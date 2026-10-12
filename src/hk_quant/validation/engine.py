"""Compare an unchanged strategy against a cost-matched simple baseline.

The train window is reserved for defining the strategy before this function is
called. Neither thresholds nor strategy versions are fitted here. Final test
results are withheld by default; revealing them marks that period exposed.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from hk_quant.strategy.models import (
    Condition, ConditionGroup, HoldingPeriod, PriceDefinition,
    StrategyDefinition, UniverseSpec, compute_strategy_hash,
)
from hk_quant.validation.models import ValidationConfig, ValidationResult
from hk_quant.validation.splits import DateWindow, temporal_split, walk_forward_folds


_COMPARISON_KEYS = (
    "total_return", "cagr", "sharpe", "max_drawdown", "turnover",
    "transaction_costs",
)


def equal_weight_buy_and_hold(strategy: StrategyDefinition, sessions: int) -> StrategyDefinition:
    """Fixed baseline: buy eligible names on T+1 Open and hold.

    The observed universe may expand over time and is *not* a historical
    listing universe. The baseline has the same universe and execution costs
    as the candidate, and therefore inherits the same universe caveat.
    """
    baseline = StrategyDefinition(
        strategy_id="baseline_equal_weight_buy_and_hold",
        name="Equal-weight universe buy-and-hold",
        version="1.0.0",
        universe=UniverseSpec(type=strategy.universe.type),
        entry=ConditionGroup(logic="all", conditions=[
            Condition(source="data", field="close", operator=">", value=0.0),
        ]),
        holding_period=HoldingPeriod(value=sessions + 1),
        exit=None,
        price=PriceDefinition(adjusted=False),
        description="Fixed positive-close buy and hold; execute at next raw open",
    )
    baseline.strategy_hash = compute_strategy_hash(baseline)
    return baseline


def _window_metrics(result: Any, window: DateWindow, backtest_config: Any) -> dict[str, float | None]:
    """Rebase period to equity immediately preceding the first visible day."""
    from hk_quant.backtest.performance import compute_performance

    daily = result.daily.copy()
    if daily.empty or not {"trade_date", "equity", "daily_return"}.issubset(daily):
        raise ValueError("backtest result must provide trade_date, equity and daily_return")
    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
    daily = daily.sort_values("trade_date")
    start, end = pd.Timestamp(window.start), pd.Timestamp(window.end)
    selected = daily[daily["trade_date"].between(start, end)].copy()
    if selected.empty:
        return {key: None for key in _COMPARISON_KEYS}

    before = daily[daily["trade_date"] < selected.iloc[0]["trade_date"]]
    initial = float(before.iloc[-1]["equity"]) if not before.empty else float(backtest_config.initial_capital)
    if initial <= 0:
        raise ValueError("period initial equity must be positive")

    trades = result.trades.copy()
    if not trades.empty:
        if "execution_date" not in trades:
            raise ValueError("backtest trades require execution_date")
        dates = pd.to_datetime(trades["execution_date"])
        trades = trades.loc[dates.between(start, end)].copy()
    period_cfg = replace(backtest_config, initial_capital=initial)
    metrics = compute_performance(selected, trades, period_cfg)
    if trades.empty:
        costs = 0.0
    elif {"commission", "slippage_cost"}.issubset(trades):
        costs = float(trades["commission"].sum() + trades["slippage_cost"].sum())
    else:
        costs = None
    return {**metrics, "transaction_costs": costs}


def _comparison(candidate: dict, baseline: dict) -> dict:
    return {
        key: (
            float(candidate[key]) - float(baseline[key])
            if candidate.get(key) is not None and baseline.get(key) is not None
            and np.isfinite(candidate[key]) and np.isfinite(baseline[key])
            else None
        )
        for key in _COMPARISON_KEYS
    }


def _period(candidate: Any, baseline: Any, window: DateWindow, backtest_config: Any) -> dict:
    main = _window_metrics(candidate, window, backtest_config)
    control = _window_metrics(baseline, window, backtest_config)
    return {
        "window": window.to_dict(),
        "strategy": main,
        "baseline": control,
        "strategy_minus_baseline": _comparison(main, control),
    }


def _diagnostics(result: Any, window: DateWindow, min_sessions: int) -> dict:
    daily = result.daily.copy()
    days = pd.to_datetime(daily["trade_date"])
    daily = daily[days.between(pd.Timestamp(window.start), pd.Timestamp(window.end))].copy()
    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
    bucketed: dict[str, list[dict]] = {}
    for label, periods in (
        ("year", daily["trade_date"].dt.to_period("Y")),
        ("month", daily["trade_date"].dt.to_period("M")),
    ):
        rows = []
        for key, group in daily.groupby(periods, sort=True):
            returns = pd.to_numeric(group["daily_return"], errors="coerce").dropna()
            rows.append({
                "period": str(key), "sample_count": int(len(returns)),
                "total_return": float(np.prod(1 + returns) - 1)
                if len(returns) >= min_sessions else None,
                "status": "AVAILABLE" if len(returns) >= min_sessions else "UNAVAILABLE_SMALL_SAMPLE",
            })
        bucketed[label] = rows
    for category in ("market_cap", "liquidity", "sector", "market_regime", "volatility"):
        bucketed[category] = {
            "status": "UNAVAILABLE", "reason": "no verified point-in-time classification supplied",
        }
    return bucketed


def _register(result: ValidationResult, registry: Any, backtest_config: Any, strategy: Any) -> None:
    record = registry.create_experiment(
        experiment_type="validation", config=result.config,
        research_question="Does this fixed strategy outperform an equal-weight buy-and-hold baseline?",
        strategy_id=result.strategy_id, strategy_version=result.strategy_version,
        strategy_hash=result.strategy_hash, data_version=result.data_version,
        date_range=result.split.to_dict(),
        universe={"mode": strategy.universe.type},
        cost_assumptions=asdict(backtest_config), warnings=result.warnings,
    )
    result.experiment_id = record.experiment_id
    registry.save_artifact(record.experiment_id, "summary.json", result.to_dict())
    registry.update_experiment_status(
        record.experiment_id, "COMPLETED",
        conclusion="EXPLORATORY: fixed strategy compared to matched simple baseline",
    )


def _test_previously_exposed(registry: Any, window: DateWindow) -> bool:
    """Check retained validation history across strategy versions."""
    for prior in registry.list_experiments(experiment_type="validation", limit=100000):
        previous_window = prior.date_range.get("test")
        cfg = prior.config.get("validation", {})
        # Also accept the earliest nested validation config, if present.
        if "validation" in cfg:
            cfg = cfg["validation"]
        if not isinstance(previous_window, dict) or not cfg.get("reveal_final_test"):
            continue
        if (previous_window.get("start", "9999") <= window.end.isoformat()
                and previous_window.get("end", "0000") >= window.start.isoformat()):
            return True
    return False


def run_validation(
    strategy: StrategyDefinition,
    start_date: object,
    end_date: object,
    repository: Any,
    *,
    backtest_config: Any = None,
    config: ValidationConfig | None = None,
    universe: Sequence[str] | None = None,
    baseline_strategy: StrategyDefinition | None = None,
    ablation_strategies: Sequence[StrategyDefinition] = (),
    registry: Any = None,
    backtest_runner: Callable[..., Any] | None = None,
) -> ValidationResult:
    """Validate only explicitly supplied strategy variants on time slices.

    An OOS period is evaluated using the continuous prior portfolio run so
    carried positions persist. Its first daily return includes performance
    since the preceding session, which is reported as a limitation.
    """
    if config is None:
        config = ValidationConfig()
    if backtest_config is None:
        from hk_quant.backtest.models import BacktestConfig
        backtest_config = BacktestConfig()
    if backtest_runner is None:
        from hk_quant.backtest.engine import run_backtest
        backtest_runner = run_backtest
    if pd.Timestamp(start_date) > pd.Timestamp(end_date):
        raise ValueError("start_date must not follow end_date")
    dates = repository.get_calendar().get_trading_days(start_date, end_date)
    split = temporal_split(
        dates, train_fraction=config.train_fraction,
        validation_fraction=config.validation_fraction,
        label_horizon_days=config.label_horizon_days,
        embargo_days=config.embargo_days,
    )
    # The final test is never even passed to the backtest engine unless the
    # caller expressly reveals it. No optimization happens in this function.
    visible_end = split.test.end if config.reveal_final_test else split.validation.end
    kwargs = {"config": backtest_config, "universe": universe}
    candidate = backtest_runner(strategy, split.train.start, visible_end, repository, **kwargs)
    baseline_definition = baseline_strategy or equal_weight_buy_and_hold(strategy, len(dates))
    baseline = backtest_runner(baseline_definition, split.train.start, visible_end, repository, **kwargs)
    periods = {
        "train": _period(candidate, baseline, split.train, backtest_config),
        "validation": _period(candidate, baseline, split.validation, backtest_config),
    }
    if config.reveal_final_test:
        periods["test"] = _period(candidate, baseline, split.test, backtest_config)

    previously_exposed = _test_previously_exposed(registry, split.test) if registry is not None else False
    warnings = list(dict.fromkeys([*candidate.warnings, *baseline.warnings]))
    warnings += [
        "Exploratory comparison only: fixed rules; no statistical proof of alpha.",
        "Subperiod returns include positions carried across split boundaries; never refit on later data.",
        "Baseline uses the same observed universe and costs; observed dates are not a historical listing universe.",
    ]
    if config.reveal_final_test:
        warnings.append(
            "Final test was viewed: subsequent strategy changes invalidate its untouched status; reserve new dates."
        )
    else:
        warnings.append("Final test withheld; set reveal_final_test=True once after fixing strategy and assumptions.")
    if previously_exposed:
        warnings.append(
            "These final-test dates overlap previously viewed validation test dates; "
            "a changed strategy cannot call this an untouched independent test."
        )
    elif registry is None:
        warnings.append(
            "No experiment registry supplied: prior final-test exposure across runs cannot be checked."
        )
    if config.label_horizon_days:
        warnings.append("Purge applies to labelled research samples; portfolio holdings can span split boundaries.")

    fold_results: list[dict] = []
    if config.walk_min_train_days is not None:
        folds = walk_forward_folds(
            [d for d in dates if d <= visible_end],
            min_train_days=config.walk_min_train_days,
            evaluation_days=config.walk_evaluation_days,
            step_days=config.walk_step_days,
            label_horizon_days=config.label_horizon_days,
            embargo_days=config.embargo_days,
        )
        for fold in folds:
            fold_results.append({
                **fold.to_dict(),
                **_period(candidate, baseline, fold.evaluation, backtest_config),
                "strategy_unchanged": True,
            })

    # Robustness perturbs execution costs, not strategy thresholds or test
    # selection. A zero-cost base adds explicit 10bp rates as an alternative.
    higher = replace(
        backtest_config,
        commission_rate=(backtest_config.commission_rate * config.cost_multiplier
                         if backtest_config.commission_rate else 0.001),
        slippage_rate=(backtest_config.slippage_rate * config.cost_multiplier
                       if backtest_config.slippage_rate else 0.001),
    )
    costly = backtest_runner(
        strategy, split.train.start, split.validation.end, repository,
        config=higher, universe=universe,
    )
    costly_metrics = _window_metrics(costly, split.validation, higher)
    standard = periods["validation"]["strategy"]
    robustness = {
        "higher_costs": {
            "commission_rate": higher.commission_rate,
            "slippage_rate": higher.slippage_rate,
            "validation_metrics": costly_metrics,
            "return_change": (
                costly_metrics["total_return"] - standard["total_return"]
                if costly_metrics["total_return"] is not None
                and standard["total_return"] is not None else None
            ),
        },
        "ablations": [],
        "missing_data": "UNAVAILABLE: requires a declared alternative dataset, no imputation performed",
        "holding_period": "UNAVAILABLE: strategy parameters are fixed; supply separately versioned ablation strategies",
    }
    for variant in ablation_strategies:
        if variant.strategy_hash == strategy.strategy_hash and variant.strategy_id == strategy.strategy_id:
            raise ValueError("ablation must be a distinct, explicitly versioned strategy")
        alternate = backtest_runner(
            variant, split.train.start, split.validation.end, repository, **kwargs,
        )
        metrics = _window_metrics(alternate, split.validation, backtest_config)
        robustness["ablations"].append({
            "strategy_id": variant.strategy_id, "version": variant.version,
            "strategy_hash": variant.strategy_hash or compute_strategy_hash(variant),
            "validation_metrics": metrics,
            "comparison_to_original": _comparison(metrics, standard),
        })

    result = ValidationResult(
        strategy_id=strategy.strategy_id, strategy_version=strategy.version,
        strategy_hash=strategy.strategy_hash or compute_strategy_hash(strategy),
        split=split,
        config={"validation": config.to_dict(), "backtest": asdict(backtest_config),
                "universe_override": list(universe) if universe is not None else None},
        periods=periods, walk_forward=fold_results,
        diagnostics=_diagnostics(candidate, split.validation, config.min_diagnostic_sessions),
        robustness=robustness, warnings=warnings,
        final_test_viewed=config.reveal_final_test,
        test_previously_exposed=previously_exposed,
        data_version=str(candidate.metadata.get("data_version") or "unavailable"),
    )
    if registry is not None:
        _register(result, registry, backtest_config, strategy)
    return result
