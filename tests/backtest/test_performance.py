"""Direct checks of risk/return formulas and undefined cases."""

import pandas as pd
import pytest

from hk_quant.backtest import BacktestConfig, compute_performance


def test_metrics_with_one_win_one_loss_and_drawdown():
    config = BacktestConfig(initial_capital=100, commission_rate=0, slippage_rate=0, annual_trading_days=2)
    daily = pd.DataFrame({
        "equity": [110.0, 99.0], "daily_return": [0.10, -0.10],
        "turnover": [0.20, 0.30],
    })
    trades = pd.DataFrame({"side": ["SELL", "SELL"], "realized_pnl": [1.0, -2.0]})
    metrics = compute_performance(daily, trades, config)
    assert metrics["total_return"] == pytest.approx(-0.01)
    assert metrics["cagr"] == pytest.approx(-0.01)
    assert metrics["annualized_volatility"] == pytest.approx(0.20)
    assert metrics["sharpe"] == pytest.approx(0.0)
    assert metrics["sortino"] == pytest.approx(0.0)
    assert metrics["max_drawdown"] == pytest.approx(-0.10)
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["turnover"] == pytest.approx(0.5)


def test_risk_ratios_and_win_rate_unavailable_without_observations():
    config = BacktestConfig(initial_capital=100)
    daily = pd.DataFrame({"equity": [100.0], "daily_return": [0.0], "turnover": [0.0]})
    trades = pd.DataFrame(columns=["side", "realized_pnl"])
    metrics = compute_performance(daily, trades, config)
    assert metrics["annualized_volatility"] is None
    assert metrics["sharpe"] is None
    assert metrics["sortino"] is None
    assert metrics["win_rate"] is None
