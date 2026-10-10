"""Load and parse strategy definitions from YAML.

Parsing here is *structural* only. Semantic validation (operators, field
availability, universe availability, numeric ranges) lives in
``validators.py``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Union

import yaml

from hk_quant.strategy.models import (
    Condition,
    ConditionGroup,
    ExitSpec,
    HoldingPeriod,
    PriceDefinition,
    ResearchProvenance,
    StrategyDefinition,
    StrategyStatus,
    UniverseSpec,
    _utc_now_iso,
)

PathLike = Union[str, os.PathLike[str]]


class StrategyConfigError(Exception):
    """Raised when a strategy YAML cannot be parsed into a definition."""


def load_strategy_definition(path: PathLike) -> StrategyDefinition:
    """Parse a strategy YAML file into a :class:`StrategyDefinition`."""
    config_path = Path(path)
    if not config_path.exists():
        raise StrategyConfigError(f"strategy config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise StrategyConfigError("strategy config must be a mapping")

    return _build_definition(raw)


def parse_strategy_definition(data: dict[str, Any]) -> StrategyDefinition:
    """Parse an in-memory strategy mapping (used by tests and the builder)."""
    if not isinstance(data, dict):
        raise StrategyConfigError("strategy config must be a mapping")
    return _build_definition(data)


def _build_definition(data: dict[str, Any]) -> StrategyDefinition:
    strategy_id = str(data.get("id") or data.get("strategy_id") or "").strip()
    name = str(data.get("name") or "").strip()
    version = str(data.get("version") or "").strip()

    if not strategy_id:
        raise StrategyConfigError("strategy 'id' is required")
    if not name:
        raise StrategyConfigError("strategy 'name' is required")
    if not version:
        raise StrategyConfigError("strategy 'version' is required")

    entry = _build_entry(data.get("entry"))
    universe = _build_universe(data.get("universe"))
    holding_period = _build_holding_period(data.get("holding_period"))
    exit_spec = _build_exit(data.get("exit"))
    research = _build_research(data.get("research"))
    price = _build_price(data.get("price"))

    status_raw = str(data.get("status") or StrategyStatus.DRAFT.value).upper()
    try:
        status = StrategyStatus(status_raw)
    except ValueError as exc:
        raise StrategyConfigError(
            f"unknown strategy status: {status_raw!r}"
        ) from exc

    return StrategyDefinition(
        strategy_id=strategy_id,
        name=name,
        version=version,
        description=str(data.get("description") or ""),
        research=research,
        universe=universe,
        entry=entry,
        exit=exit_spec,
        holding_period=holding_period,
        signal_frequency=str(data.get("signal_frequency") or "daily"),
        price=price,
        status=status,
        created_at=str(data.get("created_at") or _utc_now_iso()),
        strategy_hash=str(data.get("strategy_hash") or ""),
    )


def _build_entry(data: Any) -> ConditionGroup:
    if not isinstance(data, dict):
        raise StrategyConfigError("strategy 'entry' must be a mapping (all/any)")
    return _parse_condition_node(data)


def _parse_condition_node(data: Any) -> ConditionGroup | Condition:
    if not isinstance(data, dict):
        raise StrategyConfigError(f"condition must be a mapping, got {type(data).__name__}")

    if "all" in data:
        items = data["all"]
        if not isinstance(items, list):
            raise StrategyConfigError("'all' must be a list of conditions")
        return ConditionGroup(
            logic="all", conditions=[_parse_condition_node(item) for item in items]
        )
    if "any" in data:
        items = data["any"]
        if not isinstance(items, list):
            raise StrategyConfigError("'any' must be a list of conditions")
        return ConditionGroup(
            logic="any", conditions=[_parse_condition_node(item) for item in items]
        )

    required = ["field", "operator", "value"]
    missing = [key for key in required if key not in data]
    if missing:
        raise StrategyConfigError(f"condition is missing keys: {missing}")

    try:
        value = float(data["value"])
    except (TypeError, ValueError) as exc:
        raise StrategyConfigError(f"condition value must be numeric: {data['value']!r}") from exc

    return Condition(
        source=str(data.get("source") or "data"),
        field=str(data["field"]),
        operator=str(data["operator"]),
        value=value,
        unit=data.get("unit"),
    )


def _build_universe(data: Any) -> UniverseSpec:
    if data is None:
        return UniverseSpec()
    if not isinstance(data, dict):
        raise StrategyConfigError("strategy 'universe' must be a mapping")
    return UniverseSpec(type=str(data.get("type") or UniverseSpec().type))


def _build_holding_period(data: Any) -> HoldingPeriod:
    if data is None:
        return HoldingPeriod()
    if not isinstance(data, dict):
        raise StrategyConfigError("strategy 'holding_period' must be a mapping")
    try:
        value = int(data.get("value", 1))
    except (TypeError, ValueError) as exc:
        raise StrategyConfigError("holding_period.value must be an integer") from exc
    return HoldingPeriod(
        type=str(data.get("type") or HoldingPeriod().type),
        value=value,
    )


def _build_exit(data: Any) -> ExitSpec | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise StrategyConfigError("strategy 'exit' must be a mapping")

    if "type" in data:
        return ExitSpec(type=str(data["type"]))
    return ExitSpec(conditions=_parse_condition_node(data))


def _build_research(data: Any) -> ResearchProvenance | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise StrategyConfigError("strategy 'research' must be a mapping")
    research_id = data.get("research_id")
    if not research_id:
        raise StrategyConfigError("research.research_id is required")
    return ResearchProvenance(
        research_id=str(research_id),
        source_status=str(data["source_status"]) if data.get("source_status") else None,
        research_result_path=str(data["research_result_path"])
        if data.get("research_result_path")
        else None,
    )


def _build_price(data: Any) -> PriceDefinition:
    if data is None:
        return PriceDefinition()
    if not isinstance(data, dict):
        raise StrategyConfigError("strategy 'price' must be a mapping")
    return PriceDefinition(adjusted=bool(data.get("adjusted", True)))
