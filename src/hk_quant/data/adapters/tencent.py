"""Tencent Finance HK daily OHLCV adapter (backup / second source).

Endpoint format and the raw ``kline`` vs forward-adjusted ``fqkline``
distinction are adapted from HKUDS/Vibe-Trading (MIT License):

    https://github.com/HKUDS/Vibe-Trading
    Copyright (c) 2026 Vibe-Trading Contributors

Only the RAW ``kline`` series is used for canonical prices. The
forward-adjusted ``fqkline`` series is never used, so adjusted prices can
never be mistaken for raw prices.

Tencent does NOT provide trading amount (成交額); ``amount`` stays null. Do
not use this provider to overwrite a Sina ``amount`` field, and do not treat
its ``volume`` as amount.
"""

from __future__ import annotations

import json
import math
import urllib.request
from datetime import date, timedelta
from typing import Sequence

import pandas as pd

from hk_quant.data import models
from hk_quant.data.normalization import canonicalize_daily_prices, normalize_stock_id

_SOURCE = "tencent"

# Raw (unadjusted) series endpoint.
_BASE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"

# Tencent caps a single response at ``_PAGE_SIZE`` bars and serves the LAST
# bars of the requested window (verified empirically). Multi-year windows are
# paginated backward until the requested start date is reached.
_PAGE_SIZE = 500
_MAX_PAGES = 12
_TIMEOUT = 15

#: Tencent kline bar order.
_BAR_COLUMNS = ["date", "open", "close", "high", "low", "volume"]

_OHLC_TOLERANCE = 1e-6


class TencentHKProvider:
    """Free, no-auth Tencent Finance HK daily OHLCV provider."""

    name = _SOURCE

    # ------------------------------------------------------------------ raw

    def _request(self, stock_id: str, start_date: str, end_date: str) -> list[list]:
        """Return raw bars for one page (at most ``_PAGE_SIZE``)."""
        code = f"hk{normalize_stock_id(stock_id).zfill(5)}"
        url = f"{_BASE_URL}?param={code},day,{start_date},{end_date},{_PAGE_SIZE}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://web.ifzq.gtimg.cn/",
            },
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if payload.get("code") not in (0, None):
            raise RuntimeError(f"tencent error reply: code={payload.get('code')}")
        node = (payload.get("data") or {}).get(code, {})
        bars = node.get("day") or []
        if not bars:
            raise ValueError("tencent raw 'day' series unavailable for this window")
        return bars

    def _paginate(self, stock_id: str, start_date: str, end_date: str) -> list[list]:
        """Walk backward until ``start_date`` is reached (or pages exhausted)."""
        collected: list[list] = []
        current_end = end_date
        for _ in range(_MAX_PAGES):
            bars = self._request(stock_id, start_date, current_end)
            collected.extend(bars)
            first_date = bars[0][0]
            if first_date <= start_date:
                break
            current_end = (pd.Timestamp(first_date) - timedelta(days=1)).strftime("%Y-%m-%d")
        return collected

    def fetch_raw_daily_prices(
        self,
        stock_ids: Sequence[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Return raw Tencent bars (with ``symbol`` and ``fetched_at``).

        Raises if the requested start date cannot be reached within the page
        budget (incomplete history is never silently truncated).
        """
        start = str(start_date) if start_date else "2000-01-01"
        end = str(end_date) if end_date else date.today().strftime("%Y-%m-%d")

        frames: list[pd.DataFrame] = []
        for symbol in stock_ids:
            stock_id = normalize_stock_id(symbol)
            bars = self._paginate(stock_id, start, end)
            if not bars:
                continue

            # Some bars carry a trailing corporate-action info dict (7th
            # element); keep only the OHLCV columns.
            frame = pd.DataFrame([bar[:6] for bar in bars], columns=_BAR_COLUMNS)
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))]

            earliest = frame["date"].min()
            if earliest > pd.Timestamp(start):
                raise ValueError(
                    f"tencent history incomplete for {stock_id}: requested {start}, "
                    f"earliest returned {earliest.date()} (source caps at {_PAGE_SIZE} bars/page)"
                )

            self._validate_ohlc(frame)
            frame["symbol"] = stock_id.zfill(5)
            frame["fetched_at"] = pd.Timestamp.now("UTC")
            frames.append(frame)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _validate_ohlc(self, frame: pd.DataFrame) -> None:
        for col in ("open", "close", "high", "low", "volume"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        bad = (
            (frame["high"] + frame["high"].abs() * _OHLC_TOLERANCE < frame["low"])
            | (frame["high"] + frame["high"].abs() * _OHLC_TOLERANCE < frame["open"])
            | (frame["high"] + frame["high"].abs() * _OHLC_TOLERANCE < frame["close"])
            | (frame["low"] - frame["low"].abs() * _OHLC_TOLERANCE > frame["open"])
            | (frame["low"] - frame["low"].abs() * _OHLC_TOLERANCE > frame["close"])
        )
        if bad.any():
            dates = frame.loc[bad, "date"].astype(str).tolist()[:5]
            raise ValueError(f"tencent OHLC inconsistency at {dates}")

    # ------------------------------------------------------------ canonical

    def normalize_daily_prices(self, raw: pd.DataFrame, stock_id: str) -> pd.DataFrame:
        """Map raw Tencent bars into the canonical daily schema.

        ``amount`` (成交額) is null: Tencent provides volume only. It must not
        be filled from ``volume``.
        """
        frame = raw.copy()
        frame["stock_id"] = normalize_stock_id(stock_id)
        frame = frame.rename(columns={"date": "trade_date"})
        frame["amount"] = None
        return canonicalize_daily_prices(frame, _SOURCE)

    def get_daily_prices(
        self,
        stock_ids: Sequence[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Return canonical daily prices (``amount``/``turnover_rate`` null)."""
        frames: list[pd.DataFrame] = []
        for stock_id in stock_ids:
            raw = self.fetch_raw_daily_prices([stock_id], start_date, end_date)
            if raw.empty:
                continue
            frames.append(self.normalize_daily_prices(raw, stock_id))
        if not frames:
            return pd.DataFrame(columns=list(models.DAILY_PRICE_COLUMNS))
        return pd.concat(frames, ignore_index=True)
