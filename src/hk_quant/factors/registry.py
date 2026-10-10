"""Factor registry.

Maps ``factor_id -> (FactorDefinition, calculator)`` so the Signal Engine can
resolve factors dynamically instead of hardcoding ``if field == ...``.
"""

from __future__ import annotations

from typing import Callable

from hk_quant.factors.models import FactorDefinition

Calculator = Callable[..., float]


class FactorRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], FactorDefinition] = {}
        self._calculators: dict[tuple[str, str], Calculator] = {}

    def register(self, definition: FactorDefinition, calculator: Calculator) -> None:
        key = (definition.factor_id, definition.version)
        self._definitions[key] = definition
        self._calculators[key] = calculator

    def get(self, factor_id: str, version: str | None = None) -> FactorDefinition:
        matches = {k: d for k, d in self._definitions.items() if k[0] == factor_id}
        if not matches:
            raise KeyError(f"unknown factor: {factor_id!r}")

        if version is not None:
            key = (factor_id, version)
            if key not in self._definitions:
                raise KeyError(f"unknown factor version: {factor_id} v{version}")
            return self._definitions[key]

        latest = max(matches.keys(), key=lambda k: _version_tuple(k[1]))
        return self._definitions[latest]

    def get_calculator(self, factor_id: str, version: str | None = None) -> Calculator:
        definition = self.get(factor_id, version)
        key = (definition.factor_id, definition.version)
        return self._calculators[key]

    def list(self) -> list[FactorDefinition]:
        return [d for _, d in sorted(self._definitions.items())]


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in str(version).split("."))


DEFAULT_REGISTRY = FactorRegistry()


def register_factor(definition: FactorDefinition, calculator: Calculator) -> None:
    DEFAULT_REGISTRY.register(definition, calculator)


def get_factor(factor_id: str, version: str | None = None) -> FactorDefinition:
    return DEFAULT_REGISTRY.get(factor_id, version)


def list_factors() -> list[FactorDefinition]:
    return DEFAULT_REGISTRY.list()
