"""Canonical schema tests."""

from __future__ import annotations

from hk_quant.data.models import DAILY_PRICE_COLUMNS, STOCK_MASTER_COLUMNS


def test_daily_price_columns() -> None:
    assert DAILY_PRICE_COLUMNS[:9] == (
        "stock_id",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover_rate",
    )
    assert "source" in DAILY_PRICE_COLUMNS
    assert "ingested_at" in DAILY_PRICE_COLUMNS


def test_stock_master_columns() -> None:
    assert STOCK_MASTER_COLUMNS[:6] == (
        "stock_id",
        "symbol",
        "name",
        "listing_date",
        "delisting_date",
        "status",
    )
    assert "source" in STOCK_MASTER_COLUMNS
    assert "ingested_at" in STOCK_MASTER_COLUMNS
