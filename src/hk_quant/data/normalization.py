"""Stock id normalization and canonical dataframe construction.

Provider adapters are responsible for renaming provider-specific columns
into canonical names. This module then coerces types, adds bookkeeping
columns and fixes the canonical column order in a provider-independent way.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from hk_quant.data import models


def normalize_stock_id(symbol: object) -> str:
    """Normalize a provider stock symbol into the canonical HK stock id.

    Examples::

        "00700"   -> "0700"
        "0700"    -> "0700"
        "0700.HK" -> "0700"
        "HK.0700" -> "0700"
        700       -> "0700"
    """
    if symbol is None:
        raise ValueError("stock id / symbol cannot be None")

    text = str(symbol).strip().upper()
    for suffix in (".HK", ".HKEX"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    if text.startswith("HK.") or text.startswith("HKEX."):
        text = text.split(".", 1)[1]

    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise ValueError(f"Cannot normalize stock id from {symbol!r}")

    number = int(digits)
    if number == 0:
        raise ValueError(f"Invalid zero stock id from {symbol!r}")
    return f"{number:04d}"


def normalize_stock_ids(symbols: Iterable[object]) -> list[str]:
    """Normalize a collection of symbols into canonical stock ids."""
    return [normalize_stock_id(s) for s in symbols]


def _to_date_series(series: pd.Series) -> pd.Series:
    """Parse a series into ``datetime.date`` objects (``None`` for invalid)."""
    parsed = pd.to_datetime(series, errors="coerce")
    return pd.Series(
        [d.date() if pd.notna(d) else None for d in parsed],
        index=series.index,
        dtype="object",
    )


def _utc_now() -> pd.Timestamp:
    """Return the current UTC time as a pandas timestamp."""
    return pd.Timestamp(datetime.now(timezone.utc))


def canonicalize_daily_prices(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Convert a column-renamed DataFrame into the canonical daily schema.

    Expects the DataFrame to already use canonical column names
    (``stock_id``, ``trade_date``, ``open``, ``high``, ``low``, ``close``,
    ``volume``, ``turnover``). Type coercion, bookkeeping columns and
    ordering are applied here.
    """
    result = df.copy()
    result["stock_id"] = result["stock_id"].map(normalize_stock_id)
    result["trade_date"] = _to_date_series(result["trade_date"])
    for col in ("open", "high", "low", "close", "volume", "amount", "turnover_rate"):
        if col not in result.columns:
            result[col] = None
        result[col] = pd.to_numeric(result[col], errors="coerce")
    result["source"] = source
    result["ingested_at"] = _utc_now()
    result = result[list(models.DAILY_PRICE_COLUMNS)]
    return result.sort_values("stock_id").reset_index(drop=True)


def canonicalize_stock_master(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Convert a column-renamed DataFrame into the canonical master schema.

    Expects columns ``symbol``, ``name``, ``listing_date``, ``delisting_date``
    and ``status``. ``listing_date``/``delisting_date`` may be null.
    """
    result = df.copy()
    if "symbol" not in result.columns:
        raise ValueError("stock master data must contain a 'symbol' column")

    result["stock_id"] = result["symbol"].map(normalize_stock_id)
    for col in ("listing_date", "delisting_date"):
        if col not in result.columns:
            result[col] = None
        result[col] = _to_date_series(result[col])
    if "status" not in result.columns:
        result["status"] = None
    result["source"] = source
    result["ingested_at"] = _utc_now()
    result = result[list(models.STOCK_MASTER_COLUMNS)]
    return result.sort_values("stock_id").reset_index(drop=True)
