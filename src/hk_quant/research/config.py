"""Load and validate research definitions from YAML."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Union

import yaml

from hk_quant.research.models import (
    DateRange,
    EventMode,
    PriceSpec,
    ResearchDefinition,
    ReturnDefinition,
    UniverseMode,
    UniverseSpec,
    VariableSpec,
)

PathLike = Union[str, os.PathLike[str]]

_EVENT_MODES = {m.value for m in EventMode}
_UNIVERSE_MODES = {
    UniverseMode.OBSERVED_PRICE.value,
    UniverseMode.HISTORICAL.value,
}
_PRICE_COLUMNS = {"open", "high", "low", "close"}


class ResearchConfigError(Exception):
    """Raised when a research definition is invalid."""


def load_research_definition(path: PathLike) -> ResearchDefinition:
    """Load a research YAML file and return a validated definition."""
    config_path = Path(path)
    if not config_path.exists():
        raise ResearchConfigError(f"research config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict) or "research" not in raw:
        raise ResearchConfigError("research config must contain a top-level 'research' key")

    return _build_definition(raw["research"])


def _build_definition(data: dict[str, Any]) -> ResearchDefinition:
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise ResearchConfigError("research.name is required and must be a string")

    variable = _build_variable(data.get("variable"))
    forward_periods = _build_forward_periods(data.get("forward_periods"))
    event_mode = _build_event_mode(data.get("event_mode"))
    return_def = _build_return(data.get("return"))
    date_range = _build_date_range(data.get("date_range"))
    universe = _build_universe(data.get("universe"))
    price = _build_price(data.get("price"))

    return ResearchDefinition(
        name=name,
        variable=variable,
        forward_periods=forward_periods,
        event_mode=event_mode,
        return_definition=return_def,
        date_range=date_range,
        universe=universe,
        price=price,
        exploratory=bool(data.get("exploratory", True)),
    )


def _build_variable(data: Any) -> VariableSpec:
    if not isinstance(data, dict):
        raise ResearchConfigError("research.variable must be a mapping")

    name = data.get("name")
    if not name or not isinstance(name, str):
        raise ResearchConfigError("research.variable.name is required")

    raw_thresholds = data.get("thresholds")
    if not isinstance(raw_thresholds, list) or not raw_thresholds:
        raise ResearchConfigError("research.variable.thresholds must be a non-empty list")

    unit = str(data.get("unit", "ratio"))
    if unit not in {"ratio", "percent"}:
        raise ResearchConfigError("research.variable.unit must be 'ratio' or 'percent'")

    thresholds: list[float] = []
    for value in raw_thresholds:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ResearchConfigError(f"invalid threshold: {value!r}") from exc
        if number <= 0:
            raise ResearchConfigError(f"thresholds must be > 0, got {number}")
        # Normalize percent -> ratio so the unit inside the system is always
        # "ratio" (turnover_rate == 0.10 means 10%).
        thresholds.append(number / 100.0 if unit == "percent" else number)

    thresholds = sorted(set(thresholds))
    return VariableSpec(name=name, thresholds=thresholds, unit="ratio")


def _build_forward_periods(data: Any) -> list[int]:
    if not isinstance(data, list) or not data:
        raise ResearchConfigError("research.forward_periods must be a non-empty list")
    periods: list[int] = []
    for value in data:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ResearchConfigError(f"invalid forward period: {value!r}") from exc
        if number <= 0:
            raise ResearchConfigError(f"forward periods must be > 0, got {number}")
        periods.append(number)
    return sorted(set(periods))


def _build_event_mode(data: Any) -> str:
    mode = data or "daily"
    if mode not in _EVENT_MODES:
        raise ResearchConfigError(f"event_mode must be one of {sorted(_EVENT_MODES)}")
    return mode


def _build_return(data: Any) -> ReturnDefinition:
    if data is None:
        return ReturnDefinition()
    if not isinstance(data, dict):
        raise ResearchConfigError("research.return must be a mapping")

    entry = data.get("entry", "close")
    exit_col = data.get("exit", "close")
    if entry not in _PRICE_COLUMNS or exit_col not in _PRICE_COLUMNS:
        raise ResearchConfigError(
            f"return entry/exit must be one of {sorted(_PRICE_COLUMNS)}"
        )
    return ReturnDefinition(
        entry=entry,
        exit=exit_col,
        type=str(data.get("type", "price_return")),
        dividend=str(data.get("dividend", "excluded")),
    )


def _build_date_range(data: Any) -> DateRange:
    if data is None:
        return DateRange()
    if not isinstance(data, dict):
        raise ResearchConfigError("research.date_range must be a mapping")
    return DateRange(start=data.get("start"), end=data.get("end"))


def _build_universe(data: Any) -> UniverseSpec:
    if data is None:
        return UniverseSpec()
    if not isinstance(data, dict):
        raise ResearchConfigError("research.universe must be a mapping")
    mode = data.get("mode", "observed_price_universe")
    if mode not in _UNIVERSE_MODES:
        raise ResearchConfigError(f"universe.mode must be one of {sorted(_UNIVERSE_MODES)}")
    return UniverseSpec(mode=mode)


def _build_price(data: Any) -> PriceSpec:
    if data is None:
        return PriceSpec()
    if not isinstance(data, dict):
        raise ResearchConfigError("research.price must be a mapping")
    return PriceSpec(adjusted=bool(data.get("adjusted", True)))
