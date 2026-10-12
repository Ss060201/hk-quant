"""Long-only cash and position ledger."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from hk_quant.portfolio.models import Position


@dataclass
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0

    def buy(
        self, stock_id: str, quantity: int, execution_price: float,
        commission: float, trade_date: str,
    ) -> None:
        if quantity <= 0 or not math.isfinite(execution_price) or execution_price <= 0:
            raise ValueError("buy requires positive quantity and execution price")
        if commission < 0 or not math.isfinite(commission):
            raise ValueError("commission must be finite and nonnegative")
        outlay = quantity * execution_price + commission
        if outlay > self.cash + 1e-8:
            raise ValueError("insufficient cash for purchase including commission")
        old = self.positions.get(stock_id)
        if old is None:
            self.positions[stock_id] = Position(
                stock_id, quantity, outlay / quantity, trade_date,
            )
        else:
            old.cost_basis = (old.cost_basis * old.quantity + outlay) / (old.quantity + quantity)
            old.quantity += quantity
        self.cash = max(0.0, self.cash - outlay)

    def sell(
        self, stock_id: str, quantity: int, execution_price: float,
        commission: float,
    ) -> float:
        position = self.positions.get(stock_id)
        if position is None or quantity <= 0 or quantity > position.quantity:
            raise ValueError("sell requires available positive shares")
        if not math.isfinite(execution_price) or execution_price <= 0:
            raise ValueError("sell requires positive execution price")
        if commission < 0 or not math.isfinite(commission):
            raise ValueError("commission must be finite and nonnegative")
        pnl = quantity * (execution_price - position.cost_basis) - commission
        self.realized_pnl += pnl
        self.cash += quantity * execution_price - commission
        position.quantity -= quantity
        if position.quantity == 0:
            del self.positions[stock_id]
        return pnl
