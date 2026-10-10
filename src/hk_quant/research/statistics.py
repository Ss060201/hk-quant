"""Research statistics.

Every statistic is reported alongside its sample size. Confidence intervals
use a bootstrap; when the sample is too small they are explicitly marked
unavailable rather than fabricated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hk_quant.research.models import ResearchDefinition

_MIN_BOOTSTRAP_SAMPLES = 20
_BOOTSTRAP_REPS = 1000
_BOOTSTRAP_SEED = 42

STATISTICS_COLUMNS: tuple[str, ...] = (
    "threshold",
    "forward_period",
    "sample_count",
    "valid_sample_count",
    "mean",
    "median",
    "std",
    "win_rate",
    "q25",
    "q75",
    "min",
    "max",
    "ci_lower",
    "ci_upper",
)


def bootstrap_mean_ci(
    values: pd.Series,
    *,
    min_samples: int = _MIN_BOOTSTRAP_SAMPLES,
    reps: int = _BOOTSTRAP_REPS,
    seed: int = _BOOTSTRAP_SEED,
    ci: float = 0.95,
) -> tuple[float, float]:
    """Bootstrap confidence interval for the mean.

    Returns ``(NaN, NaN)`` when the sample is too small — never a fake CI.
    """
    clean = pd.Series(values, dtype="float64").dropna()
    if len(clean) < min_samples or clean.nunique() <= 1:
        return (float("nan"), float("nan"))

    rng = np.random.default_rng(seed)
    means = np.empty(reps, dtype="float64")
    arr = clean.to_numpy(dtype="float64")
    for i in range(reps):
        means[i] = rng.choice(arr, size=len(arr), replace=True).mean()

    lower = float(np.percentile(means, (1 - ci) / 2 * 100))
    upper = float(np.percentile(means, (1 + ci) / 2 * 100))
    return (lower, upper)


def summarize_forward_returns(
    forward_returns: pd.DataFrame,
    definition: ResearchDefinition,
) -> pd.DataFrame:
    """Summarize forward returns for every threshold x forward period."""
    valid = forward_returns[forward_returns["valid_sample"].astype(bool)]

    rows: list[dict] = []
    for threshold in definition.thresholds:
        for period in definition.forward_periods:
            cell = forward_returns[
                (forward_returns["threshold"] == threshold)
                & (forward_returns["forward_period"] == period)
            ]
            sample_count = int(len(cell))
            sub = valid[
                (valid["threshold"] == threshold)
                & (valid["forward_period"] == period)
            ]["forward_return"]
            valid_count = int(len(sub))

            if valid_count == 0:
                rows.append(
                    {
                        "threshold": threshold,
                        "forward_period": period,
                        "sample_count": sample_count,
                        "valid_sample_count": 0,
                        "mean": float("nan"),
                        "median": float("nan"),
                        "std": float("nan"),
                        "win_rate": float("nan"),
                        "q25": float("nan"),
                        "q75": float("nan"),
                        "min": float("nan"),
                        "max": float("nan"),
                        "ci_lower": float("nan"),
                        "ci_upper": float("nan"),
                    }
                )
                continue

            ci_lower, ci_upper = bootstrap_mean_ci(sub)
            rows.append(
                {
                    "threshold": threshold,
                    "forward_period": period,
                    "sample_count": sample_count,
                    "valid_sample_count": valid_count,
                    "mean": float(sub.mean()),
                    "median": float(sub.median()),
                    "std": float(sub.std()),
                    "win_rate": float((sub > 0).mean()),
                    "q25": float(sub.quantile(0.25)),
                    "q75": float(sub.quantile(0.75)),
                    "min": float(sub.min()),
                    "max": float(sub.max()),
                    "ci_lower": ci_lower,
                    "ci_upper": ci_upper,
                }
            )

    return pd.DataFrame(rows, columns=list(STATISTICS_COLUMNS))
