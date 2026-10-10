"""Data quality validation tests."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.data.quality import DataQualityError, validate_daily_prices, validate_stock_master


def _valid_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_id": ["0700", "0700"],
            "trade_date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "open": [430.0, 432.0],
            "high": [435.0, 436.0],
            "low": [425.0, 429.0],
            "close": [432.0, 433.0],
            "volume": [12345.0, 20000.0],
            "amount": [5e6, 6e6],
            "turnover_rate": [float("nan"), float("nan")],
            "source": ["akshare", "akshare"],
            "ingested_at": [pd.Timestamp.now("UTC")] * 2,
        }
    )


def test_valid_prices_pass() -> None:
    validate_daily_prices(_valid_prices())


def test_missing_column_raises() -> None:
    df = _valid_prices().drop(columns=["amount"])
    with pytest.raises(DataQualityError, match="missing columns"):
        validate_daily_prices(df)


def test_high_below_low_raises() -> None:
    df = _valid_prices()
    df.loc[0, "high"] = 100.0
    with pytest.raises(DataQualityError, match="OHLC"):
        validate_daily_prices(df)


def test_negative_volume_raises() -> None:
    df = _valid_prices()
    df.loc[0, "volume"] = -1
    with pytest.raises(DataQualityError, match="volume"):
        validate_daily_prices(df)


def test_duplicate_rows_raise() -> None:
    df = pd.concat([_valid_prices(), _valid_prices().iloc[[0]]], ignore_index=True)
    with pytest.raises(DataQualityError, match="duplicate"):
        validate_daily_prices(df)


def test_non_numeric_close_raises() -> None:
    df = _valid_prices()
    df["close"] = df["close"].astype(str)
    with pytest.raises(DataQualityError, match="not numeric"):
        validate_daily_prices(df)


def test_stock_master_duplicate_raises() -> None:
    df = pd.DataFrame(
        {
            "stock_id": ["0700", "0700"],
            "symbol": ["00700", "00700"],
            "name": ["A", "B"],
        }
    )
    with pytest.raises(DataQualityError, match="duplicate stock_id"):
        validate_stock_master(df)
