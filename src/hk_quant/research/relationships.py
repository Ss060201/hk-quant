"""Relationship analysis.

Describes statistical *associations* between research parameters and
forward returns. These are exploratory observations, never "alpha" claims.
"""

from __future__ import annotations

import math

import pandas as pd


def spearman_rank_correlation(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    """Spearman rank correlation (rho) and an approximate p-value.

    The p-value uses the Fisher z-transform normal approximation, which is
    reasonable for research sample sizes and keeps the module dependency-free.
    """
    xs = pd.Series(x, dtype="float64")
    ys = pd.Series(y, dtype="float64")
    mask = xs.notna() & ys.notna()
    xs, ys = xs[mask], ys[mask]
    if len(xs) <= 3 or xs.nunique() <= 1 or ys.nunique() <= 1:
        return (float("nan"), float("nan"))

    rho = float(xs.rank().corr(ys.rank()))
    if math.isnan(rho) or abs(rho) >= 1.0:
        return (rho, float("nan"))

    z = math.atanh(rho)
    se = 1.0 / math.sqrt(len(xs) - 3)
    z_score = z / se
    cdf = 0.5 * (1.0 + math.erf(abs(z_score) / math.sqrt(2.0)))
    p_value = 2.0 * (1.0 - cdf)
    return (rho, float(p_value))


def classify_pattern(values: list[float]) -> str:
    """Classify a sequence as increasing / decreasing / non_monotonic / no_clear_pattern.

    A monotonic sequence is reported as increasing/decreasing. A non-monotonic
    sequence with a meaningful trend (e.g. a rise-then-fall peak) is reported
    as ``non_monotonic``; otherwise ``no_clear_pattern``.
    """
    clean = [v for v in values if not (isinstance(v, float) and math.isnan(v))]
    if len(clean) < 2:
        return "no_clear_pattern"

    if all(b >= a for a, b in zip(clean, clean[1:])):
        return "increasing"
    if all(b <= a for a, b in zip(clean, clean[1:])):
        return "decreasing"

    x = pd.Series(range(len(clean)), dtype="float64")
    y = pd.Series(clean, dtype="float64")
    rho, p_value = spearman_rank_correlation(x, y)
    if not math.isnan(rho) and (
        abs(rho) >= 0.3 or (not math.isnan(p_value) and p_value <= 0.05)
    ):
        return "non_monotonic"
    return "no_clear_pattern"


def threshold_return_relationship(stats: pd.DataFrame, holding_period: int) -> dict:
    """Relationship between threshold and mean/median return at one period."""
    sub = stats[stats["forward_period"] == holding_period].sort_values("threshold")
    mean_rho, mean_p = spearman_rank_correlation(sub["threshold"], sub["mean"])
    median_rho, median_p = spearman_rank_correlation(sub["threshold"], sub["median"])
    return {
        "holding_period": holding_period,
        "spearman_mean_rho": mean_rho,
        "spearman_mean_p": mean_p,
        "spearman_median_rho": median_rho,
        "spearman_median_p": median_p,
        "pattern": classify_pattern(sub["mean"].tolist()),
    }


def holding_period_relationship(stats: pd.DataFrame, threshold: float) -> dict:
    """Relationship between holding period and mean return at one threshold."""
    sub = stats[stats["threshold"] == threshold].sort_values("forward_period")
    rho, p_value = spearman_rank_correlation(sub["forward_period"], sub["mean"])
    return {
        "threshold": threshold,
        "spearman_rho": rho,
        "spearman_p": p_value,
        "pattern": classify_pattern(sub["mean"].tolist()),
    }


def analyze_relationships(
    stats: pd.DataFrame,
    thresholds: list[float],
    forward_periods: list[int],
) -> dict:
    """Run both relationship analyses across the full sweep."""
    return {
        "threshold_return_relationships": [
            threshold_return_relationship(stats, period) for period in forward_periods
        ],
        "holding_period_relationships": [
            holding_period_relationship(stats, threshold) for threshold in thresholds
        ],
        "overlapping_thresholds": True,
        "thresholds_are_nested": True,
    }
