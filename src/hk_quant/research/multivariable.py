"""Bounded, exploratory multivariable research on a precomputed outcome panel.

The caller supplies event-date features and independently calculated future
returns. This module never turns an observed grid optimum into a strategy.
It cannot synthesize unavailable turnover_rate from amount or infer point-in-
time availability of any feature; the caller must certify it in ``available``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import product
from math import isfinite, prod
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class ResearchFieldUnavailableError(ValueError):
    """A requested feature or forward outcome lacks a verified provider."""


@dataclass(frozen=True)
class MultivariableConfig:
    thresholds: Mapping[str, Sequence[float]]
    forward_periods: tuple[int, ...]
    available_fields: frozenset[str]
    min_samples: int = 20
    min_dates: int = 8
    max_combinations: int = 100
    bootstrap_reps: int = 400
    block_length_days: int = 5
    seed: int = 42
    subgroup_field: str | None = None
    discovery_end: str | None = None
    confirmation_start: str | None = None


@dataclass
class MultivariableResult:
    grid: pd.DataFrame
    subgroups: pd.DataFrame
    boundary_candidates: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    planned_combinations: int = 0
    calculated_combinations: int = 0
    status: str = "EXPLORATORY"

    def summary(self) -> dict:
        return {
            "planned_combinations": self.planned_combinations,
            "calculated_combinations": self.calculated_combinations,
            "boundary_candidates": self.boundary_candidates,
            "warnings": self.warnings,
            "status": self.status,
        }


def estimate_grid_size(config: MultivariableConfig) -> int:
    """Predict exact number of planned threshold / horizon hypotheses."""
    if not config.thresholds or not config.forward_periods:
        raise ValueError("at least one condition and one forward period required")
    for name, values in config.thresholds.items():
        if not name or not values or any(not isfinite(float(v)) for v in values):
            raise ValueError("every variable needs finite, explicit thresholds")
        if len(set(values)) != len(values):
            raise ValueError(f"duplicate thresholds for {name}")
    if len(set(config.forward_periods)) != len(config.forward_periods) or any(
        p <= 0 for p in config.forward_periods
    ):
        raise ValueError("forward periods must be unique positive integers")
    count = prod(len(v) for v in config.thresholds.values()) * len(config.forward_periods)
    if config.max_combinations < 1 or count > config.max_combinations:
        raise ValueError(f"planned grid has {count} combinations, max is {config.max_combinations}")
    if config.min_samples < 2 or config.min_dates < 2 or config.bootstrap_reps < 50:
        raise ValueError("minimum sample/date counts >=2 and bootstrap_reps >=50 required")
    if config.block_length_days < 1:
        raise ValueError("block_length_days must be positive")
    return count


def _moving_block_stats(
    frame: pd.DataFrame, *, reps: int, block_length: int, seed: int,
) -> tuple[float | None, float | None, float | None]:
    """Bootstrap contiguous date blocks, retaining each date's stock cluster.

    A fixed block length is an approximation; long-horizon overlapping labels
    may remain dependent across blocks. Report this limitation to callers.
    """
    dates = sorted(frame["event_date"].dropna().unique())
    if len(dates) < max(3, block_length):
        return (None, None, None)
    by_date = [frame.loc[frame["event_date"] == day, "forward_return"].to_numpy(dtype=float)
               for day in dates]
    mean = float(frame["forward_return"].mean())
    rng = np.random.default_rng(seed)
    boot = np.empty(reps, dtype=float)
    blocks_needed = (len(dates) + block_length - 1) // block_length
    # Resampling circular contiguous blocks avoids changing the size of the
    # eligible starting-index population near the edges of the date interval.
    for i in range(reps):
        starts = rng.integers(0, len(dates), size=blocks_needed)
        indices = [(start + j) % len(dates)
                   for start in starts for j in range(block_length)][:len(dates)]
        count, total = 0, 0.0
        for ix in indices:
            values = by_date[ix]
            count += len(values)
            total += float(values.sum())
        boot[i] = total / count
    lower, upper = np.quantile(boot, [0.025, 0.975])
    # Centered block-bootstrap null around zero; exploratory approximation.
    p_value = (1 + int(np.count_nonzero(np.abs(boot - mean) >= abs(mean)))) / (reps + 1)
    return float(lower), float(upper), float(p_value)


def benjamini_hochberg(p_values: Sequence[float | None], hypotheses: int) -> list[float | None]:
    """BH adjusted p values with every planned grid cell counted in m.

    BH's usual FDR guarantee assumes independent or suitably positively
    dependent hypotheses; nested thresholds and overlapping returns need not
    meet that condition. Treat these q values as exploratory diagnostics.
    """
    if hypotheses < len(p_values):
        raise ValueError("planned hypotheses cannot be fewer than p values")
    valid = [(i, float(p)) for i, p in enumerate(p_values)
             if p is not None and np.isfinite(p) and 0 <= p <= 1]
    ranked = sorted(valid, key=lambda pair: pair[1])
    out: list[float | None] = [None] * len(p_values)
    smallest = 1.0
    for rank in range(len(ranked), 0, -1):
        index, value = ranked[rank - 1]
        smallest = min(smallest, value * hypotheses / rank)
        out[index] = float(smallest)
    return out


def _descriptive(frame: pd.DataFrame, config: MultivariableConfig, seed: int) -> dict:
    valid_frame = frame[frame["forward_return"].notna()]
    valid = valid_frame["forward_return"].astype(float)
    dates = int(valid_frame["event_date"].nunique())
    sufficient = len(valid) >= config.min_samples and dates >= config.min_dates
    lo, hi, p = _moving_block_stats(
        valid_frame, reps=config.bootstrap_reps,
        block_length=config.block_length_days, seed=seed,
    ) if sufficient else (None, None, None)
    return {
        "sample_count": int(len(frame)), "valid_sample_count": int(len(valid)),
        "distinct_dates": dates,
        "mean": float(valid.mean()) if len(valid) else None,
        "median": float(valid.median()) if len(valid) else None,
        "win_rate": float((valid > 0).mean()) if len(valid) else None,
        "ci_lower": lo, "ci_upper": hi, "p_exploratory": p,
        "status": "EXPLORATORY" if sufficient else "INSUFFICIENT_SAMPLE",
    }


def _boundary_candidates(grid: pd.DataFrame, names: list[str]) -> list[dict]:
    candidates: list[dict] = []
    # Changing several thresholds together cannot isolate the relationship
    # with a single field. Hold all other explicit thresholds constant.
    for period, period_rows in grid.groupby("forward_period", sort=True):
        for field in names:
            others = [name for name in names if name != field]
            groups = (period_rows.groupby([f"threshold_{name}" for name in others], dropna=False, sort=True)
                      if others else [((), period_rows)])
            for fixed, group in groups:
                ordered = group.sort_values(f"threshold_{field}")
                eligible = ordered[(ordered["status"] == "EXPLORATORY") & ordered["mean"].notna()]
                if len(eligible) < 3:
                    continue
                means = eligible["mean"].astype(float).tolist()
                diff = np.diff(means)
                trend = ("increasing" if np.all(diff >= 0) else
                         "decreasing" if np.all(diff <= 0) else
                         "sign_reversal" if min(means) < 0 < max(means) else "mixed")
                candidates.append({
                    "field": field, "forward_period": int(period),
                    "other_thresholds": dict(zip(others, fixed if isinstance(fixed, tuple) else (fixed,))),
                    "thresholds": eligible[f"threshold_{field}"].tolist(),
                    "means": means, "pattern": trend, "status": "EXPLORATORY_CANDIDATE",
                })
    return candidates


def run_multivariable_research(
    panel: pd.DataFrame, config: MultivariableConfig,
) -> MultivariableResult:
    """Run every predeclared hypothesis and optional held-out date comparison.

    Required panel: stock_id, event_date, exit_date, forward_period,
    forward_return and verified as-of feature columns. No real-data source is
    implied by a synthetic panel. Confirmation is withheld unless explicitly
    given nonoverlapping discovery_end and confirmation_start dates.
    """
    planned = estimate_grid_size(config)
    names = list(config.thresholds)
    requested = set(names) | ({config.subgroup_field} if config.subgroup_field else set())
    unavailable = requested - set(config.available_fields)
    if unavailable:
        raise ResearchFieldUnavailableError(
            f"unavailable as-of fields {sorted(unavailable)}; amount cannot replace turnover_rate"
        )
    required = requested | {"stock_id", "event_date", "exit_date", "forward_period", "forward_return"}
    missing = required - set(panel)
    if missing:
        raise ResearchFieldUnavailableError(
            f"missing panel fields {sorted(missing)}; no substitution or imputation"
        )
    if (config.discovery_end is None) != (config.confirmation_start is None):
        raise ValueError("supply both independent discovery and confirmation boundaries")
    if config.discovery_end is not None and pd.Timestamp(config.discovery_end) >= pd.Timestamp(config.confirmation_start):
        raise ValueError("discovery must end before confirmation starts")

    frame = panel.copy()
    frame["event_date"] = pd.to_datetime(frame["event_date"], errors="raise")
    frame["exit_date"] = pd.to_datetime(frame["exit_date"], errors="raise")
    if frame["event_date"].isna().any() or frame["exit_date"].isna().any():
        raise ValueError("null event/exit date; cannot verify label leakage")
    if (frame["exit_date"] <= frame["event_date"]).any():
        raise ValueError("future outcome must end after event date")
    if frame.duplicated(["stock_id", "event_date", "forward_period"]).any():
        raise ValueError("duplicate stock/date/forward_period outcome")
    for name in names:
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    frame["forward_return"] = pd.to_numeric(frame["forward_return"], errors="coerce")
    if "valid_sample" in frame:
        frame.loc[~frame["valid_sample"].fillna(False).astype(bool), "forward_return"] = np.nan
    if config.discovery_end is not None:
        discovery = frame[(frame["event_date"] <= pd.Timestamp(config.discovery_end))
                          & (frame["exit_date"] < pd.Timestamp(config.confirmation_start))]
        confirmation = frame[frame["event_date"] >= pd.Timestamp(config.confirmation_start)]
    else:
        discovery, confirmation = frame, None

    rows: list[dict] = []
    subgroup_rows: list[dict] = []
    combinations = list(product(*(config.thresholds[name] for name in names)))
    for period in config.forward_periods:
        for values in combinations:
            selectors = dict(zip(names, values))
            def selected(source: pd.DataFrame) -> pd.DataFrame:
                mask = source["forward_period"] == period
                for name, threshold in selectors.items():
                    mask &= source[name] > threshold
                return source.loc[mask]

            sample = selected(discovery)
            stats = _descriptive(sample, config, config.seed)
            row = {"forward_period": period,
                   **{f"threshold_{key}": float(value) for key, value in selectors.items()},
                   **stats}
            if confirmation is not None:
                held = selected(confirmation)
                held_stats = _descriptive(held, config, config.seed + 1)
                row.update({f"confirmation_{key}": value for key, value in held_stats.items()})
            rows.append(row)
            if config.subgroup_field:
                for group, grouped in sample.groupby(config.subgroup_field, dropna=False):
                    subgroup_rows.append({
                        "forward_period": period,
                        **{f"threshold_{key}": float(value) for key, value in selectors.items()},
                        "subgroup_field": config.subgroup_field, "subgroup": str(group),
                        **_descriptive(grouped, config, config.seed),
                    })
    grid = pd.DataFrame(rows)
    grid["q_bh_exploratory"] = benjamini_hochberg(grid["p_exploratory"].tolist(), planned)
    warnings = [
        "EXPLORATORY only; all planned threshold × period combinations are reported.",
        "BH FDR assumptions may fail for nested thresholds and overlapping forward returns.",
        "Moving date-block bootstrap preserves nearby dates and same-date stock clusters approximately; dependence can extend beyond the selected block length.",
        "Feature point-in-time availability and adjustment provenance must be verified upstream.",
    ]
    if confirmation is None:
        warnings.append("No independent confirmation interval supplied; no boundary is validated.")
    else:
        warnings.append("Discovery labels crossing the confirmation boundary were purged.")
    if "turnover_rate" in requested:
        warnings.append("Real turnover_rate requires a verified provider; never use amount as a proxy.")
    return MultivariableResult(
        grid=grid, subgroups=pd.DataFrame(subgroup_rows),
        boundary_candidates=_boundary_candidates(grid, names),
        warnings=warnings, planned_combinations=planned,
        calculated_combinations=len(grid),
    )
