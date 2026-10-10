"""Point-in-time / as-of data filtering.

Distinguishes *when a fact became known to the market* from *when it refers
to*::

    period_end          what period the fact describes
    announcement_date   when the market learned about it
    effective_date      when it takes effect

As-of visibility is driven by ``announcement_date``::

    announcement_date <= as_of_date  -> visible
    announcement_date is null        -> NOT visible (conservative)

We never silently forward-fill or guess a missing announcement date.
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd


def _as_of_timestamp(as_of_date: object) -> pd.Timestamp:
    ts = pd.Timestamp(as_of_date)
    if ts is pd.NaT:
        raise ValueError(f"invalid as_of_date: {as_of_date!r}")
    return ts


def get_available_as_of(data: pd.DataFrame, as_of_date: object) -> pd.DataFrame:
    """Return the rows of a PIT dataset that were known as of ``as_of_date``.

    A row is visible iff its ``announcement_date`` is not null and
    ``announcement_date <= as_of_date``. Rows with a null announcement date
    are excluded: we cannot prove they were known, so we never assume they
    were.
    """
    result = data.copy()
    if "announcement_date" not in result.columns:
        raise ValueError("PIT data must contain an 'announcement_date' column")

    as_of = _as_of_timestamp(as_of_date)
    announced = pd.to_datetime(result["announcement_date"], errors="coerce")
    visible = announced.notna() & (announced <= as_of)
    return result[visible].reset_index(drop=True)


def get_fundamentals_as_of(
    fundamentals: pd.DataFrame,
    as_of_date: object,
    stock_ids: Sequence[str] | None = None,
    metric: str | None = None,
) -> pd.DataFrame:
    """Return fundamentals visible as of ``as_of_date``, with optional filters."""
    visible = get_available_as_of(fundamentals, as_of_date)

    if stock_ids:
        ids = list(dict.fromkeys(stock_ids))
        visible = visible[visible["stock_id"].isin(ids)]
    if metric is not None:
        visible = visible[visible["metric"] == metric]
    return visible.reset_index(drop=True)
