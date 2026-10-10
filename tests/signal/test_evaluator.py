"""Condition evaluator tests (three-valued logic)."""

from __future__ import annotations

import math

from hk_quant.signal.evaluator import evaluate_condition_group, evaluate_leaf
from hk_quant.strategy.models import Condition, ConditionGroup


def test_operators() -> None:
    assert evaluate_leaf(Condition("data", "close", ">", 100), 101).passed is True
    assert evaluate_leaf(Condition("data", "close", ">=", 100), 100).passed is True
    assert evaluate_leaf(Condition("data", "close", "<", 100), 99).passed is True
    assert evaluate_leaf(Condition("data", "close", "<=", 100), 100).passed is True
    assert evaluate_leaf(Condition("data", "close", "==", 100), 100).passed is True
    assert evaluate_leaf(Condition("data", "close", "!=", 100), 101).passed is True


def test_missing_value_is_unavailable_not_false() -> None:
    result = evaluate_leaf(Condition("data", "close", ">", 100), None)
    assert result.passed is None
    assert result.actual_value is None


def test_nan_value_is_unavailable() -> None:
    result = evaluate_leaf(Condition("data", "close", ">", 100), float("nan"))
    assert result.passed is None


def test_all_group() -> None:
    group = ConditionGroup(
        logic="all",
        conditions=[
            Condition("data", "close", ">", 100),
            Condition("data", "volume", ">", 1000),
        ],
    )
    result = evaluate_condition_group(group, {"close": 200.0, "volume": 2000.0})
    assert result.passed is True
    assert result.available is True

    result = evaluate_condition_group(group, {"close": 200.0, "volume": 500.0})
    assert result.passed is False
    assert result.available is True


def test_all_group_with_missing_is_unavailable() -> None:
    group = ConditionGroup(
        logic="all",
        conditions=[
            Condition("data", "close", ">", 100),
            Condition("data", "volume", ">", 1000),
        ],
    )
    result = evaluate_condition_group(group, {"close": 200.0, "volume": None})
    assert result.passed is None
    assert result.available is False


def test_any_group() -> None:
    group = ConditionGroup(
        logic="any",
        conditions=[
            Condition("data", "close", ">", 100),
            Condition("data", "volume", ">", 1000),
        ],
    )
    result = evaluate_condition_group(group, {"close": 50.0, "volume": 5000.0})
    assert result.passed is True

    result = evaluate_condition_group(group, {"close": 50.0, "volume": 500.0})
    assert result.passed is False
    assert result.available is True


def test_nested_group() -> None:
    group = ConditionGroup(
        logic="all",
        conditions=[
            Condition("data", "close", ">", 100),
            ConditionGroup(
                logic="any",
                conditions=[
                    Condition("data", "volume", ">", 1000),
                    Condition("data", "amount", ">", 1000),
                ],
            ),
        ],
    )
    result = evaluate_condition_group(group, {"close": 200.0, "volume": 500.0, "amount": 5000.0})
    assert result.passed is True
    assert len(result.condition_results) == 3
