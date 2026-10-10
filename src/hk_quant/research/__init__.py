"""Research Engine: study historical market patterns, not "find stocks today"."""

from hk_quant.research.config import ResearchConfigError, load_research_definition
from hk_quant.research.engine import ResearchDataError, run_research
from hk_quant.research.models import (
    DateRange,
    EventMode,
    PriceSpec,
    ResearchDefinition,
    ResearchResult,
    ResearchStatus,
    ReturnDefinition,
    UniverseMode,
    UniverseSpec,
    VariableSpec,
)

__all__ = [
    "DateRange",
    "EventMode",
    "PriceSpec",
    "ResearchConfigError",
    "ResearchDataError",
    "ResearchDefinition",
    "ResearchResult",
    "ResearchStatus",
    "ReturnDefinition",
    "UniverseMode",
    "UniverseSpec",
    "VariableSpec",
    "load_research_definition",
    "run_research",
]
