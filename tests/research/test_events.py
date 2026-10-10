"""Event detection tests."""

from __future__ import annotations

import pandas as pd

from hk_quant.research.events import build_events
from hk_quant.research.models import ResearchDefinition, VariableSpec


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_id": ["TEST001"] * 4,
            "trade_date": pd.to_datetime(
                ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
            ),
            "turnover_rate": [0.05, 0.15, 0.25, 0.50],
            "close": [100.0, 102.0, 105.0, 110.0],
        }
    )


def _definition(thresholds: list[float], event_mode: str = "daily") -> ResearchDefinition:
    return ResearchDefinition(
        name="t",
        variable=VariableSpec(name="turnover_rate", thresholds=thresholds),
        forward_periods=[1],
        event_mode=event_mode,
    )


def test_daily_mode_creates_event_every_above_day() -> None:
    events = build_events(_panel(), _definition([0.10]))
    assert len(events) == 3  # 0.15, 0.25, 0.50 all > 0.10


def test_first_crossing_mode_only_first_crossing() -> None:
    events = build_events(_panel(), _definition([0.10], event_mode="first_crossing"))
    assert len(events) == 1
    assert events.loc[0, "variable_value"] == 0.15


def test_threshold_exactly_equal_is_not_event() -> None:
    panel = _panel()
    panel.loc[0, "turnover_rate"] = 0.10  # exactly equal
    events = build_events(panel, _definition([0.10]))
    assert len(events) == 3  # only the three strictly-above rows


def test_zero_and_negative_values_do_not_trigger() -> None:
    panel = pd.DataFrame(
        {
            "stock_id": ["TEST001", "TEST001"],
            "trade_date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "turnover_rate": [0.0, -0.5],
            "close": [100.0, 100.0],
        }
    )
    events = build_events(panel, _definition([0.10]))
    assert events.empty


def test_duplicate_panel_rows_do_not_duplicate_events() -> None:
    panel = pd.concat([_panel(), _panel().iloc[[1]]], ignore_index=True)
    events = build_events(panel, _definition([0.10]))
    assert len(events) == 3  # duplicate row deduplicated


def test_missing_value_does_not_trigger() -> None:
    panel = _panel()
    panel.loc[1, "turnover_rate"] = float("nan")
    events = build_events(panel, _definition([0.10]))
    assert 1 not in events["variable_value"].tolist() or len(events) == 2
    assert len(events) == 2
