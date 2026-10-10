"""Strategy object models.

A Strategy is a *structured, versioned rule definition* — not natural
language, not a backtest, and not a signal. It exists independently of any
particular day's market data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Union


class StrategyStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ConditionOperator(str, Enum):
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    EQ = "=="
    NEQ = "!="


class ConditionSource(str, Enum):
    DATA = "data"
    FACTOR = "factor"


class LogicalOperator(str, Enum):
    ALL = "all"
    ANY = "any"


class HoldingPeriodType(str, Enum):
    TRADING_DAYS = "trading_days"


class UniverseType(str, Enum):
    OBSERVED_PRICE = "observed_price_universe"
    HISTORICAL = "historical_universe"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Condition:
    """A single leaf condition, e.g. ``turnover_rate > 0.40`` (ratio)."""

    source: str  # "data" | "factor"
    field: str
    operator: str  # ">", ">=", "<", "<=", "==", "!="
    value: float
    unit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "field": self.field,
            "operator": self.operator,
            "value": self.value,
            "unit": self.unit,
        }


@dataclass
class ConditionGroup:
    """A logical group combining conditions (``all`` / ``any``).

    ``conditions`` may contain leaf :class:`Condition` objects and nested
    :class:`ConditionGroup` objects (limited nesting).
    """

    logic: str  # "all" | "any"
    conditions: list[Union["Condition", "ConditionGroup"]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {self.logic: [item.to_dict() for item in self.conditions]}


@dataclass
class ResearchProvenance:
    """Where this strategy came from (the research that motivated it)."""

    research_id: str
    source_status: str | None = None
    research_result_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_id": self.research_id,
            "source_status": self.source_status,
            "research_result_path": self.research_result_path,
        }


@dataclass
class UniverseSpec:
    type: str = UniverseType.OBSERVED_PRICE.value

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type}


@dataclass
class HoldingPeriod:
    type: str = HoldingPeriodType.TRADING_DAYS.value
    value: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "value": self.value}


@dataclass
class PriceDefinition:
    adjusted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"adjusted": self.adjusted}


@dataclass
class ExitSpec:
    """Exit rule: either a condition group or a holding-period exit."""

    conditions: ConditionGroup | None = None
    type: str | None = None  # "holding_period"

    def to_dict(self) -> dict[str, Any] | None:
        if self.conditions is not None:
            return self.conditions.to_dict()
        if self.type is not None:
            return {"type": self.type}
        return None


@dataclass
class StrategyDefinition:
    """A complete, versioned strategy definition."""

    strategy_id: str
    name: str
    version: str
    universe: UniverseSpec
    entry: ConditionGroup
    holding_period: HoldingPeriod
    research: ResearchProvenance | None = None
    exit: ExitSpec | None = None
    description: str = ""
    signal_frequency: str = "daily"
    price: PriceDefinition = field(default_factory=PriceDefinition)
    status: StrategyStatus = StrategyStatus.DRAFT
    created_at: str = field(default_factory=_utc_now_iso)
    strategy_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.strategy_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "research": self.research.to_dict() if self.research else None,
            "universe": self.universe.to_dict(),
            "entry": self.entry.to_dict(),
            "exit": self.exit.to_dict() if self.exit else None,
            "holding_period": self.holding_period.to_dict(),
            "signal_frequency": self.signal_frequency,
            "price": self.price.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at,
            "strategy_hash": self.strategy_hash,
        }

    def to_hashable_dict(self) -> dict[str, Any]:
        """Return the immutable rule content (excludes metadata).

        ``status``, ``created_at`` and ``strategy_hash`` are lifecycle
        metadata, so they are excluded so the same rules always hash the same.
        """
        return {
            "id": self.strategy_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "research": self.research.to_dict() if self.research else None,
            "universe": self.universe.to_dict(),
            "entry": self.entry.to_dict(),
            "exit": self.exit.to_dict() if self.exit else None,
            "holding_period": self.holding_period.to_dict(),
            "signal_frequency": self.signal_frequency,
            "price": self.price.to_dict(),
        }


def compute_strategy_hash(definition: StrategyDefinition) -> str:
    """Return a deterministic SHA-256 hash of the strategy rule content."""
    canonical = json.dumps(
        definition.to_hashable_dict(),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
