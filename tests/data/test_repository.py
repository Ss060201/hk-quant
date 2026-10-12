"""Repository query tests (DuckDB over processed parquet)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.data.repository import DataRepository
from hk_quant.data.storage import DataStorage


def test_repository_daily_prices_query(tmp_path, prices_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    storage.save_daily_prices(prices_df)

    repo = DataRepository(tmp_path / "processed")
    all_rows = repo.get_daily_prices(stock_ids=["0700"])
    assert len(all_rows) == 3

    jan = repo.get_daily_prices(stock_ids=["0700"], start_date="2025-01-01", end_date="2025-01-31")
    assert len(jan) == 2

    feb = repo.get_daily_prices(stock_ids=["0700"], start_date="2025-02-01", end_date="2025-02-28")
    assert len(feb) == 1
    assert feb.loc[0, "close"] == 444.0


def test_repository_empty_returns_empty(tmp_path) -> None:
    repo = DataRepository(tmp_path / "processed")
    assert repo.get_daily_prices(stock_ids=["0700"]).empty
    assert repo.get_stock_master().empty


def test_repository_stock_master(tmp_path, master_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    storage.save_stock_master(master_df)

    repo = DataRepository(tmp_path / "processed")
    result = repo.get_stock_master()
    assert result["stock_id"].tolist() == ["0700", "2388"]


def test_repository_parameterized_stock_filter(tmp_path, prices_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    storage.save_daily_prices(prices_df)
    repo = DataRepository(storage.processed_root)
    assert repo.get_daily_prices(stock_ids=["0700' OR TRUE --"]).empty
    assert len(repo.get_daily_prices(stock_ids=["0700"])) == 3


def test_repository_adjusted_as_of_excludes_future_actions(tmp_path, prices_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    storage.save_daily_prices(prices_df)
    storage.save_corporate_actions(pd.DataFrame({
        "stock_id": ["0700"],
        "event_date": [pd.Timestamp("2025-02-03")],
        "announcement_date": [pd.Timestamp("2025-01-02")],
        "action_type": ["split"], "factor": [2.0], "cash_amount": [None],
        "source": ["synthetic"], "ingested_at": [pd.Timestamp("2025-02-03", tz="UTC")],
    }))
    repo = DataRepository(storage.processed_root)
    jan = repo.get_prices(stock_ids=["0700"], end_date="2025-01-03", adjusted=True)
    assert jan["close"].tolist() == [432.0, 433.0]
    feb = repo.get_prices(stock_ids=["0700"], end_date="2025-02-03", adjusted=True)
    assert feb["close"].tolist() == [216.0, 216.5, 444.0]
    as_of = repo.get_prices(stock_ids=["0700"], adjusted=True, as_of_date="2025-01-03")
    assert as_of["close"].tolist() == [432.0, 433.0]
    with pytest.raises(ValueError, match="end_date must not exceed as_of_date"):
        repo.get_prices(stock_ids=["0700"], end_date="2025-02-03",
                        adjusted=True, as_of_date="2025-01-03")
