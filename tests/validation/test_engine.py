"""A synthetic fixed strategy compared to a fair, dated baseline."""

import pandas as pd

from hk_quant.backtest import BacktestConfig, run_backtest
from hk_quant.data.calendar import TradingCalendar
from hk_quant.experiments import ExperimentRegistry
from hk_quant.strategy.models import (
    Condition, ConditionGroup, HoldingPeriod, StrategyDefinition, UniverseSpec,
)
from hk_quant.validation.engine import run_validation
from hk_quant.validation.models import ValidationConfig


def _strategy() -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id="threshold_demo", name="Fixed price threshold", version="1.0.0",
        universe=UniverseSpec(),
        entry=ConditionGroup(logic="all", conditions=[
            Condition(source="data", field="close", operator=">", value=105.0),
        ]),
        holding_period=HoldingPeriod(value=100),
    )


class _Repository:
    def __init__(self):
        days = pd.bdate_range("2026-01-02", periods=30)
        self.calendar = TradingCalendar(days)
        self.panel = pd.DataFrame([
            {
                "stock_id": "A", "trade_date": day.date().isoformat(),
                "open": 100.0 + i, "high": 101.0 + i,
                "low": 99.0 + i, "close": 100.0 + i,
                "volume": 10000, "amount": 1_000_000.0,
            }
            for i, day in enumerate(days)
        ])

    def get_calendar(self):
        return self.calendar

    def get_data_version(self):
        return "synthetic-content-v1"

    def get_daily_prices(self, stock_ids=None, start_date=None, end_date=None):
        frame = self.panel
        if stock_ids:
            frame = frame[frame["stock_id"].isin(stock_ids)]
        if start_date:
            frame = frame[frame["trade_date"] >= str(start_date)]
        if end_date:
            frame = frame[frame["trade_date"] <= str(end_date)]
        return frame.reset_index(drop=True).copy()

    def get_prices(self, stock_ids=None, start_date=None, end_date=None, *, adjusted=False):
        return self.get_daily_prices(stock_ids, start_date, end_date)


def test_unseen_final_test_never_sent_to_backtester(tmp_path) -> None:
    repository = _Repository()
    calendar_days = repository.calendar.get_trading_days()
    seen_end_dates = []

    def traced(*args, **kwargs):
        seen_end_dates.append(pd.Timestamp(args[2]).date())
        return run_backtest(*args, **kwargs)

    registry = ExperimentRegistry(tmp_path / "experiment-registry")
    result = run_validation(
        _strategy(), calendar_days[0], calendar_days[-1], repository,
        backtest_config=BacktestConfig(
            initial_capital=1000, commission_rate=0, slippage_rate=0,
        ),
        config=ValidationConfig(walk_min_train_days=8, walk_evaluation_days=4),
        universe=["A"], registry=registry, backtest_runner=traced,
    )
    assert "test" not in result.periods
    assert not result.final_test_viewed
    assert max(seen_end_dates) == result.split.validation.end
    # Entering later trails buy-and-hold in-sample. A selected later window
    # can reverse the return difference because both positions are carried;
    # never assume the single-window ranking is a validation conclusion.
    assert result.periods["train"]["strategy_minus_baseline"]["total_return"] < 0
    assert result.periods["validation"]["strategy_minus_baseline"]["total_return"] is not None
    assert result.walk_forward
    assert result.robustness["higher_costs"]["commission_rate"] == 0.001
    assert result.diagnostics["sector"]["status"] == "UNAVAILABLE"
    assert result.experiment_id is not None
    saved = registry.load_experiment_artifacts(result.experiment_id)
    assert saved["summary.json"]["final_test_viewed"] is False


def test_revealed_final_test_explicitly_marked_exposed() -> None:
    repository = _Repository()
    days = repository.calendar.get_trading_days()
    result = run_validation(
        _strategy(), days[0], days[-1], repository,
        backtest_config=BacktestConfig(initial_capital=1000),
        config=ValidationConfig(reveal_final_test=True), universe=["A"],
    )
    assert result.final_test_viewed
    assert "test" in result.periods
    assert any("Final test was viewed" in warning for warning in result.warnings)


def test_registry_remembers_prior_test_view_after_strategy_changes(tmp_path) -> None:
    repository = _Repository()
    days = repository.calendar.get_trading_days()
    registry = ExperimentRegistry(tmp_path / "registry")
    defaults = dict(backtest_config=BacktestConfig(initial_capital=1000), universe=["A"], registry=registry)
    run_validation(
        _strategy(), days[0], days[-1], repository,
        config=ValidationConfig(reveal_final_test=True), **defaults,
    )
    changed = _strategy()
    changed.version = "1.0.1"
    changed.entry.conditions[0].value = 107.0
    result = run_validation(
        changed, days[0], days[-1], repository,
        config=ValidationConfig(), **defaults,
    )
    assert result.test_previously_exposed
    assert any("previously viewed" in w for w in result.warnings)
    assert "test" not in result.periods
