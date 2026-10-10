"""Factor Registry + Factor Engine (minimal, versioned, point-in-time)."""

from hk_quant.factors.builtins import register_builtin_factors
from hk_quant.factors.engine import FACTOR_RESULT_COLUMNS, FactorEngine, calculate_factor
from hk_quant.factors.models import FactorDefinition
from hk_quant.factors.registry import (
    FactorRegistry,
    get_factor,
    list_factors,
    register_factor,
)

register_builtin_factors()

__all__ = [
    "FACTOR_RESULT_COLUMNS",
    "FactorDefinition",
    "FactorEngine",
    "FactorRegistry",
    "calculate_factor",
    "get_factor",
    "list_factors",
    "register_factor",
]
