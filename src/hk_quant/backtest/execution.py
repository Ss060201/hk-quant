"""Validate raw execution prices and simulate all-or-nothing day-open fills."""

from __future__ import annotations

import math

import pandas as pd

from hk_quant.backtest.costs import execution_price, transaction_costs
from hk_quant.backtest.models import BacktestConfig
from hk_quant.portfolio.positions import Portfolio


def raw_open_or_rejection(row: dict | None) -> tuple[float | None, str | None]:
    if row is None:
        return None, "MISSING_OPEN_PRICE"
    value = row.get("open")
    try:
        raw_open = float(value)
    except (ValueError, TypeError):
        return None, "INVALID_OPEN_PRICE"
    if not math.isfinite(raw_open) or raw_open <= 0:
        return None, "INVALID_OPEN_PRICE"
    volume = row.get("volume")
    if volume is None or pd.isna(volume):
        return None, "UNKNOWN_TRADABILITY"
    try:
        raw_volume = float(volume)
    except (ValueError, TypeError):
        return None, "UNKNOWN_TRADABILITY"
    if not math.isfinite(raw_volume) or raw_volume <= 0:
        return None, "UNTRADABLE_VOLUME"
    return raw_open, None


def fill_order(
    order: dict, raw_open: float, portfolio: Portfolio, config: BacktestConfig,
    target_value: float | None = None,
) -> dict | None:
    """Fill requested integer shares at the raw open plus modeled costs.

    Target sizing may reduce the *order size* to available whole shares; market
    partial fills, liquidity depth, HK board lots and stamp duty are not modeled.
    """
    side = order["side"]
    stock_id = order["stock_id"]
    price = execution_price(raw_open, side, config)
    if side == "SELL":
        position = portfolio.positions.get(stock_id)
        if position is None:
            order.update(status="REJECTED", reason="POSITION_NOT_HELD")
            return None
        quantity = position.quantity
    elif side == "BUY":
        if target_value is None or target_value <= 0:
            order.update(status="REJECTED", reason="INVALID_TARGET_VALUE")
            return None
        existing = portfolio.positions.get(stock_id)
        existing_value = existing.quantity * raw_open if existing else 0.0
        one_share_outlay = price * (1.0 + config.commission_rate)
        quantity = min(
            math.floor(max(0.0, target_value - existing_value) / one_share_outlay),
            math.floor((portfolio.cash + 1e-9) / one_share_outlay),
        )
        if quantity < 1:
            order.update(status="REJECTED", reason="INSUFFICIENT_CASH_OR_TARGET")
            return None
    else:
        raise ValueError(f"invalid order side: {side!r}")

    commission, slippage_cost = transaction_costs(raw_open, quantity, side, config)
    realized_pnl = 0.0
    if side == "BUY":
        portfolio.buy(stock_id, quantity, price, commission, order["execution_date"])
    else:
        realized_pnl = portfolio.sell(stock_id, quantity, price, commission)
    order.update(status="FILLED", reason=None, quantity=quantity)
    return {
        "signal_date": order["signal_date"],
        "execution_date": order["execution_date"],
        "stock_id": stock_id,
        "side": side,
        "quantity": quantity,
        "raw_open": raw_open,
        "execution_price": price,
        "notional": quantity * price,
        "commission": commission,
        "slippage_cost": slippage_cost,
        "realized_pnl": realized_pnl,
        "cash_after": portfolio.cash,
    }
