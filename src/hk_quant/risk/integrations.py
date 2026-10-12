"""Thin adapters for existing backtests and the immutable experiment registry."""

from __future__ import annotations

from typing import Any

import pandas as pd

from hk_quant.risk.engine import analyze_risk
from hk_quant.risk.models import RiskResult


def analyze_backtest_risk(
    backtest: Any,
    stock_prices: pd.DataFrame,
    *,
    as_of_date: str | None = None,
    window: int = 252,
    attributes: pd.DataFrame | None = None,
    attribute_source: str | None = None,
) -> RiskResult:
    """Derive dated position weights from BacktestResult's ledger, no trades.

    Stock prices must be supplied from the same provenance as the backtest;
    this function never contacts a provider and cannot verify that claim.
    """
    if backtest.daily.empty:
        raise ValueError("backtest has no daily equity")
    last_date = pd.to_datetime(backtest.daily.trade_date).max()
    analysis_date = pd.Timestamp(as_of_date).normalize() if as_of_date else last_date.normalize()
    if analysis_date > last_date.normalize():
        raise ValueError("analysis date exceeds last backtest date")
    daily = backtest.daily.copy()
    positions = backtest.positions.copy()
    if not positions.empty:
        if not {"stock_id", "trade_date", "market_value"}.issubset(positions.columns):
            raise ValueError("backtest positions require stock_id, trade_date, market_value")
        positions = positions.merge(daily[["trade_date", "equity"]], on="trade_date", validate="many_to_one")
        if (positions.equity <= 0).any():
            raise ValueError("backtest equity must be positive")
        positions["weight"] = positions.market_value / positions.equity
    annualization = backtest.config.annual_trading_days
    result = analyze_risk(
        stock_prices, as_of_date=analysis_date.date().isoformat(),
        data_version=backtest.metadata.get("data_version"),
        strategy_version=backtest.metadata.get("strategy_version"),
        strategy_id=backtest.metadata.get("strategy_id"),
        portfolio_daily=daily, positions=positions,
        attributes=attributes, attribute_source=attribute_source,
        annualization=annualization, window=window,
        initial_equity=backtest.config.initial_capital,
    )
    if analysis_date == last_date.normalize():
        result.warnings.extend(backtest.warnings)
    else:
        result.warnings.append("Backtest-wide warnings omitted for an earlier as-of date; inspect the complete run separately.")
    if ("mark_status" in positions and
            (positions.loc[pd.to_datetime(positions.trade_date) <= analysis_date,
                           "mark_status"] == "STALE_LAST_KNOWN").any()):
        result.warnings.append("Some backtest positions used stale marks; historical equity risk may be distorted.")
    if backtest.metadata.get("status") != "VALIDATED":
        result.warnings.append("Underlying backtest is exploratory; risk metrics do not validate a strategy.")
    return result


def register_risk_result(result: RiskResult, registry: Any) -> Any:
    """Save risk summary as a new, immutable ExperimentRegistry run."""
    config = {"as_of_date": result.as_of_date, "parameters": result.parameters,
              "classification": result.classification}
    record = registry.create_experiment(
        "risk", config, strategy_id=result.strategy_id,
        strategy_version=result.strategy_version,
        data_version=result.data_version,
        date_range={"end": result.as_of_date}, warnings=result.warnings,
    )
    try:
        registry.update_experiment_status(record.experiment_id, "RUNNING")
        registry.save_artifact(record.experiment_id, "summary.json", result.summary())
        completed = registry.update_experiment_status(
            record.experiment_id, "COMPLETED", conclusion=result.classification)
        result.experiment_id = completed.experiment_id
        return completed
    except Exception:
        registry.update_experiment_status(record.experiment_id, "FAILED")
        raise
