"""Ingestion pipeline tests with a fake provider (no network)."""

from __future__ import annotations

import pandas as pd

from hk_quant.data.ingestion import ingest_daily_prices, ingest_stock_master
from hk_quant.data.normalization import (
    canonicalize_daily_prices,
    canonicalize_stock_master,
)
from hk_quant.data.storage import DataStorage


class FakeProvider:
    """Provider fake returning small, well-formed datasets."""

    name = "fake"

    def fetch_raw_stock_master(self) -> pd.DataFrame:
        return pd.DataFrame({"代码": ["00700", "02388"], "中文名称": ["Tencent", "BOC HK"]})

    def normalize_stock_master(self, raw: pd.DataFrame) -> pd.DataFrame:
        df = raw.rename(columns={"代码": "symbol", "中文名称": "name"})
        df["listing_date"] = None
        df["delisting_date"] = None
        df["status"] = "listed"
        return canonicalize_stock_master(df, self.name)

    def fetch_raw_daily_prices(
        self, stock_ids: list[str], start_date: str | None = None, end_date: str | None = None
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": ["2025-01-02", "2025-01-03"],
                "open": [430.0, 432.0],
                "high": [435.0, 436.0],
                "low": [425.0, 429.0],
                "close": [432.0, 433.0],
                "volume": [12345.0, 20000.0],
                "amount": [5e6, 6e6],
                "symbol": ["00700", "00700"],
            }
        )

    def normalize_daily_prices(self, raw: pd.DataFrame, stock_id: str) -> pd.DataFrame:
        df = raw.rename(columns={"date": "trade_date", "amount": "amount"})
        df["stock_id"] = stock_id
        df["turnover_rate"] = None
        return canonicalize_daily_prices(df, self.name)


def test_ingest_stock_master(tmp_path) -> None:
    provider = FakeProvider()
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")

    out = ingest_stock_master(provider, storage)
    assert len(out) == 2
    assert storage.load_stock_master()["stock_id"].tolist() == ["0700", "2388"]


def test_ingest_daily_prices(tmp_path) -> None:
    provider = FakeProvider()
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")

    out = ingest_daily_prices(
        provider,
        storage,
        stock_ids=["0700"],
        start_date="2025-01-01",
        end_date="2025-01-31",
    )
    assert len(out) == 2
    assert len(storage.load_daily_prices()) == 2


def test_ingest_skips_existing_raw(tmp_path) -> None:
    provider = FakeProvider()
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")

    ingest_daily_prices(
        provider,
        storage,
        stock_ids=["0700"],
        start_date="2025-01-01",
        end_date="2025-01-31",
    )
    second = ingest_daily_prices(
        provider,
        storage,
        stock_ids=["0700"],
        start_date="2025-01-01",
        end_date="2025-01-31",
    )
    assert second.empty  # already ingested -> skipped
