"""Research Engine CLI demo.

Run a research definition from a YAML config::

    python examples/run_research.py --config configs/research/turnover_forward_return.yaml

Or run a fully synthetic (no network) research to see the pipeline::

    python examples/run_research.py --synthetic
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from hk_quant.data.repository import DataRepository
from hk_quant.research import (
    ResearchDataError,
    load_research_definition,
    run_research,
)
from hk_quant.research.models import ResearchDefinition, VariableSpec


def _synthetic_panel() -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=40)
    rows = []
    price = 100.0
    for i, day in enumerate(dates):
        turnover_rate = 0.04 + (i % 20) * 0.05  # oscillates between 4% and 99%
        price *= 1.0 + turnover_rate * 0.002  # higher turnover -> higher return
        rows.append(
            {
                "stock_id": "TEST001",
                "trade_date": day.date(),
                "open": price,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": 1_000_000.0,
                "amount": 100_000_000.0,
                "turnover_rate": turnover_rate,
                "source": "synthetic",
                "ingested_at": pd.Timestamp.now("UTC"),
            }
        )
    return pd.DataFrame(rows)


def _synthetic_definition() -> ResearchDefinition:
    return ResearchDefinition(
        name="turnover_forward_return_v1_synthetic",
        variable=VariableSpec(
            name="turnover_rate",
            thresholds=[0.10, 0.30, 0.50, 0.70, 0.90],
            unit="ratio",
        ),
        forward_periods=[1, 2, 3, 5, 10, 20],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a research definition")
    parser.add_argument("--config", help="Path to a research YAML config")
    parser.add_argument("--synthetic", action="store_true", help="Run a synthetic demo")
    args = parser.parse_args(argv)

    if args.synthetic:
        definition = _synthetic_definition()
        result = run_research(
            definition,
            panel=_synthetic_panel(),
            output_dir="experiments/research/turnover_forward_return_v1_synthetic",
        )
        _print_result(result)
        return 0

    if not args.config:
        parser.error("provide --config or --synthetic")

    definition = load_research_definition(args.config)
    repository = DataRepository("data/processed")

    try:
        result = run_research(
            definition,
            repository=repository,
            output_dir=f"experiments/research/{definition.name}",
        )
    except ResearchDataError as exc:
        print(f"Research data error: {exc}", file=sys.stderr)
        print(
            "\nRequired variable `turnover_rate` is unavailable or semantically "
            "incompatible with current data.\n"
            "The current provider supplies trading amount (成交額), not turnover "
            "rate (換手率).\nRun `python examples/run_research.py --synthetic` to "
            "see the full pipeline on synthetic data."
        )
        return 1

    _print_result(result)
    return 0


def _print_result(result) -> None:
    print(f"\nResearch: {result.name}")
    print(f"Status: {result.status.value}")
    print(f"Thresholds: {len(result.statistics['threshold'].unique())}")
    print(f"Forward periods: {len(result.statistics['forward_period'].unique())}")
    print(f"Events: {len(result.events)}")
    print(f"Tested combinations: {result.tested_combinations}")
    print(f"Warnings: {len(result.warnings)}")
    for warning in result.warnings:
        print(f"  - {warning}")
    print("\nMean forward return matrix (threshold x period):")
    pivot = result.statistics.pivot(
        index="threshold", columns="forward_period", values="mean"
    )
    pivot.index = [f"{t * 100:.0f}%" for t in pivot.index]
    print(pivot.round(4).to_string())
    print(f"\nResults saved to: experiments/research/{result.name}")


if __name__ == "__main__":
    sys.exit(main())
