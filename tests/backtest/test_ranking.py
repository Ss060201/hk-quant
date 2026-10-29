"""Ranking backtest tests (top-N, rebalance, PIT, dividends)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.backtest.models import BacktestConfig
from hk_quant.backtest.ranking import run_ranking_backtest
from hk_quant.selection import momentum_scorer
from tests.backtest.conftest import price_rows

ZERO_COST = BacktestConfig(initial_capital=10_000, commission_rate=0.0, slippage_rate=0.0)


def _rising(stock_id: str, n: int = 45) -> list[dict]:
    return price_rows(stock_id, n, "2026-01-30", closes=[100.0 * (1.01 ** i) for i in range(n)])


def _flat(stock_id: str, n: int = 45) -> list[dict]:
    return price_rows(stock_id, n, "2026-01-30", closes=[100.0] * n)


def _falling(stock_id: str, n: int = 45) -> list[dict]:
    return price_rows(stock_id, n, "2026-01-30", closes=[100.0 * (0.99 ** i) for i in range(n)])


def _panel() -> pd.DataFrame:
    return pd.DataFrame(_rising("A") + _flat("B") + _falling("C"))


def _action(stock_id: str, event_date: str, cash: float) -> dict:
    return {
        "stock_id": stock_id, "event_date": pd.Timestamp(event_date),
        "announcement_date": pd.Timestamp(event_date) - pd.Timedelta(days=2),
        "action_type": "dividend", "factor": None, "cash_amount": cash,
        "source": "synthetic", "ingested_at": pd.Timestamp.now("UTC"),
    }


def test_ranking_selects_top_n_and_equal_weight(make_repo) -> None:
    repo = make_repo(_panel())
    result = run_ranking_backtest(
        repo, ["A", "B", "C"], "2026-01-02", "2026-01-30",
        scorer=momentum_scorer(20), top_n=2, rebalance_frequency=100, config=ZERO_COST,
    )
    first = result.decisions[result.decisions["rebalance_date"] == result.decisions["rebalance_date"].min()]
    selected = set(first[first["selected"]]["stock_id"])
    assert selected == {"A", "B"}  # A rising, B flat beat C falling
    assert set(first[first["selected"]]["target_weight"]) == {0.5}
    assert set(result.trades["stock_id"]) == {"A", "B"}


def test_ranking_rebalance_sells_dropped(make_repo) -> None:
    def flip_scorer(history, stock_id):
        sub = history[history["stock_id"] == stock_id]
        if sub.empty:
            return None
        last = pd.to_datetime(sub["trade_date"]).max()
        if last <= pd.Timestamp("2026-01-15"):
            return {"A": 3.0, "B": 2.0, "C": 1.0}[stock_id]
        return {"A": 3.0, "B": 1.0, "C": 2.0}[stock_id]

    repo = make_repo(_panel())
    result = run_ranking_backtest(
        repo, ["A", "B", "C"], "2026-01-02", "2026-01-30",
        scorer=flip_scorer, top_n=2, rebalance_frequency=1, config=ZERO_COST,
    )
    late = result.decisions[result.decisions["rebalance_date"] > "2026-01-15"]
    late_selected = set(late[late["selected"]]["stock_id"])
    assert late_selected == {"A", "C"}
    assert "SELL" in set(result.orders[result.orders["stock_id"] == "B"]["side"])
    assert "BUY" in set(result.orders[result.orders["stock_id"] == "C"]["side"])


def test_tie_broken_deterministically(make_repo) -> None:
    panel = pd.DataFrame(_flat("B") + _flat("A") + _rising("C"))
    repo = make_repo(panel)
    result = run_ranking_backtest(
        repo, ["A", "B", "C"], "2026-01-02", "2026-01-30",
        scorer=momentum_scorer(20), top_n=2, rebalance_frequency=100, config=ZERO_COST,
    )
    first = result.decisions[result.decisions["rebalance_date"] == result.decisions["rebalance_date"].min()]
    # C (rising) ranks first; A and B tie at 0 -> A before B by stock_id
    assert list(first[first["rank"].notna()].sort_values("rank")["stock_id"]) == ["C", "A", "B"]
    assert set(first[first["selected"]]["stock_id"]) == {"C", "A"}


def test_missing_data_excluded(make_repo) -> None:
    panel = pd.DataFrame(_rising("A") + _rising("B"))  # C absent entirely
    repo = make_repo(panel)
    result = run_ranking_backtest(
        repo, ["A", "B", "C"], "2026-01-02", "2026-01-30",
        scorer=momentum_scorer(20), top_n=3, rebalance_frequency=100, config=ZERO_COST,
    )
    first = result.decisions[result.decisions["rebalance_date"] == result.decisions["rebalance_date"].min()]
    assert not bool(first[first["stock_id"] == "C"]["selected"].iloc[0])


def test_fewer_than_n_selects_available(make_repo) -> None:
    # Only A has enough history for momentum_20; B has 5 days.
    panel = pd.DataFrame(_rising("A") + price_rows("B", 5, "2026-01-30"))
    repo = make_repo(panel)
    result = run_ranking_backtest(
        repo, ["A", "B"], "2026-01-02", "2026-01-30",
        scorer=momentum_scorer(20), top_n=2, rebalance_frequency=100, config=ZERO_COST,
    )
    first = result.decisions[result.decisions["rebalance_date"] == result.decisions["rebalance_date"].min()]
    selected = first[first["selected"]]
    assert selected["stock_id"].tolist() == ["A"]
    assert selected["target_weight"].tolist() == [1.0]


def test_ranking_is_point_in_time(make_repo) -> None:
    panel = _panel()
    repo = make_repo(panel)
    before = run_ranking_backtest(
        repo, ["A", "B", "C"], "2026-01-02", "2026-01-30",
        scorer=momentum_scorer(20), top_n=2, rebalance_frequency=1, config=ZERO_COST,
    ).decisions

    # Mutate the final day's close; only the final rebalance may change.
    panel.loc[pd.to_datetime(panel["trade_date"]) == pd.Timestamp("2026-01-30"), "close"] = 99999.0
    after = run_ranking_backtest(
        repo, ["A", "B", "C"], "2026-01-02", "2026-01-30",
        scorer=momentum_scorer(20), top_n=2, rebalance_frequency=1, config=ZERO_COST,
    ).decisions

    pd.testing.assert_frame_equal(
        before[before["rebalance_date"] < "2026-01-30"],
        after[after["rebalance_date"] < "2026-01-30"],
    )


def test_dividend_credited_on_ex_date(make_repo) -> None:
    days = pd.bdate_range(end="2026-01-16", periods=10)
    ex = days[4].date().isoformat()
    panel = pd.DataFrame(price_rows("A", 10, "2026-01-16"))
    actions = pd.DataFrame([_action("A", ex, 0.5)])
    repo = make_repo(panel, actions)

    def flat_scorer(history, stock_id):
        sub = history[history["stock_id"] == stock_id]
        return 1.0 if not sub.empty else None

    result = run_ranking_backtest(
        repo, ["A"], "2026-01-05", "2026-01-16",
        scorer=flat_scorer, top_n=1, rebalance_frequency=100, config=ZERO_COST,
    )
    assert len(result.dividends) == 1
    assert result.dividends.iloc[0]["cash_flow"] == pytest.approx(50.0)  # 100 shares x 0.5
    row = result.daily[result.daily["trade_date"] == ex].iloc[0]
    assert row["dividend_cash"] == pytest.approx(50.0)
    assert row["cash"] == pytest.approx(50.0)  # cash 0 after buy + dividend


def test_dividend_no_holding_no_credit(make_repo) -> None:
    days = pd.bdate_range(end="2026-01-16", periods=10)
    ex = days[2].date().isoformat()  # before the first buy at day 1? use a day with no position
    panel = pd.DataFrame(price_rows("A", 10, "2026-01-16"))
    actions = pd.DataFrame([_action("A", ex, 0.5)])
    repo = make_repo(panel, actions)

    # Scorer never selects any stock -> no position -> no dividend.
    result = run_ranking_backtest(
        repo, ["A"], "2026-01-05", "2026-01-16",
        scorer=lambda history, stock_id: None, top_n=1, rebalance_frequency=100, config=ZERO_COST,
    )
    assert result.dividends.empty


def test_dividend_same_day_two_distributions(make_repo) -> None:
    days = pd.bdate_range(end="2026-01-16", periods=10)
    ex = days[4].date().isoformat()
    panel = pd.DataFrame(price_rows("A", 10, "2026-01-16"))
    actions = pd.DataFrame([_action("A", ex, 0.25), _action("A", ex, 0.10)])
    repo = make_repo(panel, actions)

    def flat_scorer(history, stock_id):
        return 1.0 if not history[history["stock_id"] == stock_id].empty else None

    result = run_ranking_backtest(
        repo, ["A"], "2026-01-05", "2026-01-16",
        scorer=flat_scorer, top_n=1, rebalance_frequency=100, config=ZERO_COST,
    )
    # Both credited on the same ex-date: 100 shares x (0.25 + 0.10) = 35.0
    assert result.dividends["cash_flow"].sum() == pytest.approx(35.0)
    row = result.daily[result.daily["trade_date"] == ex].iloc[0]
    assert row["dividend_cash"] == pytest.approx(35.0)


def test_dividend_not_double_credited_across_runs(make_repo) -> None:
    days = pd.bdate_range(end="2026-01-16", periods=10)
    ex = days[4].date().isoformat()
    panel = pd.DataFrame(price_rows("A", 10, "2026-01-16"))
    actions = pd.DataFrame([_action("A", ex, 0.5)])
    repo = make_repo(panel, actions)

    def flat_scorer(history, stock_id):
        return 1.0 if not history[history["stock_id"] == stock_id].empty else None

    kwargs = dict(scorer=flat_scorer, top_n=1, rebalance_frequency=100, config=ZERO_COST)
    first = run_ranking_backtest(repo, ["A"], "2026-01-05", "2026-01-16", **kwargs)
    second = run_ranking_backtest(repo, ["A"], "2026-01-05", "2026-01-16", **kwargs)
    pd.testing.assert_frame_equal(first.daily, second.daily)
    pd.testing.assert_frame_equal(first.dividends, second.dividends)
