"""Transparent daily-return metrics over recorded portfolio equity."""

from __future__ import annotations

import math

import pandas as pd

from hk_quant.backtest.models import BacktestConfig


def compute_performance(
    daily: pd.DataFrame, trades: pd.DataFrame, config: BacktestConfig,
) -> dict[str, float | None]:
    """Annualize by configured trading sessions; undefined ratios return None."""
    if daily.empty:
        raise ValueError("performance requires at least one trading day")
    equity = daily["equity"].astype(float)
    returns = daily["daily_return"].astype(float)
    if not equity.map(math.isfinite).all() or not returns.map(math.isfinite).all():
        raise ValueError("portfolio equity and daily returns must be finite")
    days = config.annual_trading_days
    total = equity.iloc[-1] / config.initial_capital - 1.0
    cagr = ((equity.iloc[-1] / config.initial_capital) ** (days / len(daily)) - 1.0)
    volatility = returns.std(ddof=1) * math.sqrt(days) if len(returns) > 1 else None
    excess = returns - config.risk_free_rate / days
    sharpe = (excess.mean() / returns.std(ddof=1) * math.sqrt(days)) if volatility and volatility > 0 else None
    downside = math.sqrt(float((excess.clip(upper=0) ** 2).mean()))
    sortino = float(excess.mean()) / downside * math.sqrt(days) if downside > 0 else None
    peak = equity.cummax().clip(lower=config.initial_capital)
    max_drawdown = float((equity / peak - 1.0).min())
    closes = trades[trades["side"] == "SELL"] if not trades.empty else trades
    win_rate = float((closes["realized_pnl"] > 0).mean()) if not closes.empty else None
    return {
        "total_return": float(total),
        "cagr": float(cagr),
        "annualized_volatility": float(volatility) if volatility is not None else None,
        "sharpe": float(sharpe) if sharpe is not None else None,
        "sortino": float(sortino) if sortino is not None else None,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "turnover": float(daily["turnover"].sum()),
    }
