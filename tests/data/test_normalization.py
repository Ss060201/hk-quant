"""Stock id normalization and canonicalization tests."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from hk_quant.data import models
from hk_quant.data.normalization import (
    canonicalize_daily_prices,
    canonicalize_stock_master,
    normalize_stock_id,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00700", "0700"),
        ("0700", "0700"),
        ("700", "0700"),
        ("0700.HK", "0700"),
        ("hk.0700", "0700"),
        ("02388", "2388"),
        (700, "0700"),
        (" 00700.HK ", "0700"),
    ],
)
def test_normalize_stock_id(raw: object, expected: str) -> None:
    assert normalize_stock_id(raw) == expected


def test_normalize_stock_id_invalid() -> None:
    with pytest.raises(ValueError):
        normalize_stock_id(None)
    with pytest.raises(ValueError):
        normalize_stock_id("ABC")
    with pytest.raises(ValueError):
        normalize_stock_id("00000")


def test_canonicalize_daily_prices() -> None:
    df = pd.DataFrame(
        {
            "stock_id": ["00700"],
            "trade_date": ["2025-01-02"],
            "open": ["430"],
            "high": ["435"],
            "low": ["425"],
            "close": ["432"],
            "volume": ["12345"],
            "amount": ["5000000"],
        }
    )
    result = canonicalize_daily_prices(df, "akshare")
    assert list(result.columns) == list(models.DAILY_PRICE_COLUMNS)
    assert result.loc[0, "stock_id"] == "0700"
    assert result.loc[0, "trade_date"] == date(2025, 1, 2)
    assert result.loc[0, "source"] == "akshare"
    assert pd.notna(result.loc[0, "ingested_at"])


def test_canonicalize_stock_master() -> None:
    df = pd.DataFrame(
        {
            "symbol": ["00700"],
            "name": ["Tencent"],
            "listing_date": [None],
            "delisting_date": [None],
            "status": ["listed"],
        }
    )
    result = canonicalize_stock_master(df, "akshare")
    assert list(result.columns) == list(models.STOCK_MASTER_COLUMNS)
    assert result.loc[0, "stock_id"] == "0700"
    assert result.loc[0, "source"] == "akshare"
