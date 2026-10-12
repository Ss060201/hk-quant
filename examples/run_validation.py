"""Synthetic-only fixed-strategy OOS demo, with the final test withheld.

Run ``PYTHONPATH=src python examples/run_validation.py`` after installing the
project dependencies. The repository and prices are synthetic. This example
never contacts a real data source or broker and makes no investment claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hk_quant.backtest import BacktestConfig
from hk_quant.data.calendar import TradingCalendar
from hk_quant.experiments import ExperimentRegistry
from hk_quant.strategy.models import (
    Condition, ConditionGroup, HoldingPeriod, StrategyDefinition, UniverseSpec,
)
from hk_quant.validation import ValidationConfig, run_validation


class SyntheticRepository:
    def __init__(self) -> None:
        dates = pd.bdate_range("2026-01-02", periods=45)
        self._calendar = TradingCalendar(dates)
        self._panel = pd.DataFrame([
            {
                "stock_id": "SYNTHETIC_A", "trade_date": day.date().isoformat(),
                "open": 100 + i, "high": 101 + i,
                "low": 99 + i, "close": 100 + i,
                "volume": 10_000, "amount": 1_000_000.0,
            }
            for i, day in enumerate(dates)
        ])

    def get_calendar(self) -> TradingCalendar:
        return self._calendar

    def get_data_version(self) -> str:
        return "synthetic-v1-not-real-market"

    def get_daily_prices(self, stock_ids=None, start_date=None, end_date=None) -> pd.DataFrame:
        panel = self._panel
        if stock_ids:
            panel = panel[panel["stock_id"].isin(stock_ids)]
        if start_date:
            panel = panel[panel["trade_date"] >= str(start_date)]
        if end_date:
            panel = panel[panel["trade_date"] <= str(end_date)]
        return panel.reset_index(drop=True).copy()

    def get_prices(self, stock_ids=None, start_date=None, end_date=None, *, adjusted=False):
        return self.get_daily_prices(stock_ids, start_date, end_date)


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic-only strategy validation")
    parser.add_argument(
        "--registry-root", type=Path, default=Path("experiments/validation_synthetic"),
        help="local directory for an immutable experiment record",
    )
    args = parser.parse_args()
    repository = SyntheticRepository()
    strategy = StrategyDefinition(
        strategy_id="synthetic_close_threshold", name="Synthetic fixed threshold",
        version="1.0.0", universe=UniverseSpec(),
        entry=ConditionGroup(logic="all", conditions=[
            Condition(source="data", field="close", operator=">", value=106.0),
        ]),
        holding_period=HoldingPeriod(value=100),
    )
    dates = repository.get_calendar().get_trading_days()
    result = run_validation(
        strategy, dates[0], dates[-1], repository,
        backtest_config=BacktestConfig(initial_capital=10_000),
        config=ValidationConfig(
            label_horizon_days=1, walk_min_train_days=10, walk_evaluation_days=5,
        ),
        universe=["SYNTHETIC_A"],
        registry=ExperimentRegistry(args.registry_root),
    )
    print("SYNTHETIC ONLY; final test returns withheld")
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
