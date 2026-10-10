"""Signal Engine: apply a Strategy to one day's data and produce signals."""

from hk_quant.signal.engine import (
    SignalDataError,
    generate_signal,
    generate_signals,
    save_signals,
    signals_to_dataframe,
)
from hk_quant.signal.evaluator import (
    EvaluationResult,
    evaluate_condition_group,
    evaluate_leaf,
)
from hk_quant.signal.models import (
    ConditionResult,
    Signal,
    SignalStatus,
    SignalType,
)
from hk_quant.signal.state import PositionState

__all__ = [
    "ConditionResult",
    "EvaluationResult",
    "PositionState",
    "Signal",
    "SignalDataError",
    "SignalStatus",
    "SignalType",
    "evaluate_condition_group",
    "evaluate_leaf",
    "generate_signal",
    "generate_signals",
    "save_signals",
    "signals_to_dataframe",
]
