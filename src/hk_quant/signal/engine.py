"""Signal Engine.

Applies a validated :class:`StrategyDefinition` to one day's data and returns
deterministic ``BUY / SELL / HOLD`` signals (or an explicit status when data
is missing / out of universe). It never ranks, weights, or executes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence, Union

import pandas as pd

from hk_quant.data.provenance import make_data_version
from hk_quant.data.universe import UniverseDataUnavailableError
from hk_quant.factors import FactorEngine
from hk_quant.signal.evaluator import (
    EvaluationResult,
    collect_conditions,
    evaluate_condition_group,
)
from hk_quant.signal.models import ConditionResult, Signal, SignalStatus, SignalType
from hk_quant.signal.state import PositionState
from hk_quant.strategy.models import (
    StrategyDefinition,
    UniverseType,
    compute_strategy_hash,
)

PathLike = Union[str, os.PathLike[str]]


class SignalDataError(Exception):
    """Raised when required data / universe cannot be provided."""


def generate_signal(
    strategy: StrategyDefinition,
    signal_date: object,
    stock_id: str,
    state: PositionState | None = None,
    repository: Any | None = None,
    factor_engine: FactorEngine | None = None,
    data_version: str | None = None,
) -> Signal:
    """Generate one signal for one stock on one day."""
    if repository is None:
        raise ValueError("repository is required")
    factor_engine = factor_engine or FactorEngine(repository)
    data_version = data_version or make_data_version("HK_DAILY")
    strategy_hash = strategy.strategy_hash or compute_strategy_hash(strategy)
    signal_date_str = pd.Timestamp(signal_date).date().isoformat()

    warnings: list[str] = []
    if strategy.universe.type == UniverseType.OBSERVED_PRICE.value:
        warnings.append(
            "historical listing/delisting data unavailable; "
            "universe may contain survivorship bias"
        )

    base = dict(
        strategy_id=strategy.strategy_id,
        strategy_version=strategy.version,
        strategy_hash=strategy_hash,
        stock_id=stock_id,
        signal_date=signal_date_str,
        data_version=data_version,
        factor_versions={},
        warnings=warnings,
    )

    if not _in_universe(strategy, repository, signal_date, stock_id):
        return Signal(
            **base,
            signal=None,
            status=SignalStatus.OUT_OF_UNIVERSE,
            reason={"universe": strategy.universe.type},
        )

    values, factor_versions = _load_feature_values(
        strategy, repository, factor_engine, signal_date, stock_id
    )
    base["factor_versions"] = factor_versions

    entry_eval = evaluate_condition_group(strategy.entry, values)
    reason: dict[str, Any] = {
        "entry": _eval_to_dict(entry_eval),
    }

    has_position = state is not None and state.stock_id == stock_id

    if not has_position:
        if not entry_eval.available:
            return Signal(
                **base,
                signal=None,
                status=SignalStatus.DATA_UNAVAILABLE,
                reason=reason,
            )
        return Signal(
            **base,
            signal=SignalType.BUY.value if entry_eval.passed else SignalType.HOLD.value,
            status=SignalStatus.VALID,
            reason=reason,
        )

    # Position exists -> check exit rules.
    exit_eval: EvaluationResult | None = None
    if strategy.exit is not None and strategy.exit.conditions is not None:
        exit_eval = evaluate_condition_group(strategy.exit.conditions, values)
        reason["exit"] = _eval_to_dict(exit_eval)
        if not exit_eval.available:
            return Signal(
                **base,
                signal=None,
                status=SignalStatus.DATA_UNAVAILABLE,
                reason=reason,
            )

    days_held = _trading_days_held(repository, state.entry_date, signal_date_str)
    reason["holding_period"] = {
        "entry_date": state.entry_date,
        "trading_days_held": days_held,
        "required": strategy.holding_period.value,
    }

    sell = False
    if exit_eval is not None and exit_eval.passed:
        sell = True
    elif days_held >= strategy.holding_period.value:
        sell = True

    return Signal(
        **base,
        signal=SignalType.SELL.value if sell else SignalType.HOLD.value,
        status=SignalStatus.VALID,
        reason=reason,
    )


def generate_signals(
    strategy: StrategyDefinition,
    signal_date: object,
    universe: Sequence[str] | None = None,
    state: dict[str, PositionState] | None = None,
    repository: Any | None = None,
    factor_engine: FactorEngine | None = None,
    data_version: str | None = None,
) -> list[Signal]:
    """Generate signals for every stock in the universe on one day."""
    if repository is None:
        raise ValueError("repository is required")

    stock_ids = _resolve_universe(strategy, repository, signal_date, universe)
    state = state or {}
    factor_engine = factor_engine or FactorEngine(repository)

    return [
        generate_signal(
            strategy,
            signal_date,
            stock_id,
            state=state.get(stock_id),
            repository=repository,
            factor_engine=factor_engine,
            data_version=data_version,
        )
        for stock_id in stock_ids
    ]


def _resolve_universe(
    strategy: StrategyDefinition,
    repository: Any,
    signal_date: object,
    universe: Sequence[str] | None,
) -> list[str]:
    if universe is not None:
        return list(dict.fromkeys(universe))

    if strategy.universe.type == UniverseType.OBSERVED_PRICE.value:
        df = repository.get_daily_prices(
            start_date=pd.Timestamp(signal_date).date().isoformat(),
            end_date=pd.Timestamp(signal_date).date().isoformat(),
        )
        return sorted(df["stock_id"].astype(str).unique().tolist())

    if strategy.universe.type == UniverseType.HISTORICAL.value:
        try:
            universe_df = repository.get_universe(signal_date)
        except UniverseDataUnavailableError as exc:
            raise SignalDataError(
                "historical_universe unavailable from the current data provider"
            ) from exc
        return sorted(universe_df["stock_id"].astype(str).tolist())

    raise SignalDataError(f"unknown universe type: {strategy.universe.type!r}")


def _in_universe(
    strategy: StrategyDefinition,
    repository: Any,
    signal_date: object,
    stock_id: str,
) -> bool:
    if strategy.universe.type == UniverseType.HISTORICAL.value:
        universe_df = repository.get_universe(signal_date)
        return stock_id in set(universe_df["stock_id"].astype(str))

    # observed universe: stock is in universe if it has a price row on the day
    row = repository.get_daily_prices(
        stock_ids=[stock_id],
        start_date=pd.Timestamp(signal_date).date().isoformat(),
        end_date=pd.Timestamp(signal_date).date().isoformat(),
    )
    return not row.empty


def _load_feature_values(
    strategy: StrategyDefinition,
    repository: Any,
    factor_engine: FactorEngine,
    signal_date: object,
    stock_id: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    conditions: list[Any] = list(collect_conditions(strategy.entry))
    if strategy.exit is not None and strategy.exit.conditions is not None:
        conditions.extend(collect_conditions(strategy.exit.conditions))

    data_fields = {c.field for c in conditions if c.source == "data"}
    factor_fields = {c.field for c in conditions if c.source == "factor"}

    values: dict[str, Any] = {}
    factor_versions: dict[str, str] = {}

    if data_fields:
        row = repository.get_prices(
            stock_ids=[stock_id],
            start_date=pd.Timestamp(signal_date).date().isoformat(),
            end_date=pd.Timestamp(signal_date).date().isoformat(),
            adjusted=strategy.price.adjusted,
        )
        for field in data_fields:
            if row.empty or field not in row.columns:
                values[field] = None
            else:
                raw_value = row.iloc[0][field]
                values[field] = None if pd.isna(raw_value) else float(raw_value)

    for field in factor_fields:
        from hk_quant.factors import get_factor

        definition = get_factor(field)
        factor_versions[field] = definition.version
        result = factor_engine.calculate(
            field,
            signal_date,
            stock_ids=[stock_id],
            adjusted=strategy.price.adjusted,
        )
        if result.empty or pd.isna(result.iloc[0]["value"]):
            values[field] = None
        else:
            values[field] = float(result.iloc[0]["value"])

    return values, factor_versions


def _trading_days_held(
    repository: Any, entry_date: object, signal_date: object
) -> int:
    calendar = repository.get_calendar()
    days = calendar.get_trading_days(entry_date, signal_date)
    return max(0, len(days) - 1)  # exclude the entry day itself


def _eval_to_dict(evaluation: EvaluationResult) -> dict[str, Any]:
    return {
        "passed": evaluation.passed,
        "available": evaluation.available,
        "condition_results": [result.to_dict() for result in evaluation.condition_results],
    }


def signals_to_dataframe(signals: Sequence[Signal]) -> pd.DataFrame:
    rows = []
    for signal in signals:
        rows.append(
            {
                "signal_date": signal.signal_date,
                "stock_id": signal.stock_id,
                "signal": signal.signal,
                "status": signal.status.value,
                "strategy_id": signal.strategy_id,
                "strategy_version": signal.strategy_version,
                "strategy_hash": signal.strategy_hash,
                "data_version": signal.data_version,
                "factor_versions": json.dumps(signal.factor_versions, sort_keys=True),
                "reason": json.dumps(signal.reason, sort_keys=True, ensure_ascii=False),
                "warnings": json.dumps(signal.warnings, ensure_ascii=False),
            }
        )
    return pd.DataFrame(rows)


def save_signals(signals: Sequence[Signal], output_dir: PathLike) -> Path:
    """Save batch signals as ``signals.parquet`` + ``metadata.json``."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    df = signals_to_dataframe(signals)
    df.to_parquet(root / "signals.parquet", index=False)

    if signals:
        first = signals[0]
        metadata = {
            "strategy_id": first.strategy_id,
            "strategy_version": first.strategy_version,
            "strategy_hash": first.strategy_hash,
            "signal_date": first.signal_date,
            "data_version": first.data_version,
            "factor_versions": first.factor_versions,
            "universe": None,
            "warnings": first.warnings,
            "count": len(signals),
        }
    else:
        metadata = {"count": 0}
    (root / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return root
