"""Fixed-strategy close signal -> next trading day raw-open simulation."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from hk_quant.backtest.execution import fill_order, raw_open_or_rejection
from hk_quant.backtest.models import BacktestConfig, BacktestResult
from hk_quant.backtest.performance import compute_performance
from hk_quant.factors import FactorEngine
from hk_quant.portfolio import Portfolio, equal_weight_targets
from hk_quant.signal import PositionState, SignalStatus, generate_signals
from hk_quant.strategy.models import StrategyDefinition, UniverseType, compute_strategy_hash
from hk_quant.strategy.validators import validate_strategy


def _date(value: object) -> date:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"invalid date: {value!r}")
    return timestamp.date()


def _valid_mark(value: Any) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (ValueError, TypeError):
        return False


def run_backtest(
    strategy: StrategyDefinition,
    start_date: object,
    end_date: object,
    repository: Any,
    config: BacktestConfig | None = None,
    *,
    universe: Sequence[str] | None = None,
    output_dir: str | Path | None = None,
) -> BacktestResult:
    """Run a single fixed Strategy with no parameter search.

    Each day's close signal creates an order for the calendar's *next* trading
    day open. Fills query raw provider prices, irrespective of the strategy's
    adjusted/point-in-time research price setting. No broker calls occur.
    """
    if repository is None:
        raise ValueError("repository is required")
    config = config or BacktestConfig()
    start, end = _date(start_date), _date(end_date)
    if start > end:
        raise ValueError("start_date must be <= end_date")
    validate_strategy(strategy, repository)
    calendar = repository.get_calendar()
    days = calendar.get_trading_days(start, end)
    if not days:
        raise ValueError("no calendar trading days within the requested range")
    if universe is not None and (not universe or len(universe) != len(set(universe))):
        raise ValueError("explicit universe must be nonempty with unique stock IDs")

    # Price panel is used only at/after the current simulated date, never to
    # create feature values. generate_signals queries the repository as of T.
    raw = repository.get_daily_prices(start_date=start.isoformat(), end_date=end.isoformat())
    day_rows: dict[date, dict[str, dict]] = defaultdict(dict)
    for row in raw.to_dict("records"):
        day = _date(row["trade_date"])
        stock_id = str(row["stock_id"])
        if stock_id in day_rows[day]:
            raise ValueError(f"duplicate raw prices for {stock_id} on {day}")
        day_rows[day][stock_id] = row

    version_getter = getattr(repository, "get_data_version", None)
    data_version = version_getter() if callable(version_getter) else None
    if not data_version:
        data_version = None
    if data_version is not None:
        data_version = str(data_version)
    warnings = [
        "Execution assumes whole-share fills at raw next-session Open; board lots, "
        "partial fills, liquidity depth, market taxes and FX are not modeled.",
        "Calendar provenance is not verified as official HKEX calendar.",
    ]
    if data_version is None:
        warnings.append("Content-derived data version unavailable; date labels do not establish reproducibility.")
    if strategy.universe.type == UniverseType.OBSERVED_PRICE.value:
        warnings.append("Observed price universe may suffer survivorship bias; result is EXPLORATORY.")
    actions_getter = getattr(repository, "get_corporate_actions", None)
    if callable(actions_getter):
        actions = actions_getter()
        if not actions.empty and "event_date" in actions:
            events = pd.to_datetime(actions["event_date"], errors="coerce").dt.date
            if events.between(start, end).any():
                warnings.append(
                    "Corporate actions occur in the sample; split share changes, dividends "
                    "and rights cash flows are not modeled, so equity may be inaccurate."
                )

    portfolio = Portfolio(config.initial_capital)
    last_marks: dict[str, float] = {}
    pending: dict[date, list[dict]] = defaultdict(list)
    orders: list[dict] = []
    trades: list[dict] = []
    positions: list[dict] = []
    daily: list[dict] = []
    signal_rows: list[dict] = []
    factor_versions: dict[str, str] = {}
    factor_engine = FactorEngine(repository)
    previous_equity = config.initial_capital

    for index, day in enumerate(days):
        day_str = day.isoformat()
        row_map = day_rows.get(day, {})
        due = pending.pop(day, [])
        executed_today: list[dict] = []

        # SELLs release cash before BUYs, while failed SELLs leave positions
        # intact and keep them in the equal-weight denominator.
        for order in sorted((o for o in due if o["side"] == "SELL"), key=lambda o: o["stock_id"]):
            raw_open, error = raw_open_or_rejection(row_map.get(order["stock_id"]))
            if error:
                order.update(status="REJECTED", reason=error)
                continue
            trade = fill_order(order, raw_open, portfolio, config)
            if trade:
                executed_today.append(trade)
                trades.append(trade)

        buys = sorted((o for o in due if o["side"] == "BUY"), key=lambda o: o["stock_id"])
        weights = equal_weight_targets(portfolio.positions, (o["stock_id"] for o in buys))
        open_equity = portfolio.cash
        for stock_id, position in portfolio.positions.items():
            raw_open, _ = raw_open_or_rejection(row_map.get(stock_id))
            known_mark = raw_open if raw_open is not None else last_marks.get(stock_id, position.cost_basis)
            open_equity += position.quantity * known_mark
        for order in buys:
            stock_id = order["stock_id"]
            order["target_weight"] = weights[stock_id]
            raw_open, error = raw_open_or_rejection(row_map.get(stock_id))
            if error:
                order.update(status="REJECTED", reason=error)
                continue
            existing = portfolio.positions.get(stock_id)
            if existing and existing.quantity * raw_open >= open_equity * weights[stock_id]:
                order.update(status="SKIPPED", reason="TARGET_ALREADY_MET")
                continue
            trade = fill_order(
                order, raw_open, portfolio, config,
                target_value=open_equity * weights[stock_id],
            )
            if trade:
                executed_today.append(trade)
                trades.append(trade)
                last_marks[stock_id] = raw_open

        positions_value = 0.0
        unrealized_pnl = 0.0
        stale = 0
        for stock_id, position in sorted(portfolio.positions.items()):
            row = row_map.get(stock_id)
            close = row.get("close") if row is not None else None
            if _valid_mark(close):
                mark = float(close)
                last_marks[stock_id] = mark
                mark_status = "CLOSE"
            else:
                mark = last_marks.get(stock_id, position.cost_basis)
                stale += 1
                mark_status = "STALE_LAST_KNOWN"
                warnings.append(f"{day_str} {stock_id}: no valid raw Close; carrying previous known mark.")
            market_value = position.quantity * mark
            pnl = market_value - position.cost_basis * position.quantity
            positions_value += market_value
            unrealized_pnl += pnl
            positions.append({
                "trade_date": day_str, "stock_id": stock_id,
                "quantity": position.quantity, "entry_date": position.entry_date,
                "cost_basis": position.cost_basis, "raw_close_or_mark": mark,
                "mark_status": mark_status, "market_value": market_value,
                "unrealized_pnl": pnl,
            })
        equity = portfolio.cash + positions_value
        if portfolio.cash < -1e-8:
            raise AssertionError("portfolio cash became negative")
        day_turnover = sum(t["notional"] for t in executed_today) / previous_equity
        daily.append({
            "trade_date": day_str,
            "cash": portfolio.cash, "positions_value": positions_value,
            "equity": equity, "realized_pnl": portfolio.realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "daily_return": equity / previous_equity - 1.0,
            "turnover": day_turnover, "stale_position_count": stale,
            "valuation_status": "STALE" if stale else "COMPLETE",
        })
        previous_equity = equity

        state = {
            stock_id: PositionState(stock_id, p.entry_date, strategy.strategy_id, strategy.version)
            for stock_id, p in portfolio.positions.items()
        }
        observed = set(row_map)
        todays_universe = (
            sorted(set(universe) | set(state)) if universe is not None
            else sorted(observed | set(state)) if strategy.universe.type == UniverseType.OBSERVED_PRICE.value
            else None
        )
        signals = generate_signals(
            strategy, day_str, universe=todays_universe, state=state,
            repository=repository, factor_engine=factor_engine,
            data_version=data_version,
        )
        for signal in signals:
            row = signal.to_dict()
            # Parquet cannot store nested dict/list columns; serialize them.
            row["reason"] = json.dumps(row["reason"], sort_keys=True, ensure_ascii=False)
            row["factor_versions"] = json.dumps(row["factor_versions"], sort_keys=True)
            row["warnings"] = json.dumps(row["warnings"], ensure_ascii=False)
            signal_rows.append(row)
            factor_versions.update(signal.factor_versions)
            if signal.status != SignalStatus.VALID or signal.signal not in ("BUY", "SELL"):
                continue
            execution_day = days[index + 1].isoformat() if index + 1 < len(days) else None
            order = {
                "order_id": f"sim-{len(orders) + 1:06d}",
                "signal_date": day_str, "execution_date": execution_day,
                "stock_id": signal.stock_id, "side": signal.signal,
                "target_weight": None, "quantity": 0,
                "status": "PENDING" if execution_day else "REJECTED",
                "reason": None if execution_day else "NO_NEXT_SESSION_WITHIN_RANGE",
            }
            orders.append(order)
            if execution_day:
                pending[days[index + 1]].append(order)

    daily_frame = pd.DataFrame(daily)
    daily_frame["drawdown"] = daily_frame["equity"] / daily_frame["equity"].cummax().clip(lower=config.initial_capital) - 1.0
    trades_frame = pd.DataFrame(trades, columns=[
        "signal_date", "execution_date", "stock_id", "side", "quantity", "raw_open",
        "execution_price", "notional", "commission", "slippage_cost", "realized_pnl", "cash_after",
    ])
    positions_frame = pd.DataFrame(positions, columns=[
        "trade_date", "stock_id", "quantity", "entry_date", "cost_basis",
        "raw_close_or_mark", "mark_status", "market_value", "unrealized_pnl",
    ])
    orders_frame = pd.DataFrame(orders, columns=[
        "order_id", "signal_date", "execution_date", "stock_id", "side",
        "target_weight", "quantity", "status", "reason",
    ])
    if not orders_frame.empty and (orders_frame["status"] == "PENDING").any():
        raise AssertionError("unfinished pending simulated orders")
    if not orders_frame.empty and (orders_frame["status"] == "REJECTED").any():
        warnings.append("One or more simulated orders were rejected; consult orders artifact for reasons.")
    if (daily_frame["valuation_status"] == "STALE").any():
        warnings.append("Some daily equity marks are carried forward; performance statistics are exploratory.")
    metadata = {
        "strategy_id": strategy.strategy_id,
        "strategy_version": strategy.version,
        "strategy_hash": strategy.strategy_hash or compute_strategy_hash(strategy),
        "data_version": data_version,
        "factor_versions": factor_versions,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "universe": strategy.universe.type,
        "explicit_universe": list(universe) if universe is not None else None,
        "status": "EXPLORATORY",
        "execution": "T close signal, earliest T+1 trading-session raw Open",
        "valuation": "raw Close; stale last known mark if missing",
        "assumptions": {
            "construction": "equal-weight new BUY targets; existing HOLD never sold on rebalance",
            "fill": "whole shares, all-or-nothing order; no market partial fill",
            "corporate_actions": "not applied to portfolio cash/shares",
            "currency": "single currency; no FX conversion",
            **config.to_dict(),
        },
    }
    result = BacktestResult(
        daily=daily_frame, trades=trades_frame, positions=positions_frame,
        orders=orders_frame,
        metrics=compute_performance(daily_frame, trades_frame, config),
        warnings=list(dict.fromkeys(warnings)), metadata=metadata, config=config,
    )
    result.signals = pd.DataFrame(signal_rows, columns=[
        "strategy_id", "strategy_version", "strategy_hash", "stock_id", "signal_date",
        "signal", "status", "reason", "data_version", "factor_versions", "warnings",
    ])
    if output_dir is not None:
        from hk_quant.backtest.results import save_backtest
        save_backtest(result, output_dir)
    return result
