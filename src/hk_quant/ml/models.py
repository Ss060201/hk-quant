"""One fixed adverse outcome, with provenance and honest missing-data status."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

LABEL = "raw_close_return_20_trading_days_below_minus_5pct"
HORIZON_TRADING_DAYS = 20
LOSS_THRESHOLD = -0.05


@dataclass
class ConditionalDataset:
    samples: pd.DataFrame
    feature_columns: tuple[str, ...]
    strategy_id: str
    strategy_version: str
    data_version: str | None
    feature_source: str
    discarded: dict[str, int]
    warnings: list[str] = field(default_factory=list)
    label_definition: str = LABEL


@dataclass
class ConditionalModelResult:
    status: str  # EVALUATED, BLOCKED
    strategy_id: str
    strategy_version: str
    data_version: str | None
    feature_columns: tuple[str, ...]
    model_version: str | None
    model_config: dict[str, Any]
    label_definition: str
    split_config: dict[str, Any]
    fold_metrics: list[dict[str, Any]]
    predictions: pd.DataFrame
    strategy_comparison: dict[str, Any] | None
    warnings: list[str]
    experiment_id: str | None = None

    @property
    def comparison_status(self) -> str:
        return "EVALUATED" if self.strategy_comparison is not None else "BLOCKED"
