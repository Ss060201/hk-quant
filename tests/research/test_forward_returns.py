"""Forward return computation tests (hand-verifiable)."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from hk_quant.data.calendar import TradingCalendar
from hk_quant.research.events import build_events
from hk_quant.research.forward_returns import compute_forward_returns
from hk_quant.research.models import ResearchDefinition, VariableSpec


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_id": ["TEST001"] * 6,
            "trade_date": pd.to_datetime(
                ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09"]
            ),
            "turnover_rate": [0.05, 0.15, 0.25, 0.50, 0.60, 0.70],
            "close": [100.0, 102.0, 105.0, 110.0, 112.0, 115.0],
        }
    )


def _definition(periods: list[int]) -> ResearchDefinition:
    return ResearchDefinition(
        name="t",
        variable=VariableSpec(name="turnover_rate", thresholds=[0.10]),
        forward_periods=periods,
    )


def test_forward_1d_matches_hand_calculation() -> None:
    panel = _panel()
    calendar = TradingCalendar.from_prices(panel)
    events = build_events(panel, _definition([1]))

    ff = compute_forward_returns(events, panel, calendar, _definition([1]))
    returns = ff[ff["valid_sample"]]["forward_return"].tolist()
    assert returns == pytest.approx(
        [
            105.0 / 102.0 - 1,  # 0.15 event
            110.0 / 105.0 - 1,  # 0.25 event
            112.0 / 110.0 - 1,  # 0.50 event
            115.0 / 112.0 - 1,  # 0.60 event
        ]
    )


def test_forward_2d_matches_hand_calculation() -> None:
    panel = _panel()
    calendar = TradingCalendar.from_prices(panel)
    events = build_events(panel, _definition([2]))

    ff = compute_forward_returns(events, panel, calendar, _definition([2]))
    returns = ff[ff["valid_sample"]]["forward_return"].tolist()
    assert returns == pytest.approx(
        [
            110.0 / 102.0 - 1,  # 0.15 event -> 2 trading days later
            112.0 / 105.0 - 1,  # 0.25 event
            115.0 / 110.0 - 1,  # 0.50 event
        ]
    )


def test_missing_forward_date_is_invalid_not_filled() -> None:
    panel = _panel()
    calendar = TradingCalendar.from_prices(panel)
    events = build_events(panel, _definition([1]))

    ff = compute_forward_returns(events, panel, calendar, _definition([1]))
    # The last event (0.70 on 2020-01-09) has no next trading day.
    last = ff[ff["variable_value"] == 0.70].iloc[0]
    assert not bool(last["valid_sample"])
    assert math.isnan(last["forward_return"])


def test_event_on_last_day_all_periods_invalid() -> None:
    panel = _panel()
    calendar = TradingCalendar.from_prices(panel)
    events = build_events(panel, _definition([1, 2, 5]))

    ff = compute_forward_returns(events, panel, calendar, _definition([1, 2, 5]))
    last_day_rows = ff[ff["variable_value"] == 0.70]
    assert not last_day_rows["valid_sample"].any()


def test_weekend_is_skipped_via_calendar() -> None:
    panel = pd.DataFrame(
        {
            "stock_id": ["TEST001", "TEST001"],
            "trade_date": pd.to_datetime(["2020-01-03", "2020-01-06"]),
            "turnover_rate": [0.15, 0.25],
            "close": [100.0, 104.0],
        }
    )
    calendar = TradingCalendar.from_prices(panel)
    events = build_events(panel, _definition([1]))
    ff = compute_forward_returns(events, panel, calendar, _definition([1]))

    # 2020-01-03 (Fri) + 1 trading day = 2020-01-06 (Mon), not 2020-01-04
    row = ff[ff["variable_value"] == 0.15].iloc[0]
    assert row["forward_return"] == pytest.approx(104.0 / 100.0 - 1)
    assert pd.Timestamp(row["exit_date"]).date().isoformat() == "2020-01-06"
