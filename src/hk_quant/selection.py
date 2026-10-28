"""Ranking-based selection: score -> rank -> top-N -> equal weight.

All scoring uses only data up to and including the decision date (strict
point-in-time). A scorer is a plain callable, so new selection ideas can be
implemented and tested without touching the ranking/selection plumbing.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable

import pandas as pd

#: Maps (history DataFrame up to decision date, stock_id) -> score or None.
#: ``None`` means "cannot score" (missing data, suspension, insufficient history)
#: and the stock is excluded rather than silently given a zero or a guess.
Scorer = Callable[[pd.DataFrame, str], float | None]


def momentum_scorer(window: int = 20) -> Scorer:
    """Return a ``window``-day close momentum scorer.

    This is an explicit *example* factor to validate the selection flow; it is
    not a claim that momentum is a profitable or validated signal.
    """
    def score(history: pd.DataFrame, stock_id: str) -> float | None:
        sub = history[history["stock_id"] == stock_id].sort_values("trade_date")
        close = sub["close"].astype("float64").dropna()
        if len(close) < window + 1:
            return None
        return float(close.iloc[-1] / close.iloc[-window - 1] - 1.0)

    return score


def evaluate_scores(
    history: pd.DataFrame,
    stock_ids: Iterable[str],
    scorer: Scorer,
) -> dict[str, float | None]:
    """Evaluate one scorer over every stock (already restricted to PIT history)."""
    return {stock_id: scorer(history, stock_id) for stock_id in stock_ids}


def rank_by_score(scores: dict[str, float | None]) -> list[str]:
    """Rank by descending score; ``None``/NaN excluded.

    Ties are broken by stock_id for a deterministic result.
    """
    valid: dict[str, float] = {}
    for stock_id, value in scores.items():
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            valid[stock_id] = number
    return sorted(valid, key=lambda stock_id: (-valid[stock_id], stock_id))


def select_top_n(scores: dict[str, float | None], top_n: int) -> dict[str, float]:
    """Select the top ``top_n`` stocks by score with equal weights.

    Returns ``{stock_id: weight}``. Fewer than ``top_n`` scorable stocks
    selects only those available; no scorable stocks returns an empty dict.
    """
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    ranked = rank_by_score(scores)
    selected = ranked[:top_n]
    if not selected:
        return {}
    weight = 1.0 / len(selected)
    return {stock_id: weight for stock_id in selected}


def build_selection_schedule(
    panel: pd.DataFrame,
    stock_ids: Iterable[str],
    rebalance_dates: Iterable[object],
    scorer: Scorer,
    top_n: int,
) -> dict[str, dict[str, float]]:
    """For each rebalance date, pick top-N equal-weight targets.

    Only rows with ``trade_date <= rebalance_date`` are passed to the scorer,
    so future prices never influence a selection.
    """
    ids = list(dict.fromkeys(stock_ids))
    panel_dates = pd.to_datetime(panel["trade_date"], errors="coerce")
    schedule: dict[str, dict[str, float]] = {}
    for day in rebalance_dates:
        cutoff = pd.Timestamp(day)
        history = panel[panel_dates <= cutoff]
        scores = evaluate_scores(history, ids, scorer)
        key = pd.Timestamp(day).date().isoformat()
        schedule[key] = select_top_n(scores, top_n)
    return schedule
