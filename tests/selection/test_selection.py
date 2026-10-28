"""Ranking-based selection tests (ties, missing data, suspension, PIT)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from hk_quant.selection import (
    build_selection_schedule,
    evaluate_scores,
    momentum_scorer,
    rank_by_score,
    select_top_n,
)


def test_rank_excludes_none_and_breaks_ties_deterministically() -> None:
    scores = {"A": 0.5, "B": None, "C": float("nan"), "D": 0.5, "E": 0.1}
    assert rank_by_score(scores) == ["A", "D", "E"]  # A before D by stock_id tie-break


def test_select_top_n_equal_weight() -> None:
    targets = select_top_n({"A": 0.5, "B": 0.3, "C": 0.1}, top_n=2)
    assert targets == {"A": 0.5, "B": 0.5}


def test_select_top_n_fewer_than_n_selects_available() -> None:
    targets = select_top_n({"A": 0.5, "B": None, "C": None}, top_n=3)
    assert targets == {"A": 1.0}


def test_select_top_n_no_scorable_stock_is_empty() -> None:
    assert select_top_n({"A": None, "B": float("nan")}, top_n=2) == {}


def test_select_top_n_requires_positive_n() -> None:
    with pytest.raises(ValueError):
        select_top_n({"A": 0.5}, top_n=0)


def test_momentum_scorer_hand_calculation() -> None:
    history = pd.DataFrame(
        {
            "stock_id": ["0700"] * 21,
            "trade_date": pd.bdate_range("2025-01-02", periods=21),
            "close": [100.0 + i for i in range(21)],
        }
    )
    scorer = momentum_scorer(window=20)
    assert scorer(history, "0700") == pytest.approx(120.0 / 100.0 - 1.0)


def test_momentum_scorer_insufficient_history_is_none() -> None:
    history = pd.DataFrame(
        {"stock_id": ["0700"] * 5, "trade_date": pd.bdate_range("2025-01-02", periods=5), "close": [100.0] * 5}
    )
    assert momentum_scorer(window=20)(history, "0700") is None


def test_suspension_missing_data_excluded() -> None:
    # 0941 has no rows for the lookback window -> scorer returns None -> excluded.
    history = pd.DataFrame(
        {"stock_id": ["0700"] * 21, "trade_date": pd.bdate_range("2025-01-02", periods=21), "close": [100.0] * 21}
    )
    scores = evaluate_scores(history, ["0700", "0941"], momentum_scorer(20))
    assert scores["0700"] is not None
    assert scores["0941"] is None


def test_schedule_is_point_in_time() -> None:
    panel = pd.DataFrame(
        [
            {"stock_id": s, "trade_date": d, "close": c}
            for s, closes in {
                "A": [100.0 + i for i in range(25)],
                "B": [100.0 + 0.5 * i for i in range(25)],
            }.items()
            for d, c in zip(pd.bdate_range("2025-01-02", periods=25), closes)
        ]
    )
    decision = "2025-02-04"  # the 25th session day
    scorer = momentum_scorer(20)

    before = build_selection_schedule(panel, ["A", "B"], [decision], scorer, top_n=1)

    # Mutate future (post-decision) closes drastically; decision must not change.
    future = pd.to_datetime(panel["trade_date"]) > pd.Timestamp(decision)
    panel.loc[future, "close"] = 99999.0
    after = build_selection_schedule(panel, ["A", "B"], [decision], scorer, top_n=1)

    assert before == after
    # A: 124/104-1 = 0.1923; B: 112/102-1 = 0.0980 -> A ranks first
    assert before[pd.Timestamp(decision).date().isoformat()] == {"A": 1.0}
