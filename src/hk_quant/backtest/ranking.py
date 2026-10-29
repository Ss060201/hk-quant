"""In-memory ranking backtest: score -> rank -> top-N -> equal weight -> T+1 fills.

Unlike the fixed-threshold engine, the whole price panel and corporate actions
are loaded once and scored in memory, so a six-year run is fast. Signals use
only data up to the rebalance date (``<= T``); fills use the next session's raw
open, exactly like the existing engine.

Cash dividends are credited to equity on the ex-date for shares held entering
that day. Shares distributed in another issuer (``distribution_in_kind``) are
never valued here and are not silently treated as zero: callers surface them
through warnings/blocks.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from hk_quant.backtest.execution import fill_order, raw_open_or_rejection
from hk_quant.backtest.models import BacktestConfig
from hk_quant.backtest.performance import compute_performance
from hk_quant.data import models
from hk_quant.portfolio import Portfolio, equal_weight_targets
from hk_quant.selection import Scorer, momentum_scorer, rank_by_score, select_top_n


def _date(value: object) -> date:
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise ValueError(f"invalid date: {value!r}")
    return ts.date()


@dataclass
class RankingBacktestResult:
    daily: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    orders: pd.DataFrame
    dividends: pd.DataFrame
    decisions: pd.DataFrame
    metrics: dict[str, Any]
    metadata: dict[str, Any]
    config: BacktestConfig
    warnings: list[str] = field(default_factory=list)


def run_ranking_backtest(
    repository: Any,
    stock_ids: Sequence[str],
    start_date: object,
    end_date: object,
    *,
    scorer: Scorer | None = None,
    top_n: int = 2,
    rebalance_frequency: int = 20,
    config: BacktestConfig | None = None,
    output_dir: str | Path | None = None,
) -> RankingBacktestResult:
    """Run a ranking strategy over an explicit cohort.

    On every ``rebalance_frequency``-th trading day, stocks are scored with
    data ``<=`` that day, ranked, and the top ``top_n`` become equal-weight
    targets. Dropped holdings are sold and targets bought at the next trading
    day's raw open.
    """
    if repository is None:
        raise ValueError("repository is required")
    config = config or BacktestConfig()
    start, end = _date(start_date), _date(end_date)
    ids = list(dict.fromkeys(stock_ids))
    if len(ids) < 1:
        raise ValueError("ranking backtest requires at least one distinct stock ID")
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if rebalance_frequency <= 0:
        raise ValueError("rebalance_frequency must be positive")
    scorer = scorer or momentum_scorer(window=20)

    calendar = repository.get_calendar()
    days = calendar.get_trading_days(start, end)
    if not days:
        raise ValueError("no calendar trading days within the requested range")

    # Load full history up to ``end`` so early rebalance dates have lookback;
    # only ``[start, end]`` is ever used for fills/marks (the daily loop).
    panel = repository.get_daily_prices(end_date=end.isoformat(), stock_ids=ids)
    if panel.empty:
        raise ValueError("no processed daily prices for the requested cohort/range")
    panel_dates = pd.to_datetime(panel["trade_date"], errors="coerce")

    day_rows: dict[date, dict[str, dict]] = defaultdict(dict)
    for row in panel.to_dict("records"):
        day = _date(row["trade_date"])
        stock_id = str(row["stock_id"])
        if stock_id in day_rows[day]:
            raise ValueError(f"duplicate raw prices for {stock_id} on {day}")
        day_rows[day][stock_id] = row

    # Dividend ex-date map: total cash per share per (stock, ex-date).
    ex_dividends: dict[tuple[str, date], float] = defaultdict(float)
    actions_getter = getattr(repository, "get_corporate_actions", None)
    unmodeled_actions = False
    if callable(actions_getter):
        actions = actions_getter(stock_ids=ids)
        if not actions.empty and "event_date" in actions:
            sample_days = set(days)
            for _, action in actions.iterrows():
                event = pd.to_datetime(action["event_date"], errors="coerce")
                if pd.isna(event):
                    continue
                if action.get("action_type") == models.ACTION_DISTRIBUTION:
                    if event.date() in sample_days:
                        unmodeled_actions = True
                if (
                    action.get("action_type") == models.ACTION_DIVIDEND
                    and pd.notna(action.get("cash_amount"))
                ):
                    ex_dividends[(str(action["stock_id"]), event.date())] += float(
                        action["cash_amount"]
                    )

    version_getter = getattr(repository, "get_data_version", None)
    data_version = str(version_getter()) if callable(version_getter) else None

    portfolio = Portfolio(config.initial_capital)
    pending: dict[date, list[dict]] = defaultdict(list)
    orders: list[dict] = []
    trades: list[dict] = []
    positions: list[dict] = []
    dividends: list[dict] = []
    decisions: list[dict] = []
    daily: list[dict] = []
    last_marks: dict[str, float] = {}
    warnings: list[str] = [
        "Execution assumes whole-share fills at raw next-session Open; board lots, "
        "partial fills, liquidity depth, market taxes and FX are not modeled.",
        "Calendar provenance is not verified as official HKEX calendar.",
        "Ranking uses only data <= rebalance date; fills use next-session raw open.",
    ]
    if unmodeled_actions:
        warnings.append(
            "distribution_in_kind occurs in the sample and is NOT valued; total return is exploratory."
        )
    if data_version is None:
        warnings.append("Content-derived data version unavailable; date labels do not establish reproducibility.")

    previous_equity = config.initial_capital

    for index, day in enumerate(days):
        day_str = day.isoformat()
        row_map = day_rows.get(day, {})

        # 1. Credit cash dividends on the ex-date for shares held entering today.
        for stock_id, position in sorted(portfolio.positions.items()):
            cash_per_share = ex_dividends.get((stock_id, day))
            if cash_per_share and position.quantity > 0:
                amount = position.quantity * cash_per_share
                portfolio.cash += amount
                dividends.append(
                    {
                        "event_date": day_str,
                        "stock_id": stock_id,
                        "shares": position.quantity,
                        "cash_per_share": cash_per_share,
                        "cash_flow": amount,
                    }
                )

        # 2. Execute due orders: sells release cash first, then buys.
        due = pending.pop(day, [])
        executed_today: list[dict] = []
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

        # 3. Mark positions at close and compute daily equity.
        positions_value = 0.0
        unrealized_pnl = 0.0
        stale = 0
        for stock_id, position in sorted(portfolio.positions.items()):
            row = row_map.get(stock_id)
            close = row.get("close") if row is not None else None
            if close is not None and pd.notna(close) and float(close) > 0:
                mark = float(close)
                last_marks[stock_id] = mark
                mark_status = "CLOSE"
            else:
                mark = last_marks.get(stock_id, position.cost_basis)
                stale += 1
                mark_status = "STALE_LAST_KNOWN"
            market_value = position.quantity * mark
            pnl = market_value - position.cost_basis * position.quantity
            positions_value += market_value
            unrealized_pnl += pnl
            positions.append(
                {
                    "trade_date": day_str, "stock_id": stock_id,
                    "quantity": position.quantity, "entry_date": position.entry_date,
                    "cost_basis": position.cost_basis, "raw_close_or_mark": mark,
                    "mark_status": mark_status, "market_value": market_value,
                    "unrealized_pnl": pnl,
                }
            )
        equity = portfolio.cash + positions_value
        if portfolio.cash < -1e-8:
            raise AssertionError("portfolio cash became negative")
        day_turnover = sum(t["notional"] for t in executed_today) / previous_equity
        daily.append(
            {
                "trade_date": day_str,
                "cash": portfolio.cash,
                "positions_value": positions_value,
                "equity": equity,
                "realized_pnl": portfolio.realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "dividend_cash": sum(d["cash_flow"] for d in dividends if d["event_date"] == day_str),
                "daily_return": equity / previous_equity - 1.0,
                "turnover": day_turnover,
                "stale_position_count": stale,
                "valuation_status": "STALE" if stale else "COMPLETE",
            }
        )
        previous_equity = equity

        # 4. Rebalance decision at close of rebalance days.
        if index % rebalance_frequency == 0:
            cutoff = pd.Timestamp(day)
            history = panel[panel_dates <= cutoff]
            scores = {stock_id: scorer(history, stock_id) for stock_id in ids}
            targets = select_top_n(scores, top_n)
            ranked = rank_by_score(scores)
            rank_of = {stock_id: position + 1 for position, stock_id in enumerate(ranked)}
            for stock_id in ids:
                decisions.append(
                    {
                        "rebalance_date": day_str,
                        "stock_id": stock_id,
                        "score": scores[stock_id],
                        "rank": rank_of.get(stock_id),
                        "selected": stock_id in targets,
                        "target_weight": targets.get(stock_id),
                    }
                )

            next_day = days[index + 1].isoformat() if index + 1 < len(days) else None
            for stock_id in sorted(portfolio.positions):
                if stock_id not in targets:
                    orders.append(
                        {
                            "order_id": f"sim-{len(orders) + 1:06d}",
                            "signal_date": day_str,
                            "execution_date": next_day,
                            "stock_id": stock_id,
                            "side": "SELL",
                            "target_weight": None,
                            "quantity": 0,
                            "status": "PENDING" if next_day else "REJECTED",
                            "reason": None if next_day else "NO_NEXT_SESSION_WITHIN_RANGE",
                        }
                    )
                    if next_day:
                        pending[days[index + 1]].append(orders[-1])
            for stock_id in sorted(targets):
                orders.append(
                    {
                        "order_id": f"sim-{len(orders) + 1:06d}",
                        "signal_date": day_str,
                        "execution_date": next_day,
                        "stock_id": stock_id,
                        "side": "BUY",
                        "target_weight": None,
                        "quantity": 0,
                        "status": "PENDING" if next_day else "REJECTED",
                        "reason": None if next_day else "NO_NEXT_SESSION_WITHIN_RANGE",
                    }
                )
                if next_day:
                    pending[days[index + 1]].append(orders[-1])

    daily_frame = pd.DataFrame(daily)
    daily_frame["drawdown"] = (
        daily_frame["equity"] / daily_frame["equity"].cummax().clip(lower=config.initial_capital) - 1.0
    )
    trades_frame = pd.DataFrame(
        trades,
        columns=[
            "signal_date", "execution_date", "stock_id", "side", "quantity", "raw_open",
            "execution_price", "notional", "commission", "slippage_cost", "realized_pnl", "cash_after",
        ],
    )
    positions_frame = pd.DataFrame(
        positions,
        columns=[
            "trade_date", "stock_id", "quantity", "entry_date", "cost_basis",
            "raw_close_or_mark", "mark_status", "market_value", "unrealized_pnl",
        ],
    )
    orders_frame = pd.DataFrame(
        orders,
        columns=[
            "order_id", "signal_date", "execution_date", "stock_id", "side",
            "target_weight", "quantity", "status", "reason",
        ],
    )
    dividends_frame = pd.DataFrame(
        dividends, columns=["event_date", "stock_id", "shares", "cash_per_share", "cash_flow"]
    )
    decisions_frame = pd.DataFrame(
        decisions,
        columns=[
            "rebalance_date", "stock_id", "score", "rank", "selected", "target_weight",
        ],
    )
    if not orders_frame.empty and (orders_frame["status"] == "PENDING").any():
        raise AssertionError("unfinished pending simulated orders")
    if not orders_frame.empty and (orders_frame["status"] == "REJECTED").any():
        warnings.append("One or more simulated orders were rejected; consult orders artifact for reasons.")
    if (daily_frame["valuation_status"] == "STALE").any():
        warnings.append("Some daily equity marks are carried forward; performance statistics are exploratory.")

    metadata = {
        "strategy_id": "ranking_top_n",
        "strategy_version": "1.0.0",
        "strategy_hash": "ranking-momentum-top-n (in-memory, no immutable YAML hash)",
        "data_version": data_version,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "stock_ids": ids,
        "top_n": top_n,
        "rebalance_frequency": rebalance_frequency,
        "scorer": getattr(scorer, "__name__", "custom"),
        "universe": "explicit cohort (not a historical listing universe)",
        "status": "EXPLORATORY",
        "execution": "T close score/rank, earliest T+1 trading-session raw Open",
        "valuation": "raw Close; stale last known mark if missing",
        "dividends": "cash dividends credited on ex-date for shares held entering that day",
        "assumptions": {
            "construction": "equal-weight top-N targets; dropped names sold, targets topped up",
            "fill": "whole shares, all-or-nothing order; no market partial fill",
            "corporate_actions": "cash dividends credited; distribution_in_kind not valued",
            "currency": "single currency; no FX conversion",
            **config.to_dict(),
        },
    }
    result = RankingBacktestResult(
        daily=daily_frame,
        trades=trades_frame,
        positions=positions_frame,
        orders=orders_frame,
        dividends=dividends_frame,
        decisions=decisions_frame,
        metrics=compute_performance(daily_frame, trades_frame, config),
        metadata=metadata,
        config=config,
        warnings=list(dict.fromkeys(warnings)),
    )
    if output_dir is not None:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        daily_frame.to_parquet(root / "daily_portfolio.parquet", index=False)
        trades_frame.to_parquet(root / "trades.parquet", index=False)
        positions_frame.to_parquet(root / "positions.parquet", index=False)
        orders_frame.to_parquet(root / "orders.parquet", index=False)
        dividends_frame.to_parquet(root / "dividends.parquet", index=False)
        decisions_frame.to_parquet(root / "decisions.parquet", index=False)
        (root / "summary.json").write_text(
            json.dumps(
                {"metrics": result.metrics, "metadata": metadata, "warnings": result.warnings},
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return result
