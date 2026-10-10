"""Research visualization (matplotlib, headless Agg backend)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

import matplotlib

matplotlib.use("Agg")  # headless

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

PathLike = Union[str, os.PathLike[str]]


def _thresholds_as_percent(stats: pd.DataFrame) -> list[float]:
    return [round(float(t) * 100, 1) for t in stats["threshold"].unique()]


def plot_heatmap(
    stats: pd.DataFrame,
    output_path: PathLike,
    *,
    value_column: str = "mean",
) -> Path:
    """Plot a threshold x holding-period heatmap of ``value_column``."""
    pivot = stats.pivot(index="threshold", columns="forward_period", values=value_column)
    pivot = pivot.sort_index()

    fig, ax = plt.subplots(figsize=(12, max(4, len(pivot) * 0.6)))
    im = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="RdYlGn")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([str(c) for c in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{t * 100:.0f}%" for t in pivot.index])
    ax.set_xlabel("Holding period (trading days)")
    ax.set_ylabel("Threshold")
    ax.set_title(f"{value_column} forward return by threshold x holding period")
    fig.colorbar(im, ax=ax, label=value_column)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_threshold_vs_return(
    stats: pd.DataFrame,
    holding_period: int,
    output_path: PathLike,
) -> Path:
    """Plot mean return vs threshold for one holding period."""
    sub = stats[stats["forward_period"] == holding_period].sort_values("threshold")
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(_thresholds_as_percent(sub), sub["mean"], marker="o", label="mean")
    ax.plot(_thresholds_as_percent(sub), sub["median"], marker="s", label="median")
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_xlabel("Threshold (%)")
    ax.set_ylabel("Forward return")
    ax.set_title(f"Threshold vs return ({holding_period} trading days)")
    ax.legend()

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_holding_period_vs_return(
    stats: pd.DataFrame,
    threshold: float,
    output_path: PathLike,
) -> Path:
    """Plot mean return vs holding period for one threshold."""
    sub = stats[stats["threshold"] == threshold].sort_values("forward_period")
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(sub["forward_period"], sub["mean"], marker="o", label="mean")
    ax.plot(sub["forward_period"], sub["median"], marker="s", label="median")
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_xlabel("Holding period (trading days)")
    ax.set_ylabel("Forward return")
    ax.set_title(f"Holding period vs return (threshold {threshold * 100:.0f}%)")
    ax.legend()

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_sample_sizes(stats: pd.DataFrame, output_path: PathLike) -> Path:
    """Plot valid sample count by threshold for the first holding period."""
    sub = stats.sort_values(["threshold", "forward_period"])
    fig, ax = plt.subplots(figsize=(8, 5))
    for period, group in sub.groupby("forward_period"):
        ax.plot(
            _thresholds_as_percent(group),
            group["valid_sample_count"],
            marker="o",
            label=f"{period}D",
        )
    ax.set_xlabel("Threshold (%)")
    ax.set_ylabel("Valid sample count")
    ax.set_title("Sample size by threshold")
    ax.legend(title="Holding period")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path
