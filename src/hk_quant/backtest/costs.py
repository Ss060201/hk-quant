"""Deterministic linear cost assumptions for simulated fills."""

from __future__ import annotations

from hk_quant.backtest.models import BacktestConfig


def execution_price(raw_open: float, side: str, config: BacktestConfig) -> float:
    if side == "BUY":
        return raw_open * (1.0 + config.slippage_rate)
    if side == "SELL":
        return raw_open * (1.0 - config.slippage_rate)
    raise ValueError(f"unsupported side: {side}")


def transaction_costs(raw_open: float, quantity: int, side: str, config: BacktestConfig) -> tuple[float, float]:
    """Return (commission at execution notional, slippage against raw open)."""
    price = execution_price(raw_open, side, config)
    return price * quantity * config.commission_rate, abs(price - raw_open) * quantity
