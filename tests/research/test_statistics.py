"""Research statistics tests."""

from __future__ import annotations

import math

import pandas as pd

from hk_quant.research.models import ResearchDefinition, VariableSpec
from hk_quant.research.statistics import bootstrap_mean_ci, summarize_forward_returns


def test_bootstrap_ci_too_small_is_unavailable() -> None:
    lower, upper = bootstrap_mean_ci(pd.Series([1.0, 2.0, 3.0]))
    assert math.isnan(lower) and math.isnan(upper)


def test_bootstrap_ci_available_for_larger_sample() -> None:
    values = pd.Series([float(i) for i in range(30)])
    lower, upper = bootstrap_mean_ci(values, seed=42)
    assert not math.isnan(lower) and not math.isnan(upper)
    assert lower <= values.mean() <= upper


def test_summarize_forward_returns() -> None:
    definition = ResearchDefinition(
        name="t",
        variable=VariableSpec(name="x", thresholds=[0.1]),
        forward_periods=[1, 5],
    )
    ff = pd.DataFrame(
        {
            "stock_id": ["A", "A", "A", "A"],
            "event_date": pd.to_datetime(["2020-01-02"] * 4),
            "variable_name": ["x"] * 4,
            "variable_value": [0.2, 0.2, 0.2, 0.2],
            "threshold": [0.1] * 4,
            "forward_period": [1, 1, 5, 5],
            "forward_return": [0.01, 0.02, 0.03, 0.04],
            "valid_sample": [True, True, True, True],
            "exit_date": pd.to_datetime(["2020-01-03", "2020-01-03", "2020-01-09", "2020-01-09"]),
        }
    )
    stats = summarize_forward_returns(ff, definition)
    row1 = stats[stats["forward_period"] == 1].iloc[0]
    row5 = stats[stats["forward_period"] == 5].iloc[0]

    assert row1["sample_count"] == 2
    assert row1["valid_sample_count"] == 2
    assert row1["mean"] == 0.015
    assert row1["median"] == 0.015
    assert row1["win_rate"] == 1.0

    assert row5["valid_sample_count"] == 2
    assert row5["mean"] == 0.035
