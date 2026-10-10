"""Built-in factors: momentum_20 and volatility_20.

Both are strictly point-in-time: the value at date ``T`` only uses closes at
``T`` and earlier trading days.
"""

from __future__ import annotations

import math

import pandas as pd

from hk_quant.factors.models import FactorDefinition
from hk_quant.factors.registry import register_factor

MOMENTUM_20 = FactorDefinition(
    factor_id="momentum_20",
    version="1.0.0",
    description="20 trading day price momentum",
    required_fields=("close",),
    frequency="daily",
    calculation_method="close[t] / close[t-20] - 1 (previous 20 trading days)",
    annualized=False,
    parameters={"window": 20},
)

VOLATILITY_20 = FactorDefinition(
    factor_id="volatility_20",
    version="1.0.0",
    description="20 trading day realized volatility of daily returns (NOT annualized)",
    required_fields=("close",),
    frequency="daily",
    calculation_method=(
        "std(daily_return over previous 20 trading days), "
        "daily_return[t] = close[t]/close[t-1] - 1; sample std (ddof=1); "
        "annualized=false"
    ),
    annualized=False,
    parameters={"window": 20},
)


def _momentum_20_calculator(close: pd.Series) -> float:
    window = int(MOMENTUM_20.parameters["window"])
    if len(close) < window + 1:
        return float("nan")
    return float(close.iloc[-1] / close.iloc[-window - 1] - 1.0)


def _volatility_20_calculator(close: pd.Series) -> float:
    window = int(VOLATILITY_20.parameters["window"])
    if len(close) < window + 1:
        return float("nan")
    daily_returns = close.pct_change().iloc[-window:]
    result = float(daily_returns.std(ddof=1))
    return result if not math.isnan(result) else float("nan")


def register_builtin_factors() -> None:
    register_factor(MOMENTUM_20, _momentum_20_calculator)
    register_factor(VOLATILITY_20, _volatility_20_calculator)
