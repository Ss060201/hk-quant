"""Simulation configuration and inspectable output."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import pandas as pd


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.001
    slippage_rate: float = 0.001
    risk_free_rate: float = 0.0  # annualized decimal
    annual_trading_days: int = 252

    def __post_init__(self) -> None:
        for key in ("initial_capital", "commission_rate", "slippage_rate", "risk_free_rate"):
            if not math.isfinite(getattr(self, key)):
                raise ValueError(f"{key} must be finite")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not 0 <= self.commission_rate < 1 or not 0 <= self.slippage_rate < 1:
            raise ValueError("commission_rate and slippage_rate must be in [0, 1)")
        if self.annual_trading_days < 1:
            raise ValueError("annual_trading_days must be >= 1")

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass
class BacktestResult:
    daily: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    orders: pd.DataFrame
    metrics: dict[str, float | None]
    warnings: list[str]
    metadata: dict
    config: BacktestConfig
    signals: pd.DataFrame = field(default_factory=pd.DataFrame)
    artifact_dir: str | None = field(default=None)
