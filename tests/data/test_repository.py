"""Repository query tests (DuckDB over processed parquet)."""

from __future__ import annotations

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
