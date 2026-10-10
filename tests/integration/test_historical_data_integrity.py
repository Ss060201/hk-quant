"""Historical data integrity integration tests.

Contains:

* a complete **synthetic** scenario exercising every Phase 3 layer
  end-to-end (deterministic, no network);
* real-data checks for what AKShare can actually provide (observed trading
  calendar and dividend events).

Historical universe (listing/delisting dates) is NOT available from the
current provider; that path is covered by the unit tests via
``UniverseDataUnavailableError`` and documented in the README.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from hk_quant.data import models
from hk_quant.data.calendar import TradingCalendar
from hk_quant.data.repository import DataRepository
from hk_quant.data.storage import DataStorage

pytestmark = pytest.mark.integration


def _save_synthetic_scenario(storage: DataStorage) -> None:
    storage.save_stock_master(
        pd.DataFrame(
            {
                "stock_id": ["TEST001"],
                "symbol": ["TEST001"],
                "name": ["Synthetic Corp"],
                "listing_date": pd.to_datetime(["2020-01-01"]),
                "delisting_date": [pd.NaT],
                "status": ["listed"],
                "source": ["synthetic"],
                "ingested_at": [pd.Timestamp.now("UTC")],
            }
        )
    )

    storage.save_fundamentals(
        pd.DataFrame(
            {
                "stock_id": ["TEST001"],
                "period_end": pd.to_datetime(["2020-06-30"]),
                "announcement_date": pd.to_datetime(["2020-08-15"]),
                "effective_date": [pd.NaT],
                "metric": ["revenue"],
                "value": [100.0],
                "source": ["synthetic"],
                "ingested_at": [pd.Timestamp.now("UTC")],
            }
        )
    )

    storage.save_corporate_actions(
        pd.DataFrame(
            {
                "stock_id": ["TEST001"],
                "event_date": pd.to_datetime(["2020-09-01"]),
                "announcement_date": pd.to_datetime(["2020-08-15"]),
                "action_type": [models.ACTION_SPLIT],
                "factor": [2.0],
                "cash_amount": [None],
                "source": ["synthetic"],
                "ingested_at": [pd.Timestamp.now("UTC")],
            }
        )
    )

    storage.save_daily_prices(
        pd.DataFrame(
            {
                "stock_id": ["TEST001"] * 4,
                "trade_date": [
                    date(2020, 8, 28),
                    date(2020, 8, 31),
                    date(2020, 9, 1),
                    date(2020, 9, 2),
                ],
                "open": [98.0, 100.0, 50.0, 51.0],
                "high": [100.0, 102.0, 51.0, 52.0],
                "low": [97.0, 99.0, 49.0, 50.0],
                "close": [100.0, 102.0, 50.0, 51.0],
                "volume": [1000.0] * 4,
                "amount": [100000.0] * 4,
                "turnover_rate": [float("nan")] * 4,
                "source": ["synthetic"] * 4,
                "ingested_at": [pd.Timestamp.now("UTC")] * 4,
            }
        )
    )


def test_synthetic_historical_scenario(tmp_path) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    _save_synthetic_scenario(storage)
    repo = DataRepository(storage.processed_root)

    # Fundamental announced 2020-08-15: invisible on 2020-07-01, visible 2020-08-20
    assert repo.get_data_as_of("2020-07-01").empty
    visible = repo.get_data_as_of("2020-08-20")
    assert visible["stock_id"].tolist() == ["TEST001"]
    assert visible["value"].tolist() == [100.0]

    # Universe includes TEST001 (listed 2020-01-01, never delisted)
    universe = repo.get_universe("2020-07-01")
    assert universe["stock_id"].tolist() == ["TEST001"]

    # Split is queryable
    actions = repo.get_corporate_actions(stock_ids=["TEST001"])
    assert actions["action_type"].tolist() == [models.ACTION_SPLIT]

    # Raw vs adjusted prices are clearly distinguishable
    raw = repo.get_prices(stock_ids=["TEST001"], adjusted=False)
    adj = repo.get_prices(stock_ids=["TEST001"], adjusted=True)
    raw_row = raw[raw["trade_date"] == pd.Timestamp("2020-08-31")].iloc[0]
    adj_row = adj[adj["trade_date"] == pd.Timestamp("2020-08-31")].iloc[0]
    assert raw_row["close"] == 102.0
    assert adj_row["close"] == 51.0  # 102 / 2.0 split factor

    # Observed calendar derived from prices
    cal = repo.get_calendar()
    assert cal.is_trading_day("2020-08-31")
    assert not cal.is_trading_day("2020-08-29")  # Saturday


def test_real_observed_calendar_from_akshare() -> None:
    from hk_quant.data.adapters.akshare import AKShareProvider

    provider = AKShareProvider()
    prices = provider.get_daily_prices(
        stock_ids=["0700"], start_date="2025-01-01", end_date="2025-01-31"
    )
    assert not prices.empty

    cal = TradingCalendar.from_prices(prices)
    assert not cal.is_trading_day("2025-01-01")  # New Year's Day (observed)
    assert cal.is_trading_day("2025-01-02")


def test_real_akshare_corporate_actions() -> None:
    import requests

    from hk_quant.data.adapters.akshare import AKShareProvider

    provider = AKShareProvider()
    try:
        actions = provider.get_corporate_actions(stock_ids=["0700"])
    except requests.exceptions.ConnectionError as exc:
        pytest.skip(f"AKShare dividend endpoint unreachable: {exc}")

    assert not actions.empty
    assert set(actions["action_type"]).issubset(set(models.CORPORATE_ACTION_TYPES))
    assert actions["event_date"].notna().any()
