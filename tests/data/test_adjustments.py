"""Raw vs adjusted price tests."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from hk_quant.data.adjustments import adjust_prices
from hk_quant.data.models import ACTION_BONUS, ACTION_DIVIDEND, ACTION_SPLIT


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
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
            "turnover": [100000.0] * 4,
            "source": ["synthetic"] * 4,
            "ingested_at": [pd.Timestamp.now("UTC")] * 4,
        }
    )


def _split() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_id": ["TEST001"],
            "event_date": pd.to_datetime(["2020-09-01"]),
            "announcement_date": pd.to_datetime(["2020-08-15"]),
            "action_type": [ACTION_SPLIT],
            "factor": [2.0],
            "cash_amount": [None],
            "source": ["synthetic"],
            "ingested_at": [pd.Timestamp.now("UTC")],
        }
    )


def test_split_adjusts_pre_event_prices_only() -> None:
    adjusted = adjust_prices(_prices(), _split())

    # before split: close divided by 2
    assert adjusted.loc[0, "close"] == pytest.approx(50.0)
    assert adjusted.loc[1, "close"] == pytest.approx(51.0)
    # on/after split: unchanged
    assert adjusted.loc[2, "close"] == pytest.approx(50.0)
    assert adjusted.loc[3, "close"] == pytest.approx(51.0)


def test_raw_prices_unchanged() -> None:
    raw = _prices()
    assert raw.loc[1, "close"] == 102.0
    assert raw.loc[2, "close"] == 50.0


def test_empty_actions_no_change() -> None:
    prices = _prices()
    adjusted = adjust_prices(prices, pd.DataFrame())
    pd.testing.assert_frame_equal(adjusted, prices)


def test_dividend_not_applied_to_price() -> None:
    prices = _prices()
    dividend = pd.DataFrame(
        {
            "stock_id": ["TEST001"],
            "event_date": pd.to_datetime(["2020-09-01"]),
            "announcement_date": pd.to_datetime(["2020-08-15"]),
            "action_type": [ACTION_DIVIDEND],
            "factor": [None],
            "cash_amount": [1.0],
            "source": ["synthetic"],
            "ingested_at": [pd.Timestamp.now("UTC")],
        }
    )
    adjusted = adjust_prices(prices, dividend)
    pd.testing.assert_frame_equal(adjusted, prices)


def test_bonus_adjusts_by_share_factor() -> None:
    bonus = pd.DataFrame(
        {
            "stock_id": ["TEST001"],
            "event_date": pd.to_datetime(["2020-09-01"]),
            "announcement_date": pd.to_datetime(["2020-08-15"]),
            "action_type": [ACTION_BONUS],
            "factor": [1.1],  # 1 bonus share per 10 held
            "cash_amount": [None],
            "source": ["synthetic"],
            "ingested_at": [pd.Timestamp.now("UTC")],
        }
    )
    adjusted = adjust_prices(_prices(), bonus)
    assert adjusted.loc[1, "close"] == pytest.approx(102.0 / 1.1)
    assert adjusted.loc[2, "close"] == pytest.approx(50.0)


def test_as_of_prices_ignore_future_or_undated_corporate_actions() -> None:
    prices = _prices()
    actions = pd.concat([
        _split(),
        _split().assign(event_date=pd.Timestamp("2020-10-01"), announcement_date=pd.Timestamp("2020-09-15")),
        _split().assign(event_date=pd.Timestamp("2020-08-31"), announcement_date=pd.NaT),
    ], ignore_index=True)
    before = adjust_prices(prices, actions, as_of_date="2020-08-31")
    assert before.loc[0, "close"] == pytest.approx(100.0)
    assert before.loc[1, "close"] == pytest.approx(102.0)
    after = adjust_prices(prices, actions, as_of_date="2020-09-02")
    assert after.loc[1, "close"] == pytest.approx(51.0)
    assert after.loc[2, "close"] == pytest.approx(50.0)


def test_late_announced_action_does_not_rewrite_earlier_view() -> None:
    late = _split().assign(announcement_date=pd.Timestamp("2020-09-02"))
    before_announcement = adjust_prices(_prices(), late, as_of_date="2020-09-01")
    after_announcement = adjust_prices(_prices(), late, as_of_date="2020-09-02")
    assert before_announcement.loc[1, "close"] == 102.0
    assert after_announcement.loc[1, "close"] == 51.0
