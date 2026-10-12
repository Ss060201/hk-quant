"""Save the full simulation ledger to a fresh artifact directory."""

from __future__ import annotations

import json
from pathlib import Path

from hk_quant.backtest.models import BacktestResult


def save_backtest(result: BacktestResult, output_dir: str | Path) -> Path:
    """Persist a backtest without silently replacing an earlier run."""
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"backtest artifact directory must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(
        json.dumps(result.config.to_dict(), indent=2), encoding="utf-8",
    )
    (root / "summary.json").write_text(
        json.dumps({
            "metrics": result.metrics,
            "metadata": result.metadata,
            "warnings": result.warnings,
            "order_status_counts": result.orders["status"].value_counts().to_dict(),
        }, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    for name, frame in (
        ("daily_portfolio", result.daily), ("trades", result.trades),
        ("positions", result.positions), ("orders", result.orders),
        ("signals", result.signals),
    ):
        frame.to_parquet(root / f"{name}.parquet", index=False)

    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(result.daily["trade_date"], result.daily["equity"])
    ax.set(xlabel="Trading day", ylabel="Portfolio equity", title="Backtest equity")
    ax.tick_params(axis="x", labelrotation=45)
    fig.tight_layout()
    fig.savefig(root / "equity.png", dpi=150)
    plt.close(fig)
    result.artifact_dir = str(root)
    return root
