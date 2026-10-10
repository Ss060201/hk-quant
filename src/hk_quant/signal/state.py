"""Position state used by the Signal Engine.

This is NOT a portfolio: it only records whether a strategy already holds a
stock and when it entered, so holding-period exits can be evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionState:
    stock_id: str
    entry_date: str
    strategy_id: str
    strategy_version: str
