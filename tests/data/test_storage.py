"""Storage save/load round-trip tests."""

from __future__ import annotations

import pandas as pd

from hk_quant.data.storage import DataStorage


def test_daily_prices_round_trip(tmp_path, prices_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    paths = storage.save_daily_prices(prices_df)
    assert len(paths) == 2  # 2025-01 and 2025-02

    loaded = storage.load_daily_prices()
    assert len(loaded) == 3
    assert set(loaded["stock_id"]) == {"0700"}


def test_daily_prices_filter(tmp_path, prices_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    storage.save_daily_prices(prices_df)

    jan = storage.load_daily_prices(start_date="2025-01-01", end_date="2025-01-31")
    assert len(jan) == 2

    feb = storage.load_daily_prices(stock_id="0700", start_date="2025-02-01", end_date="2025-02-28")
    assert len(feb) == 1
    assert feb.loc[0, "trade_date"] == pd.Timestamp("2025-02-03")


def test_daily_prices_preserve_previous_same_month_and_replace_overlapping_day(tmp_path, prices_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    storage.save_daily_prices(prices_df.iloc[[0]])
    storage.save_daily_prices(prices_df.iloc[[1]])
    assert storage.load_daily_prices()["trade_date"].tolist() == [
        pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")
    ]
    amended = prices_df.iloc[[0]].copy()
    amended["close"] = 434.0
    storage.save_daily_prices(amended)
    loaded = storage.load_daily_prices()
    assert len(loaded) == 2
    assert loaded["close"].tolist() == [434.0, 433.0]


def test_stock_master_round_trip(tmp_path, master_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    storage.save_stock_master(master_df)

    loaded = storage.load_stock_master()
    assert loaded["stock_id"].tolist() == ["0700", "2388"]
    assert loaded["name"].tolist() == ["Tencent", "BOC HK"]


def test_raw_save_and_exists(tmp_path) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    raw = pd.DataFrame({"date": ["2025-01-02"], "close": [432.0]})
    storage.save_raw_daily_prices(
        raw, provider="akshare", run_date="2025-09-24",
        stock_id="0700", start_date="2025-01-01", end_date="2025-01-31",
    )
    assert storage.raw_daily_prices_exists(
        "akshare", "0700", "2025-01-01", "2025-01-31"
    )
    assert not storage.raw_daily_prices_exists(
        "akshare", "0700", "2025-02-01", "2025-02-28"
    )
