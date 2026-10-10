"""Signal Engine CLI demo.

Real data::

    python examples/run_signals.py \\
        --strategy strategies/examples/price_threshold_strategy.yaml \\
        --date 2025-01-02

Synthetic (no network, demonstrates BUY/HOLD/SELL/DATA_UNAVAILABLE)::

    python examples/run_signals.py --synthetic --date 2026-09-24
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import pandas as pd

from hk_quant.data.calendar import TradingCalendar
from hk_quant.data.repository import DataRepository
from hk_quant.factors import FactorEngine
from hk_quant.signal import (
    PositionState,
    SignalType,
    generate_signals,
    save_signals,
    signals_to_dataframe,
)
from hk_quant.strategy.config import load_strategy_definition
from hk_quant.strategy.models import (
    Condition,
    ConditionGroup,
    HoldingPeriod,
    StrategyDefinition,
    UniverseSpec,
)
from hk_quant.strategy.validators import validate_strategy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Signal Engine")
    parser.add_argument("--strategy", help="Path to a strategy YAML")
    parser.add_argument("--date", required=True, help="Signal date (YYYY-MM-DD)")
    parser.add_argument("--synthetic", action="store_true", help="Run a synthetic demo")
    args = parser.parse_args(argv)

    if args.synthetic:
        strategy = _synthetic_strategy()
        repository = _SyntheticRepository()
        universe = ["TEST001", "TEST002", "TEST003", "TEST004"]
        state = {
            "TEST004": PositionState(
                stock_id="TEST004",
                entry_date="2026-09-17",
                strategy_id=strategy.strategy_id,
                strategy_version=strategy.version,
            )
        }
    else:
        if not args.strategy:
            parser.error("--strategy is required unless --synthetic")
        strategy = load_strategy_definition(args.strategy)
        validate_strategy(strategy)
        repository = DataRepository("data/processed")
        universe = None
        state = None

    signals = generate_signals(
        strategy,
        args.date,
        universe=universe,
        state=state,
        repository=repository,
        factor_engine=FactorEngine(repository),
    )

    _print_report(strategy, args.date, signals)

    output_dir = f"experiments/signals/{strategy.strategy_id}_{args.date}"
    save_signals(signals, output_dir)
    print(f"\nResults saved to: {output_dir}")
    return 0


def _print_report(strategy, signal_date, signals) -> None:
    print(f"Strategy: {strategy.strategy_id} v{strategy.version}")
    print(f"Signal Date: {signal_date}\n")

    by_type: dict[str, list[str]] = {"BUY": [], "SELL": [], "HOLD": []}
    unavailable: list[str] = []
    for signal in signals:
        if signal.status.value == "DATA_UNAVAILABLE":
            unavailable.append(signal.stock_id)
        elif signal.signal in by_type:
            by_type[signal.signal].append(signal.stock_id)

    for label in ("BUY", "HOLD", "SELL"):
        print(f"{label}:")
        for stock_id in by_type[label]:
            print(f"  {stock_id}")
    if unavailable:
        print("DATA_UNAVAILABLE:")
        for stock_id in unavailable:
            print(f"  {stock_id}")

    # show one reason example
    buys = [s for s in signals if s.signal == SignalType.BUY.value]
    if buys:
        example = buys[0]
        print(f"\nExample reason ({example.stock_id}):")
        print(example.reason)


def _synthetic_strategy() -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id="synthetic_momentum_strategy",
        name="Synthetic Momentum Factor Strategy",
        version="1.0.0",
        universe=UniverseSpec(type="observed_price_universe"),
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="factor", field="momentum_20", operator=">", value=0.05, unit="ratio")
            ],
        ),
        holding_period=HoldingPeriod(type="trading_days", value=5),
        exit=None,
        status="validated",
    )


class _SyntheticRepository:
    """Minimal in-memory repository for the synthetic demo."""

    def __init__(self) -> None:
        end = pd.Timestamp("2026-09-24")
        rows = []
        # TEST001: 30 days rising -> momentum > 5% -> BUY
        # TEST002: 30 days flat -> momentum ~0 -> HOLD
        # TEST003: only 5 days -> momentum unavailable -> DATA_UNAVAILABLE
        # TEST004: 30 days rising + position -> SELL
        for stock_id, days, drift in [
            ("TEST001", 30, 0.01),
            ("TEST002", 30, 0.0),
            ("TEST003", 5, 0.01),
            ("TEST004", 30, 0.01),
        ]:
            dates = pd.bdate_range(end=end, periods=days)
            close = 100.0
            for day in dates:
                close *= 1.0 + drift
                rows.append(
                    {
                        "stock_id": stock_id,
                        "trade_date": day.date(),
                        "open": close,
                        "high": close * 1.01,
                        "low": close * 0.99,
                        "close": close,
                        "volume": 1_000_000.0,
                        "amount": 100_000_000.0,
                        "turnover_rate": float("nan"),
                        "source": "synthetic",
                        "ingested_at": pd.Timestamp.now("UTC"),
                    }
                )
        self.panel = pd.DataFrame(rows)

    def get_daily_prices(self, stock_ids=None, start_date=None, end_date=None) -> pd.DataFrame:
        df = self.panel
        if stock_ids:
            ids = [stock_ids] if isinstance(stock_ids, str) else list(stock_ids)
            df = df[df["stock_id"].isin(ids)]
        if start_date:
            df = df[pd.to_datetime(df["trade_date"]) >= pd.Timestamp(start_date)]
        if end_date:
            df = df[pd.to_datetime(df["trade_date"]) <= pd.Timestamp(end_date)]
        return df.reset_index(drop=True)

    def get_prices(self, stock_ids=None, start_date=None, end_date=None, *, adjusted=False):
        return self.get_daily_prices(stock_ids, start_date, end_date)

    def get_calendar(self) -> TradingCalendar:
        return TradingCalendar.from_prices(self.panel)


if __name__ == "__main__":
    sys.exit(main())
