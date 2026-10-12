"""Cash conservation and HOLD-safe equal weighting."""

import pytest

from hk_quant.portfolio import Portfolio, equal_weight_targets


def test_equal_weight_only_constructs_targets_without_selling_holds():
    targets = equal_weight_targets(["A", "B"], ["C"])
    assert targets == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "C": pytest.approx(1 / 3)}
    assert sum(targets.values()) == pytest.approx(1.0)
    assert equal_weight_targets(["A", "B"], [], ["A"]) == {"B": 1.0}


def test_cash_and_realized_profit_include_commissions():
    portfolio = Portfolio(cash=1000.0)
    portfolio.buy("A", 5, 100.0, 5.0, "2026-01-05")
    assert portfolio.cash == pytest.approx(495.0)
    assert portfolio.positions["A"].cost_basis == pytest.approx(101.0)
    with pytest.raises(ValueError, match="insufficient cash"):
        portfolio.buy("B", 5, 100.0, 5.0, "2026-01-05")
    pnl = portfolio.sell("A", 5, 110.0, 5.5)
    assert pnl == pytest.approx(39.5)
    assert portfolio.realized_pnl == pytest.approx(39.5)
    assert portfolio.cash == pytest.approx(1039.5)
    assert not portfolio.positions
