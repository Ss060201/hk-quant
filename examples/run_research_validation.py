"""Validate one fixed rule and an explicit local cohort; withhold final test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from hk_quant.backtest import BacktestConfig
from hk_quant.data.normalization import normalize_stock_id
from hk_quant.data.readiness import assess_price_panel
from hk_quant.data.repository import DataRepository
from hk_quant.experiments import ExperimentRegistry
from hk_quant.strategy.config import load_strategy_definition
from hk_quant.validation import ValidationConfig, run_validation


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exploratory cost-aware validation with final test withheld")
    parser.add_argument("--strategy", type=Path, required=True)
    parser.add_argument("--stocks", nargs="+", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--min-sessions", type=int, default=252)
    parser.add_argument("--min-coverage", type=float, default=0.8)
    parser.add_argument("--allow-unmodeled-actions", action="store_true",
                        help="Run a price-only exploratory simulation despite unmodeled distributions")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/backtest/price_demo.yaml")
    args = parser.parse_args(argv)
    stocks = [normalize_stock_id(stock) for stock in args.stocks]
    repo = DataRepository(ROOT / "data" / "processed")
    panel = repo.get_daily_prices(stock_ids=stocks, start_date=args.start, end_date=args.end)
    coverage = assess_price_panel(panel, stocks, args.start, args.end,
                                  min_sessions=args.min_sessions, min_coverage=args.min_coverage)
    if coverage["status"] == "BLOCKED":
        parser.error("data coverage is insufficient: " + json.dumps(coverage, ensure_ascii=False))

    actions = repo.get_corporate_actions(stock_ids=stocks)
    if not actions.empty:
        import pandas as pd
        relevant = pd.to_datetime(actions["event_date"]).between(
            pd.Timestamp(args.start), pd.Timestamp(args.end)
        )
        if relevant.any() and not args.allow_unmodeled_actions:
            parser.error("corporate action cash/share flows are unmodeled; use --allow-unmodeled-actions for an exploratory price-only result")

    with args.config.open(encoding="utf-8") as stream:
        costs = BacktestConfig(**yaml.safe_load(stream))
    strategy = load_strategy_definition(args.strategy)
    result = run_validation(
        strategy, args.start, args.end, repo, universe=stocks,
        backtest_config=costs,
        config=ValidationConfig(reveal_final_test=False),
        registry=ExperimentRegistry(ROOT / "experiments" / "validation_real"),
    )
    print(json.dumps({
        "status": "EXPLORATORY", "experiment_id": result.experiment_id,
        "data_version": result.data_version, "split": result.split.to_dict(),
        "periods": result.periods, "warnings": result.warnings,
        "final_test_viewed": result.final_test_viewed,
        "unmodeled_actions_in_sample": bool(not actions.empty and relevant.any()),
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
