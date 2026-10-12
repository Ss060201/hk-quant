"""Explicit provenance for historical risk statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class RiskResult:
    as_of_date: str
    data_version: str | None
    strategy_version: str | None
    parameters: dict[str, Any]
    stock_metrics: pd.DataFrame
    strategy_metrics: dict[str, Any]
    portfolio_metrics: dict[str, Any]
    correlations: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    strategy_id: str | None = None
    classification: str = "HISTORICAL_DESCRIPTIVE"
    experiment_id: str | None = None

    def summary(self) -> dict[str, Any]:
        stocks = self.stock_metrics.astype(object).where(pd.notna(self.stock_metrics), None)
        correlations = self.correlations.astype(object).where(pd.notna(self.correlations), None)
        return {
            "as_of_date": self.as_of_date,
            "data_version": self.data_version,
            "strategy_version": self.strategy_version,
            "strategy_id": self.strategy_id,
            "classification": self.classification,
            "parameters": self.parameters,
            "stock_metrics": stocks.to_dict(orient="records"),
            "strategy_metrics": self.strategy_metrics,
            "portfolio_metrics": self.portfolio_metrics,
            "correlations": correlations.to_dict(orient="records"),
            "warnings": self.warnings,
            "experiment_id": self.experiment_id,
        }
