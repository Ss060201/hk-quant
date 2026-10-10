"""Factor object models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FactorDefinition:
    """A versioned, documented factor definition."""

    factor_id: str
    version: str
    description: str
    required_fields: tuple[str, ...]
    frequency: str = "daily"
    calculation_method: str = ""
    annualized: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "version": self.version,
            "description": self.description,
            "required_fields": list(self.required_fields),
            "frequency": self.frequency,
            "calculation_method": self.calculation_method,
            "annualized": self.annualized,
            "parameters": self.parameters,
        }
