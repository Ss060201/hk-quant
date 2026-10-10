"""Basic data quality checks for canonical data."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Iterable

import pandas as pd

from hk_quant.data import models

if TYPE_CHECKING:  # pragma: no cover - used only for type hints
    from hk_quant.data.calendar import TradingCalendar


class DataQualityError(Exception):
    """Raised when canonical data fails validation."""


#: Numeric columns that must be present and non-null.
_NUMERIC_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume", "amount")


def _require_columns(df: pd.DataFrame, required: list[str], context: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataQualityError(f"{context}: missing columns {missing}")


def validate_daily_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a canonical daily prices DataFrame.

    Raises :class:`DataQualityError` on the first problem found and returns
    the unchanged DataFrame on success.
    """
    _require_columns(
        df,
        ["stock_id", "trade_date", *_NUMERIC_COLUMNS],
        "daily prices",
    )

    if df["stock_id"].isna().any() or (df["stock_id"].astype(str).str.strip() == "").any():
        raise DataQualityError("daily prices: stock_id contains null/empty values")

    if df["trade_date"].isna().any():
        raise DataQualityError("daily prices: trade_date contains null values")

    for col in _NUMERIC_COLUMNS:
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise DataQualityError(f"daily prices: column {col!r} is not numeric")
        if df[col].isna().any():
            raise DataQualityError(f"daily prices: column {col!r} contains null values")

    # ``turnover_rate`` is optional (unavailable from some providers).
    if "turnover_rate" in df.columns:
        if not pd.api.types.is_numeric_dtype(df["turnover_rate"]):
            raise DataQualityError("daily prices: turnover_rate is not numeric")
        if (df["turnover_rate"].notna() & (df["turnover_rate"] < 0)).any():
            raise DataQualityError("daily prices: turnover_rate contains negative values")

    # OHLC sanity with a small relative tolerance: providers sometimes emit
    # close == high + 1e-5 (floating-point rounding), which is not a real
    # data error.
    scale = df[["open", "high", "low", "close"]].abs().max(axis=1) * 1e-6
    tolerance = scale.clip(lower=1e-9)
    bad_ohlc = (
        (df["high"] + tolerance < df["low"])
        | (df["high"] + tolerance < df["open"])
        | (df["high"] + tolerance < df["close"])
        | (df["low"] - tolerance > df["open"])
        | (df["low"] - tolerance > df["close"])
    )
    if bad_ohlc.any():
        examples = df.index[bad_ohlc].tolist()[:5]
        raise DataQualityError(f"daily prices: OHLC inconsistency at rows {examples}")

    if (df["volume"] < 0).any():
        raise DataQualityError("daily prices: volume contains negative values")

    if (df["amount"] < 0).any():
        raise DataQualityError("daily prices: amount contains negative values")

    if df.duplicated(subset=["stock_id", "trade_date"]).any():
        raise DataQualityError("daily prices: duplicate (stock_id, trade_date) rows")

    if df.duplicated().any():
        raise DataQualityError("daily prices: fully duplicate rows")

    return df


def validate_stock_master(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a canonical stock master DataFrame."""
    _require_columns(df, ["stock_id", "symbol", "name"], "stock master")

    if df["stock_id"].isna().any() or (df["stock_id"].astype(str).str.strip() == "").any():
        raise DataQualityError("stock master: stock_id contains null/empty values")

    if df.duplicated(subset=["stock_id"]).any():
        raise DataQualityError("stock master: duplicate stock_id rows")

    return df


def validate_fundamentals(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a canonical point-in-time fundamentals DataFrame.

    ``announcement_date`` may be null; the PIT layer handles null
    announcement dates conservatively (excluded as-of).
    """
    _require_columns(
        df,
        ["stock_id", "period_end", "announcement_date", "metric", "value"],
        "fundamentals",
    )

    if df["stock_id"].isna().any() or (df["stock_id"].astype(str).str.strip() == "").any():
        raise DataQualityError("fundamentals: stock_id contains null/empty values")

    if df["metric"].isna().any() or (df["metric"].astype(str).str.strip() == "").any():
        raise DataQualityError("fundamentals: metric contains null/empty values")

    if df["period_end"].isna().any():
        raise DataQualityError("fundamentals: period_end contains null values")

    if not pd.api.types.is_numeric_dtype(df["value"]):
        raise DataQualityError("fundamentals: value is not numeric")
    if df["value"].isna().any():
        raise DataQualityError("fundamentals: value contains null values")

    if df.duplicated(subset=["stock_id", "period_end", "metric"]).any():
        raise DataQualityError("fundamentals: duplicate (stock_id, period_end, metric) rows")

    return df


def validate_corporate_actions(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a canonical corporate actions DataFrame.

    Only structural checks are enforced. ``event_date`` vs
    ``announcement_date`` ordering is intentionally NOT hard-failed because
    real data can legitimately vary.
    """
    _require_columns(
        df,
        ["stock_id", "event_date", "action_type", "factor", "cash_amount"],
        "corporate actions",
    )

    if df["stock_id"].isna().any() or (df["stock_id"].astype(str).str.strip() == "").any():
        raise DataQualityError("corporate actions: stock_id contains null/empty values")

    if df["event_date"].isna().any():
        raise DataQualityError("corporate actions: event_date contains null values")

    unknown = set(df["action_type"].dropna()) - set(models.CORPORATE_ACTION_TYPES)
    if unknown:
        raise DataQualityError(
            f"corporate actions: unknown action_type {sorted(unknown)}"
        )

    if (df["factor"].notna() & (df["factor"] <= 0)).any():
        raise DataQualityError("corporate actions: factor must be > 0 when present")

    if (df["cash_amount"].notna() & (df["cash_amount"] < 0)).any():
        raise DataQualityError("corporate actions: cash_amount must be >= 0 when present")

    return df


def validate_universe(df: pd.DataFrame) -> pd.DataFrame:
    """Validate universe membership data (listing/delisting sanity)."""
    _require_columns(df, ["stock_id", "listing_date", "delisting_date"], "universe")

    both = df["listing_date"].notna() & df["delisting_date"].notna()
    bad = both & (
        pd.to_datetime(df["listing_date"], errors="coerce")
        > pd.to_datetime(df["delisting_date"], errors="coerce")
    )
    if bad.any():
        raise DataQualityError("universe: listing_date > delisting_date at some rows")

    return df


def validate_trade_dates(
    dates: Iterable[object], calendar: "TradingCalendar"
) -> list[date]:
    """Check that every date is a trading day in the given calendar."""
    result: list[date] = []
    bad: list[str] = []
    for value in dates:
        ts = pd.Timestamp(value)
        if ts is pd.NaT:
            bad.append(str(value))
            continue
        if not calendar.is_trading_day(ts):
            bad.append(ts.date().isoformat())
        else:
            result.append(ts.date())

    if bad:
        raise DataQualityError(f"dates are not trading days: {sorted(set(bad))}")
    return result
