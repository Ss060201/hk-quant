"""Position bookkeeping in raw, unadjusted share units."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Position:
    stock_id: str
    quantity: int
    cost_basis: float  # average price per share including entry commission
    entry_date: str
