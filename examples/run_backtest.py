"""Run a local synthetic backtest, or reuse already ingested real prices.

    python examples/run_backtest.py
    python examples/run_backtest.py --real --start 2025-01-02 --end 2025-02-28

The real mode only exercises the existing data pipeline. It does not establish
that the price-threshold example is an effective investment strategy.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
import yaml

from hk_quant.backtest import BacktestConfig, run_backtest
from hk_quant.data.calendar import TradingCalendar
from hk_quant.strategy.config import load_strategy_definition


ROOT = Path(__file__).resolve().parents[1]


class _SyntheticRepository:
    """Minimal deterministic in-memory repository, with no network access."""

    def __init__(self) -> None:
        days = pd.bdate_range("2026-01-05", periods=6)
        self.calendar = TradingCalendar(days)
        self.prices = pd.DataFrame([
            {
                "stock_id": stock, "trade_date": day.date(),
                "open": close, "high": close, "low": close, "close": close,
                "volume": 10_000, "amount": 1_000_000,
                "turnover_rate": float("nan"), "source": "synthetic",
                "ingested_at": pd.Timestamp("2026-01-13", tz="UTC"),
            }
            for day in days for stock, close in (("DEMO_A", 500.0), ("DEMO_B", 250.0))
        ])

    def get_calendar(self):
        return self.calendar

    def get_daily_prices(self, stock_ids=None, start_date=None, end_date=None):
        result = self.prices
        if stock_ids:
            result = result[result.stock_id.isin(stock_ids)]
        if start_date:
            result = result[pd.to_datetime(result.trade_date) >= pd.Timestamp(start_date)]
        if end_date:
            result = result[pd.to_datetime(result.trade_date) <= pd.Timestamp(end_date)]
        return result.copy()

    def get_prices(self, stock_ids=None, start_date=None, end_date=None, *, adjusted=False):
        return self.get_daily_prices(stock_ids, start_date, end_date)

    def get_data_version(self):
        return "SYNTHETIC_DEMO_V1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a fixed-strategy exploratory backtest")
    parser.add_argument("--real", action="store_true", help="Use existing data/processed; requires --start and --end")
    parser.add_argument("--start", help="Start date for real-data mode, inclusive")
    parser.add_argument("--end", help="End date for real-data mode, inclusive")
    parser.add_argument("--strategy", type=Path, default=ROOT / "strategies/examples/price_threshold_strategy.yaml")
    parser.add_argument("--stock-id", action="append", help="Real-data stock ID (repeatable; default 0700)")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/backtest/price_demo.yaml")
    parser.add_argument("--output", type=Path, help="Unique, empty directory for output artifacts")
    args = parser.parse_args(argv)

    with args.config.open(encoding="utf-8") as stream:
        config = BacktestConfig(**yaml.safe_load(stream))
    strategy = load_strategy_definition(args.strategy)
    if args.real:
        if not args.start or not args.end:
            parser.error("--real requires both --start and --end")
        from hk_quant.data.repository import DataRepository
        repository = DataRepository(ROOT / "data/processed")
        universe = args.stock_id or ["0700"]
        if repository.get_daily_prices(stock_ids=universe, start_date=args.start, end_date=args.end).empty:
            parser.error(f"no locally ingested prices for {universe} in that date range")
        start, end = args.start, args.end
    else:
        repository = _SyntheticRepository()
        start, end = "2026-01-05", "2026-01-12"
        universe = ["DEMO_A", "DEMO_B"]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    output = args.output or ROOT / "experiments/backtests" / run_id
    result = run_backtest(strategy, start, end, repository, config, universe=universe, output_dir=output)
    print(f"Status: {result.metadata['status']}")
    print(f"Total return: {result.metrics['total_return']:.4%}")
    print(f"Trades: {len(result.trades)}; rejected orders: {(result.orders.status == 'REJECTED').sum()}")
    print(f"Artifacts: {output}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
