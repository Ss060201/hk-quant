"""Strategy Builder: formal, versioned strategy definitions.

A Strategy is a fixed set of rules. It is NOT a signal, a backtest, or a
profitability claim.
"""

from hk_quant.strategy.builder import (
    build_strategy,
    build_strategy_from_dict,
    create_strategy_from_research,
)
from hk_quant.strategy.config import StrategyConfigError, load_strategy_definition
from hk_quant.strategy.models import (
    Condition,
    ConditionGroup,
    ConditionOperator,
    ConditionSource,
    ExitSpec,
    HoldingPeriod,
    PriceDefinition,
    ResearchProvenance,
    StrategyDefinition,
    StrategyStatus,
    UniverseSpec,
    compute_strategy_hash,
)
from hk_quant.strategy.storage import (
    StrategyImmutabilityError,
    load_strategy,
    save_strategy,
)
from hk_quant.strategy.validators import StrategyValidationError, validate_strategy

__all__ = [
    "Condition",
    "ConditionGroup",
    "ConditionOperator",
    "ConditionSource",
    "ExitSpec",
    "HoldingPeriod",
    "PriceDefinition",
    "ResearchProvenance",
    "StrategyConfigError",
    "StrategyDefinition",
    "StrategyImmutabilityError",
    "StrategyStatus",
    "StrategyValidationError",
    "UniverseSpec",
    "build_strategy",
    "build_strategy_from_dict",
    "compute_strategy_hash",
    "create_strategy_from_research",
    "load_strategy",
    "load_strategy_definition",
    "save_strategy",
    "validate_strategy",
]
