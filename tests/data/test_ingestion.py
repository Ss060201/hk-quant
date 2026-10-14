"""Ingestion pipeline tests with a fake provider (no network)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.data.corporate_actions import (
    canonicalize_corporate_actions,
    parse_dividend_scheme,
)
from hk_quant.data.ingestion import (
    ingest_corporate_actions,
    ingest_daily_prices,
    ingest_stock_master,
)
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


def test_raw_saved_before_normalize_failure_is_recovered_without_refetch(tmp_path) -> None:
    class FlakyProvider(FakeProvider):
        calls = 0
        fail = True

        def fetch_raw_daily_prices(self, stock_ids, start_date=None, end_date=None):
            self.calls += 1
            return super().fetch_raw_daily_prices(stock_ids, start_date, end_date)

        def normalize_daily_prices(self, raw, stock_id):
            if self.fail:
                raise ValueError("synthetic normalization failure")
            return super().normalize_daily_prices(raw, stock_id)

    provider = FlakyProvider()
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    args = {"stock_ids": ["0700"], "start_date": "2025-01-01", "end_date": "2025-01-31"}
    with pytest.raises(ValueError, match="normalization failure"):
        ingest_daily_prices(provider, storage, **args)
    assert storage.raw_daily_prices_exists("fake", "0700", "2025-01-01", "2025-01-31")
    assert not storage.daily_prices_completed("fake", "0700", "2025-01-01", "2025-01-31")

    provider.fail = False
    assert len(ingest_daily_prices(provider, storage, **args)) == 2
    assert provider.calls == 1
    assert storage.daily_prices_completed("fake", "0700", "2025-01-01", "2025-01-31")


def test_processed_failure_after_partial_save_retries_from_raw(tmp_path, monkeypatch) -> None:
    class CountingProvider(FakeProvider):
        calls = 0

        def fetch_raw_daily_prices(self, stock_ids, start_date=None, end_date=None):
            self.calls += 1
            return super().fetch_raw_daily_prices(stock_ids, start_date, end_date)

    provider = CountingProvider()
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    original = storage.save_daily_prices

    def fail_after_write(frame):
        original(frame)
        raise RuntimeError("synthetic disk failure after processed write")

    monkeypatch.setattr(storage, "save_daily_prices", fail_after_write)
    args = {"stock_ids": ["0700"], "start_date": "2025-01-01", "end_date": "2025-01-31"}
    with pytest.raises(RuntimeError, match="disk failure"):
        ingest_daily_prices(provider, storage, **args)
    assert not storage.daily_prices_completed("fake", "0700", "2025-01-01", "2025-01-31")
    monkeypatch.setattr(storage, "save_daily_prices", original)
    assert len(ingest_daily_prices(provider, storage, **args)) == 2
    assert provider.calls == 1
    assert len(storage.load_daily_prices()) == 2
    assert storage.daily_prices_completed("fake", "0700", "2025-01-01", "2025-01-31")
    assert ingest_daily_prices(provider, storage, **args).empty

    # An incomplete processed partition invalidates the completion record.
    (storage.processed_root / "daily_prices" / "0700" / "2025" / "01" / "data.parquet").unlink()
    assert not storage.daily_prices_completed("fake", "0700", "2025-01-01", "2025-01-31")
    assert len(ingest_daily_prices(provider, storage, **args)) == 2
    assert provider.calls == 1


def test_provider_symbol_completion_uses_canonical_stock_partition(tmp_path) -> None:
    provider = FakeProvider()
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    args = {"stock_ids": ["00700"], "start_date": "2025-01-01", "end_date": "2025-01-31"}
    assert len(ingest_daily_prices(provider, storage, **args)) == 2
    assert storage.daily_prices_completed("fake", "00700", "2025-01-01", "2025-01-31")
    assert ingest_daily_prices(provider, storage, **args).empty


def test_ingest_corporate_actions_preserves_same_day_distributions(tmp_path) -> None:
    class CorporateProvider:
        name = "fake"

        def fetch_raw_corporate_actions(self, stock_id: str) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "最新公告日期": ["2009-05-14", "2009-05-14"],
                    "除净日": ["2009-05-06", "2009-05-06"],
                    "分红方案": ["每股派港币0.25元", "每股派港币0.10元"],
                    "symbol": ["00700", "00700"],
                }
            )

        def normalize_corporate_actions(self, raw: pd.DataFrame) -> pd.DataFrame:
            rows = []
            for _, record in raw.iterrows():
                action_type, cash_amount, factor = parse_dividend_scheme(record["分红方案"])
                rows.append(
                    {
                        "stock_id": record["symbol"],
                        "event_date": record["除净日"],
                        "announcement_date": record["最新公告日期"],
                        "action_type": action_type,
                        "factor": factor,
                        "cash_amount": cash_amount,
                    }
                )
            return canonicalize_corporate_actions(pd.DataFrame(rows), self.name)

    provider = CorporateProvider()
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")

    first = ingest_corporate_actions(provider, storage, stock_ids=["0700"])
    assert len(first) == 2

    # Re-ingest merges with existing data; both same-day distributions survive.
    second = ingest_corporate_actions(provider, storage, stock_ids=["0700"])
    assert len(second) == 2
    loaded = storage.load_corporate_actions()
    assert len(loaded) == 2
    assert sorted(loaded["cash_amount"].tolist()) == [0.1, 0.25]
