"""Exploratory grid records all trials and protects held-out outcomes."""

import pandas as pd
import pytest

from hk_quant.research.multivariable import (
    MultivariableConfig, ResearchFieldUnavailableError,
    benjamini_hochberg, estimate_grid_size, run_multivariable_research,
)


def _panel() -> pd.DataFrame:
    days = pd.bdate_range("2022-01-03", periods=80)
    rows = []
    for i, day in enumerate(days[:-3]):
        for stock in ("A", "B"):
            rows.append({
                "stock_id": stock, "event_date": day,
                "exit_date": days[i + 3], "forward_period": 3,
                "momentum_20": (i % 8) / 10,
                "volatility_20": 0.05 + (i % 4) / 20,
                "sector": "S1" if stock == "A" else "S2",
                "forward_return": (0.02 if stock == "A" else -0.01) + (i % 3) / 300,
            })
    return pd.DataFrame(rows)


def _config(**kwargs) -> MultivariableConfig:
    return MultivariableConfig(
        thresholds={"momentum_20": (0.1, 0.3, 0.5), "volatility_20": (0.05, 0.1)},
        forward_periods=(3,),
        available_fields=frozenset({"momentum_20", "volatility_20", "sector"}),
        min_samples=8, min_dates=4, block_length_days=3,
        bootstrap_reps=50, subgroup_field="sector", **kwargs,
    )


def test_grid_all_trials_and_holdout_label_purge() -> None:
    panel = _panel()
    config = _config(discovery_end="2022-03-02", confirmation_start="2022-03-03")
    result = run_multivariable_research(panel, config)
    assert result.status == "EXPLORATORY"
    assert result.planned_combinations == result.calculated_combinations == 6
    assert len(result.grid) == 6
    assert result.grid["q_bh_exploratory"].notna().any()
    assert (result.grid["q_bh_exploratory"].dropna()
            >= result.grid.loc[result.grid["q_bh_exploratory"].notna(), "p_exploratory"]).all()
    assert "confirmation_mean" in result.grid.columns
    assert not result.subgroups.empty
    assert any("purged" in warning for warning in result.warnings)


def test_missing_turnover_never_replaced_by_amount() -> None:
    panel = _panel()
    panel["amount"] = 100
    config = MultivariableConfig(
        thresholds={"turnover_rate": (0.1,)}, forward_periods=(3,),
        available_fields=frozenset({"amount"}),
    )
    with pytest.raises(ResearchFieldUnavailableError, match="turnover_rate"):
        run_multivariable_research(panel, config)


def test_grid_bound_checked_before_run() -> None:
    config = MultivariableConfig(
        thresholds={"a": tuple(range(12)), "b": tuple(range(12))},
        forward_periods=(1, 2), available_fields=frozenset({"a", "b"}),
        max_combinations=100,
    )
    with pytest.raises(ValueError, match="288 combinations"):
        estimate_grid_size(config)


def test_nested_hypotheses_are_counted_and_missing_p_remain_null() -> None:
    q = benjamini_hochberg([0.01, 0.04, None], hypotheses=4)
    assert q == pytest.approx([0.04, 0.08, None])


def test_invalid_holdout_boundary_and_duplicate_outcomes() -> None:
    panel = _panel()
    with pytest.raises(ValueError, match="discovery must end"):
        run_multivariable_research(
            panel, _config(discovery_end="2022-04-01", confirmation_start="2022-04-01")
        )
    with pytest.raises(ValueError, match="duplicate"):
        run_multivariable_research(pd.concat([panel, panel.iloc[:1]]), _config())
