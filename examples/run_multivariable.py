"""Synthetic-only Phase 11 demo; these numbers are not Hong Kong stock evidence.

Run with ``PYTHONPATH=src python examples/run_multivariable.py``.
Requires configured project dependencies; no external data or credentials.
"""

from __future__ import annotations

import pandas as pd

from hk_quant.research.multivariable import MultivariableConfig, run_multivariable_research


def main() -> None:
    days = pd.bdate_range("2022-01-03", periods=100)
    rows = []
    for i, day in enumerate(days[:-5]):
        for stock_id in ("A", "B"):
            rows.append({
                "stock_id": stock_id, "event_date": day,
                "exit_date": days[i + 5], "forward_period": 5,
                "momentum_20": (i % 9) / 10,
                "volatility_20": (i % 4) / 20 + 0.05,
                "forward_return": ((i % 6) - 2) / 100
                                  + (0.002 if stock_id == "A" else -0.002),
            })
    panel = pd.DataFrame(rows)
    config = MultivariableConfig(
        thresholds={"momentum_20": (0.2, 0.4, 0.6), "volatility_20": (0.05, 0.1)},
        forward_periods=(5,),
        available_fields=frozenset({"momentum_20", "volatility_20"}),
        min_samples=10, min_dates=8,
        discovery_end="2022-03-31", confirmation_start="2022-04-01",
    )
    result = run_multivariable_research(panel, config)
    print("SYNTHETIC ONLY; exploratory hypotheses, not trading recommendations")
    print(result.grid.to_string(index=False))
    print(result.summary())


if __name__ == "__main__":
    main()
