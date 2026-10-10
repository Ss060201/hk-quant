"""Research object models.

The research engine studies *historical market patterns*, not "find stocks
today". These models describe a research definition and its result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd


class EventMode(str, Enum):
    DAILY = "daily"
    FIRST_CROSSING = "first_crossing"


class UniverseMode(str, Enum):
    OBSERVED_PRICE = "observed_price_universe"
    HISTORICAL = "historical_universe"


class ResearchStatus(str, Enum):
    """Descriptive research status, NOT an investment rating."""

    NO_EVIDENCE = "NO_EVIDENCE"
    WEAK_PATTERN = "WEAK_PATTERN"
    NOTABLE_PATTERN = "NOTABLE_PATTERN"
    WORTH_FURTHER_RESEARCH = "WORTH_FURTHER_RESEARCH"


@dataclass
class VariableSpec:
    name: str
    thresholds: list[float]  # in ratio units (0.10 == 10%)
    unit: str = "ratio"


@dataclass
class ReturnDefinition:
    entry: str = "close"
    exit: str = "close"
    type: str = "price_return"
    dividend: str = "excluded"


@dataclass
class DateRange:
    start: str | None = None
    end: str | None = None


@dataclass
class UniverseSpec:
    mode: str = UniverseMode.OBSERVED_PRICE.value


@dataclass
class PriceSpec:
    adjusted: bool = True


@dataclass
class ResearchDefinition:
    """A complete, reproducible research definition."""

    name: str
    variable: VariableSpec
    forward_periods: list[int]
    event_mode: str = EventMode.DAILY.value
    return_definition: ReturnDefinition = field(default_factory=ReturnDefinition)
    date_range: DateRange = field(default_factory=DateRange)
    universe: UniverseSpec = field(default_factory=UniverseSpec)
    price: PriceSpec = field(default_factory=PriceSpec)
    exploratory: bool = True

    @property
    def research_id(self) -> str:
        return self.name

    @property
    def thresholds(self) -> list[float]:
        return self.variable.thresholds

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "variable": {
                "name": self.variable.name,
                "unit": self.variable.unit,
                "thresholds": self.variable.thresholds,
            },
            "forward_periods": self.forward_periods,
            "event_mode": self.event_mode,
            "return": {
                "entry": self.return_definition.entry,
                "exit": self.return_definition.exit,
                "type": self.return_definition.type,
                "dividend": self.return_definition.dividend,
            },
            "date_range": {
                "start": self.date_range.start,
                "end": self.date_range.end,
            },
            "universe": {"mode": self.universe.mode},
            "price": {"adjusted": self.price.adjusted},
            "exploratory": self.exploratory,
        }


@dataclass
class ResearchResult:
    """The full, serializable outcome of one research run."""

    research_id: str
    name: str
    data_version: str
    parameters: dict[str, Any]
    events: pd.DataFrame
    forward_returns: pd.DataFrame
    statistics: pd.DataFrame
    relationship_analysis: dict[str, Any]
    warnings: list[str]
    status: ResearchStatus
    tested_combinations: int
    exploratory: bool = True
