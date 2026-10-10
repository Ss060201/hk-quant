"""Strategy validation.

Checks schema, condition operators, field availability (data vs factor),
numeric sanity, holding period, universe availability and version format.
Validation never silently skips unknown fields.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from hk_quant.strategy.models import (
    Condition,
    ConditionGroup,
    ConditionOperator,
    ConditionSource,
    HoldingPeriodType,
    StrategyDefinition,
    UniverseType,
)

#: Data fields available in the canonical daily price schema.
KNOWN_DATA_FIELDS: set[str] = {
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
}

#: Data fields that exist in the schema but are NOT supplied by the current
#: provider. ``turnover_rate`` is unavailable (provider only gives 成交額).
UNAVAILABLE_DATA_FIELDS: set[str] = {"turnover_rate"}

_OPERATORS = {op.value for op in ConditionOperator}
_SOURCES = {src.value for src in ConditionSource}
_UNIVERSE_TYPES = {u.value for u in UniverseType}
_HOLDING_PERIOD_TYPES = {h.value for h in HoldingPeriodType}
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ALLOWED_SIGNAL_FREQUENCIES = {"daily"}

#: Fields whose natural unit is a ratio in [0, 1].
_RATIO_FIELDS = {"turnover_rate"}
#: Fields that must be non-negative regardless of unit.
_NON_NEGATIVE_FIELDS = {"open", "high", "low", "close", "volume", "amount"}


class StrategyValidationError(Exception):
    """Raised when a strategy definition is invalid or uses unavailable data."""


def validate_strategy(
    strategy: StrategyDefinition,
    repository: Any | None = None,
) -> StrategyDefinition:
    """Validate a strategy definition and return it (or raise)."""
    _validate_header(strategy)
    _validate_universe(strategy, repository)
    _validate_holding_period(strategy)
    _validate_conditions(strategy.entry)
    if strategy.exit is not None and strategy.exit.conditions is not None:
        _validate_conditions(strategy.exit.conditions)
    if strategy.exit is not None and strategy.exit.type is not None:
        if strategy.exit.type != "holding_period":
            raise StrategyValidationError(
                f"exit.type must be 'holding_period', got {strategy.exit.type!r}"
            )
    if strategy.signal_frequency not in _ALLOWED_SIGNAL_FREQUENCIES:
        raise StrategyValidationError(
            f"signal_frequency must be one of {sorted(_ALLOWED_SIGNAL_FREQUENCIES)}"
        )
    return strategy


def _validate_header(strategy: StrategyDefinition) -> None:
    if not strategy.strategy_id.strip():
        raise StrategyValidationError("strategy_id is required")
    if not strategy.name.strip():
        raise StrategyValidationError("name is required")
    if not _VERSION_RE.match(strategy.version):
        raise StrategyValidationError(
            f"version must match X.Y.Z (e.g. 1.0.0), got {strategy.version!r}"
        )


def _validate_universe(strategy: StrategyDefinition, repository: Any | None) -> None:
    if strategy.universe.type not in _UNIVERSE_TYPES:
        raise StrategyValidationError(
            f"universe.type must be one of {sorted(_UNIVERSE_TYPES)}"
        )

    if strategy.universe.type == UniverseType.HISTORICAL.value and repository is not None:
        from hk_quant.data.universe import UniverseDataUnavailableError

        try:
            repository.get_universe(date.today().isoformat())
        except UniverseDataUnavailableError as exc:
            raise StrategyValidationError(
                "historical_universe is unavailable from the current data provider"
            ) from exc


def _validate_holding_period(strategy: StrategyDefinition) -> None:
    if strategy.holding_period.type not in _HOLDING_PERIOD_TYPES:
        raise StrategyValidationError(
            f"holding_period.type must be one of {sorted(_HOLDING_PERIOD_TYPES)}"
        )
    if strategy.holding_period.value <= 0:
        raise StrategyValidationError("holding_period.value must be a positive integer")


def _validate_conditions(group: ConditionGroup) -> None:
    if group.logic not in {"all", "any"}:
        raise StrategyValidationError(f"condition logic must be 'all' or 'any', got {group.logic!r}")
    if not group.conditions:
        raise StrategyValidationError("condition group must not be empty")

    for node in group.conditions:
        if isinstance(node, ConditionGroup):
            _validate_conditions(node)
        else:
            _validate_leaf(node)


def _validate_leaf(condition: Condition) -> None:
    if condition.source not in _SOURCES:
        raise StrategyValidationError(
            f"condition source must be one of {sorted(_SOURCES)}, got {condition.source!r}"
        )
    if condition.operator not in _OPERATORS:
        raise StrategyValidationError(
            f"condition operator must be one of {sorted(_OPERATORS)}, got {condition.operator!r}"
        )
    if not condition.field or not condition.field.strip():
        raise StrategyValidationError("condition field is required")
    if not _is_finite(condition.value):
        raise StrategyValidationError(
            f"condition value must be a finite number, got {condition.value!r}"
        )

    if condition.source == ConditionSource.FACTOR.value:
        from hk_quant.factors import get_factor

        try:
            get_factor(condition.field)
        except KeyError as exc:
            raise StrategyValidationError(
                f"unknown factor field {condition.field!r}"
            ) from exc
        return

    # source == data
    if condition.field not in KNOWN_DATA_FIELDS:
        raise StrategyValidationError(f"unknown data field {condition.field!r}")
    if condition.field in UNAVAILABLE_DATA_FIELDS:
        raise StrategyValidationError(
            f"data field {condition.field!r} is unavailable from the current "
            "data provider; do not substitute another field (e.g. amount)"
        )

    _validate_numeric_range(condition)


def _validate_numeric_range(condition: Condition) -> None:
    value = float(condition.value)
    unit = condition.unit

    if unit == "ratio":
        if not (0.0 <= value <= 1.0):
            raise StrategyValidationError(
                f"ratio value must be in [0, 1], got {value}"
            )
        return
    if unit == "percent":
        if not (0.0 <= value <= 100.0):
            raise StrategyValidationError(
                f"percent value must be in [0, 100], got {value}"
            )
        return

    # No explicit unit: apply field-specific sanity.
    if condition.field in _RATIO_FIELDS:
        if not (0.0 <= value <= 1.0):
            raise StrategyValidationError(
                f"field {condition.field!r} is a ratio; value must be in [0, 1], got {value}"
            )
    elif condition.field in _NON_NEGATIVE_FIELDS and value < 0:
        raise StrategyValidationError(
            f"field {condition.field!r} must be non-negative, got {value}"
        )


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
