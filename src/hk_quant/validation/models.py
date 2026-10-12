"""Fixed-strategy validation results; no parameter search or alpha claims."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any

from hk_quant.validation.splits import TemporalSplit, WalkForwardFold


@dataclass(frozen=True)
class ValidationConfig:
    train_fraction: float = 0.6
    validation_fraction: float = 0.2
    label_horizon_days: int = 0
    embargo_days: int = 0
    reveal_final_test: bool = False
    walk_min_train_days: int | None = None
    walk_evaluation_days: int | None = None
    walk_step_days: int | None = None
    cost_multiplier: float = 2.0
    min_diagnostic_sessions: int = 3

    def __post_init__(self) -> None:
        if self.label_horizon_days < 0 or self.embargo_days < 0:
            raise ValueError("label horizon and embargo must be nonnegative")
        if self.cost_multiplier < 1:
            raise ValueError("cost_multiplier must be >= 1")
        if self.min_diagnostic_sessions < 2:
            raise ValueError("min_diagnostic_sessions must be >= 2")
        if (self.walk_min_train_days is None) != (self.walk_evaluation_days is None):
            raise ValueError("walk_min_train_days and walk_evaluation_days must be provided together")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    strategy_id: str
    strategy_version: str
    strategy_hash: str
    split: TemporalSplit
    config: dict[str, Any]
    periods: dict[str, dict[str, Any]]
    walk_forward: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    robustness: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    experiment_id: str | None = None
    final_test_viewed: bool = False
    test_previously_exposed: bool = False
    data_version: str = "unavailable"
    baseline_name: str = "equal_weight_buy_and_hold"

    def to_dict(self) -> dict[str, Any]:
        return _json_safe({
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_hash": self.strategy_hash,
            "split": self.split.to_dict(),
            "config": self.config,
            "periods": self.periods,
            "walk_forward": self.walk_forward,
            "diagnostics": self.diagnostics,
            "robustness": self.robustness,
            "warnings": self.warnings,
            "experiment_id": self.experiment_id,
            "final_test_viewed": self.final_test_viewed,
            "test_previously_exposed": self.test_previously_exposed,
            "data_version": self.data_version,
            "baseline_name": self.baseline_name,
            "status": "EXPLORATORY",
        })


def _json_safe(value: Any) -> Any:
    """Represent missing/nonfinite statistics explicitly in immutable JSON."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
