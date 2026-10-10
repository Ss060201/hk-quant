"""Condition evaluation (reuses the Strategy condition schema).

Implements three-valued logic: a condition can be True, False, or
*unavailable* (when the required value is missing). Missing data never
defaults to False.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from hk_quant.strategy.models import Condition, ConditionGroup
from hk_quant.signal.models import ConditionResult


@dataclass
class EvaluationResult:
    passed: bool | None  # None = unavailable
    available: bool
    condition_results: list[ConditionResult] = field(default_factory=list)


def evaluate_condition_group(group: ConditionGroup, values: dict[str, Any]) -> EvaluationResult:
    """Evaluate a condition group against a ``{field: value}`` mapping."""
    results: list[ConditionResult] = []
    passed_flags: list[bool | None] = []

    for node in group.conditions:
        if isinstance(node, ConditionGroup):
            child = evaluate_condition_group(node, values)
            results.extend(child.condition_results)
            passed_flags.append(child.passed)
        else:
            leaf = evaluate_leaf(node, values.get(node.field))
            results.append(leaf)
            passed_flags.append(leaf.passed)

    if group.logic == "all":
        if any(flag is False for flag in passed_flags):
            passed, available = False, True
        elif any(flag is None for flag in passed_flags):
            passed, available = None, False
        else:
            passed, available = True, True
    else:  # any
        if any(flag is True for flag in passed_flags):
            passed, available = True, True
        elif any(flag is None for flag in passed_flags):
            passed, available = None, False
        else:
            passed, available = False, True

    return EvaluationResult(passed=passed, available=available, condition_results=results)


def evaluate_leaf(condition: Condition, value: Any) -> ConditionResult:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ConditionResult(
            field=condition.field,
            actual_value=None,
            operator=condition.operator,
            target_value=condition.value,
            passed=None,
            source=condition.source,
        )

    actual = float(value)
    return ConditionResult(
        field=condition.field,
        actual_value=actual,
        operator=condition.operator,
        target_value=condition.value,
        passed=_compare(actual, condition.operator, condition.value),
        source=condition.source,
    )


def collect_conditions(group: ConditionGroup) -> list[Condition]:
    """Flatten a condition group into its leaf conditions."""
    leaves: list[Condition] = []
    for node in group.conditions:
        if isinstance(node, ConditionGroup):
            leaves.extend(collect_conditions(node))
        else:
            leaves.append(node)
    return leaves


def _compare(actual: float, operator: str, target: float) -> bool:
    if operator == ">":
        return actual > target
    if operator == ">=":
        return actual >= target
    if operator == "<":
        return actual < target
    if operator == "<=":
        return actual <= target
    if operator == "==":
        return actual == target
    if operator == "!=":
        return actual != target
    raise ValueError(f"unsupported operator: {operator!r}")
