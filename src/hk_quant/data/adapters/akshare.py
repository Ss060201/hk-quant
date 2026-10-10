"""AKShare data provider adapter.

All AKShare-specific code lives in this module. Nothing else in the data
layer imports the ``akshare`` package directly; upper layers should only see
canonical DataFrames through the provider interface.
"""

from __future__ import annotations

from typing import Sequence

import akshare as ak
import pandas as pd

from hk_quant.data import models
from hk_quant.data.corporate_actions import (
    canonicalize_corporate_actions,
    empty_corporate_actions,
    parse_dividend_scheme,
)
from hk_quant.data.normalization import (
    canonicalize_daily_prices,
    canonicalize_stock_master,
    normalize_stock_id,
)

_SOURCE = models.SOURCE_AKSHARE

#: ``stock_hk_daily`` (Sina backend) columns -> canonical daily columns.
#: NOTE: Sina's ``amount`` is 成交額 (trading amount), NOT 換手率 (turnover
#: rate). It maps to canonical ``amount``. ``turnover_rate`` is left null
#: because the current provider does not supply it.
_DAILY_COLUMN_MAP: dict[str, str] = {
    "date": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
}

#: ``stock_hk_spot`` columns -> canonical stock master columns.
_MASTER_COLUMN_MAP: dict[str, str] = {
    "代码": "symbol",
    "中文名称": "name",
}

#: ``stock_hk_dividend_payout_em`` columns -> canonical corporate action columns.
_DIVIDEND_COLUMN_MAP: dict[str, str] = {
    "最新公告日期": "announcement_date",
    "除净日": "event_date",
    "分红方案": "scheme",
}


def _provider_symbol(stock_id: str) -> str:
    """Map a canonical stock id to the 5-digit symbol AKShare/Sina expects."""
    return normalize_stock_id(stock_id).zfill(5)


def _require_columns(df: pd.DataFrame, required: Sequence[str], context: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{context}: missing columns {missing}; got {list(df.columns)}")


class AKShareProvider:
    """AKShare-backed market data provider.

    Returns canonical DataFrames. Raw (provider-format) responses are also
    available via ``fetch_raw_*`` methods for the ingestion pipeline to save.
    """

    name: str = _SOURCE

    # ------------------------------------------------------------ stock master

    def fetch_raw_stock_master(self) -> pd.DataFrame:
        """Return the raw AKShare ``stock_hk_spot`` response."""
        raw = ak.stock_hk_spot()
        if raw is None or raw.empty:
            raise RuntimeError("AKShare returned an empty stock master")
        return raw.copy()

    def normalize_stock_master(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Map a raw AKShare stock master response into the canonical schema."""
        _require_columns(raw, list(_MASTER_COLUMN_MAP), "AKShare stock master")

        df = raw.rename(columns=_MASTER_COLUMN_MAP)
        df = df[["symbol", "name"]].copy()
        # ``stock_hk_spot`` only provides currently listed securities, so it
        # cannot supply listing/delisting dates. Those stay null (documented
        # provider limitation), not guessed.
        df["listing_date"] = None
        df["delisting_date"] = None
        df["status"] = "listed"
        return canonicalize_stock_master(df, _SOURCE)

    def get_stock_master(self) -> pd.DataFrame:
        """Return canonical stock master data."""
        return self.normalize_stock_master(self.fetch_raw_stock_master())

    # ----------------------------------------------------------- daily prices

    def fetch_raw_daily_prices(
        self,
        stock_ids: Sequence[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Return raw AKShare daily price responses for the given stocks.

        AKShare returns full history, so the result is filtered to the
        requested date range and tagged with the provider ``symbol``.
        """
        frames: list[pd.DataFrame] = []
        for stock_id in stock_ids:
            symbol = _provider_symbol(stock_id)
            raw = ak.stock_hk_daily(symbol=symbol, adjust="")
            if raw is None or raw.empty:
                continue
            raw = raw.copy()
            raw["symbol"] = symbol
            frames.append(raw)

        if not frames:
            return pd.DataFrame()

        result = pd.concat(frames, ignore_index=True)
        dates = pd.to_datetime(result["date"], errors="coerce")
        mask = pd.Series(True, index=result.index)
        if start_date is not None:
            mask &= dates >= pd.Timestamp(start_date)
        if end_date is not None:
            mask &= dates <= pd.Timestamp(end_date)
        return result[mask].reset_index(drop=True)

    def normalize_daily_prices(self, raw: pd.DataFrame, stock_id: str) -> pd.DataFrame:
        """Map a raw AKShare daily price response into the canonical schema."""
        _require_columns(raw, list(_DAILY_COLUMN_MAP), "AKShare daily prices")

        df = raw.rename(columns=_DAILY_COLUMN_MAP)
        df["stock_id"] = normalize_stock_id(stock_id)
        # Turnover rate is unavailable from this provider; never guess it.
        df["turnover_rate"] = None
        return canonicalize_daily_prices(df, _SOURCE)

    def get_daily_prices(
        self,
        stock_ids: Sequence[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Return canonical daily prices for the given stocks and range."""
        if stock_ids is None:
            raise ValueError("stock_ids are required for AKShareProvider.get_daily_prices")

        ids = list(dict.fromkeys(normalize_stock_id(s) for s in stock_ids))
        frames: list[pd.DataFrame] = []
        for stock_id in ids:
            raw = self.fetch_raw_daily_prices([stock_id], start_date, end_date)
            if raw.empty:
                continue
            frames.append(self.normalize_daily_prices(raw, stock_id))

        if not frames:
            return pd.DataFrame(columns=list(models.DAILY_PRICE_COLUMNS))
        return pd.concat(frames, ignore_index=True)

    # ------------------------------------------------------ corporate actions

    def fetch_raw_corporate_actions(self, stock_id: str) -> pd.DataFrame:
        """Return the raw AKShare dividend history for one stock.

        AKShare currently provides dividend/stock-distribution events (via
        ``stock_hk_dividend_payout_em``); it does not provide a complete
        split/rights feed.
        """
        symbol = _provider_symbol(stock_id)
        raw = ak.stock_hk_dividend_payout_em(symbol=symbol)
        if raw is None or raw.empty:
            return pd.DataFrame()
        raw = raw.copy()
        raw["symbol"] = symbol
        return raw

    def normalize_corporate_actions(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Map a raw AKShare dividend response into canonical actions."""
        _require_columns(
            raw, list(_DIVIDEND_COLUMN_MAP), "AKShare corporate actions"
        )

        df = raw.rename(columns=_DIVIDEND_COLUMN_MAP)
        rows: list[dict] = []
        for _, record in df.iterrows():
            action_type, cash_amount, factor = parse_dividend_scheme(
                record.get("scheme")
            )
            rows.append(
                {
                    "stock_id": record.get("symbol"),
                    "event_date": record.get("event_date"),
                    "announcement_date": record.get("announcement_date"),
                    "action_type": action_type,
                    "factor": factor,
                    "cash_amount": cash_amount,
                }
            )

        frame = pd.DataFrame(rows)
        if frame.empty:
            return empty_corporate_actions()
        return canonicalize_corporate_actions(frame, _SOURCE)

    def get_corporate_actions(self, stock_ids: Sequence[str]) -> pd.DataFrame:
        """Return canonical corporate actions for the given stocks."""
        frames: list[pd.DataFrame] = []
        for stock_id in stock_ids:
            raw = self.fetch_raw_corporate_actions(stock_id)
            if raw.empty:
                continue
            frames.append(self.normalize_corporate_actions(raw))

        if not frames:
            return empty_corporate_actions()
        return pd.concat(frames, ignore_index=True)
