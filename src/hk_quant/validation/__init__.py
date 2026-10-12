"""Temporal validation of immutable strategies and exploratory research."""

from hk_quant.validation.engine import equal_weight_buy_and_hold, run_validation
from hk_quant.validation.models import ValidationConfig, ValidationResult
from hk_quant.validation.splits import (
    DateWindow,
    TemporalSplit,
    WalkForwardFold,
    purge_overlapping_labels,
    temporal_split,
    walk_forward_folds,
)

__all__ = [
    "DateWindow", "TemporalSplit", "WalkForwardFold", "ValidationConfig",
    "ValidationResult", "purge_overlapping_labels", "temporal_split", "walk_forward_folds",
    "equal_weight_buy_and_hold", "run_validation",
]
