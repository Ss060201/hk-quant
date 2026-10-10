"""Shared fixtures for data layer tests."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest


@pytest.fixture
def prices_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_id": ["0700", "0700", "0700"],
            "trade_date": [date(2025, 1, 2), date(2025, 1, 3), date(2025, 2, 3)],
            "open": [430.0, 432.0, 440.0],
            "high": [435.0, 436.0, 445.0],
            "low": [425.0, 429.0, 439.0],
            "close": [432.0, 433.0, 444.0],
            "volume": [12345.0, 20000.0, 21000.0],
            "amount": [5e6, 6e6, 7e6],
            "turnover_rate": [float("nan"), float("nan"), float("nan")],
            "source": ["akshare"] * 3,
            "ingested_at": [pd.Timestamp.now("UTC")] * 3,
        }
    )


@pytest.fixture
def master_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_id": ["0700", "2388"],
            "symbol": ["00700", "02388"],
            "name": ["Tencent", "BOC HK"],
            "listing_date": [None, None],
            "delisting_date": [None, None],
            "status": ["listed", "listed"],
            "source": ["akshare", "akshare"],
            "ingested_at": [pd.Timestamp.now("UTC")] * 2,
        }
    )
