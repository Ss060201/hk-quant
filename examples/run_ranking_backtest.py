"""Ranking backtest CLI (in-memory, fast).

Example::

    python examples/run_ranking_backtest.py \
        --stocks 0700 0005 0941 --start 2020-01-01 --end 2025-12-31 \
        --top-n 2 --rebalance 20

Result is EXPLORATORY; the example momentum factor is not a validated strategy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hk_quant.backtest.models import BacktestConfig
from hk_quant.backtest.ranking import run_ranking_backtest
from hk_quant.data.repository import DataRepository
from hk_quant.selection import momentum_scorer

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="In-memory ranking backtest")
    parser.add_argument("--stocks", nargs="+", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--rebalance", type=int, default=20, help="trading days between rebalances")
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--commission", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.001)
    args = parser.parse_args(argv)

    repository = DataRepository(ROOT / "data" / "processed")
    config = BacktestConfig(
        initial_capital=args.capital,
        commission_rate=args.commission,
        slippage_rate=args.slippage,
    )
    result = run_ranking_backtest(
        repository, args.stocks, args.start, args.end,
        scorer=momentum_scorer(20), top_n=args.top_n,
        rebalance_frequency=args.rebalance, config=config,
    )
    print(f"status: {result.metadata['status']}")
    print(f"data_version: {result.metadata['data_version']}")
    print(f"metrics: {result.metrics}")
    print(f"trades: {len(result.trades)} | dividends: {len(result.dividends)}")
    print(f"rebalance days: {result.decisions['rebalance_date'].nunique()}")
    print("warnings:")
    for warning in result.warnings:
        print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
