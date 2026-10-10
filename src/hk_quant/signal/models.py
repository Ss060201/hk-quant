"""Signal object models.

A Signal is the result of applying a fixed Strategy to one stock on one day.
It is deterministic and carries a structured, verifiable reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class SignalStatus(str, Enum):
    VALID = "VALID"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    OUT_OF_UNIVERSE = "OUT_OF_UNIVERSE"
    INVALID = "INVALID"


@dataclass
class ConditionResult:
    """Structured result of evaluating one condition."""

    field: str
    actual_value: float | None
    operator: str
    target_value: float
    passed: bool | None  # None = data unavailable
    source: str = "data"

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "actual_value": self.actual_value,
            "operator": self.operator,
            "target_value": self.target_value,
            "passed": self.passed,
            "source": self.source,
        }


@dataclass
class Signal:
    strategy_id: str
    strategy_version: str
    strategy_hash: str
    stock_id: str
    signal_date: str
    signal: str | None  # BUY / SELL / HOLD / None
    status: SignalStatus
    reason: dict[str, Any]
    data_version: str | None = None
    factor_versions: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_hash": self.strategy_hash,
            "stock_id": self.stock_id,
            "signal_date": self.signal_date,
            "signal": self.signal,
            "status": self.status.value,
            "reason": self.reason,
            "data_version": self.data_version,
            "factor_versions": self.factor_versions,
            "warnings": self.warnings,
        }
