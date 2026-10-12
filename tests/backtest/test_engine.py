"""Hand-checkable synthetic backtests with explicit trading sessions."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.backtest import BacktestConfig, run_backtest
from hk_quant.data.calendar import TradingCalendar
from hk_quant.strategy.models import (
    Condition, ConditionGroup, HoldingPeriod, StrategyDefinition, UniverseSpec,
)


DAYS = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]


class MemoryRepository:
    def __init__(self, rows, calendar_days=DAYS, adjusted_offset=0):
        self.panel = pd.DataFrame(rows)
        self.calendar = TradingCalendar(calendar_days)
        self.adjusted_offset = adjusted_offset

    def get_calendar(self):
        return self.calendar

    def get_daily_prices(self, stock_ids=None, start_date=None, end_date=None):
        frame = self.panel
        if stock_ids:
            frame = frame[frame.stock_id.isin(stock_ids)]
        if start_date:
            frame = frame[frame.trade_date >= str(start_date)]
        if end_date:
            frame = frame[frame.trade_date <= str(end_date)]
        return frame.copy().reset_index(drop=True)

    def get_prices(self, stock_ids=None, start_date=None, end_date=None, *, adjusted=False):
        frame = self.get_daily_prices(stock_ids, start_date, end_date)
        if adjusted:
            frame["close"] = frame["close"] + self.adjusted_offset
        return frame

    def get_data_version(self):
        return "synthetic-input-v1"


def row(stock, day, *, open=100.0, close=100.0, volume=10000):
    return {"stock_id": stock, "trade_date": day, "open": open, "close": close,
            "high": close, "low": close, "volume": volume, "amount": 100000.0,
            "turnover_rate": float("nan"), "source": "synthetic", "ingested_at": day}


def strategy(threshold=0, hold=1):
    return StrategyDefinition(
        strategy_id="fixed_price_demo", name="Fixed price demo", version="1.0.0",
        universe=UniverseSpec(),
        entry=ConditionGroup(logic="all", conditions=[
            Condition(source="data", field="close", operator=">", value=threshold),
        ]),
        holding_period=HoldingPeriod(value=hold),
    )


def test_t_close_fill_is_next_calendar_day_open_and_costs_are_hand_checkable():
    repository = MemoryRepository([
        row("A", DAYS[0], close=100), row("A", DAYS[1], open=100, close=110),
        row("A", DAYS[2], open=999, close=120), row("A", DAYS[3], open=120, close=120),
    ])
    config = BacktestConfig(initial_capital=1000, commission_rate=0.01, slippage_rate=0.01)
    result = run_backtest(strategy(), DAYS[0], DAYS[-1], repository, config, universe=["A"])

    assert result.trades.execution_date.tolist() == [DAYS[1], DAYS[3]]
    buy, sell = result.trades.to_dict("records")
    assert buy["signal_date"] == DAYS[0]
    assert buy["raw_open"] == 100  # ignores adjusted close and next day's close
    assert buy["execution_price"] == pytest.approx(101)
    assert buy["quantity"] == 9  # floor(1000 / (101 * 1.01))
    assert buy["commission"] == pytest.approx(9.09)
    assert result.daily.loc[1, "cash"] == pytest.approx(81.91)
    assert result.daily.loc[1, "equity"] == pytest.approx(1071.91)
    assert sell["signal_date"] == DAYS[2]
    assert sell["execution_price"] == pytest.approx(118.8)
    assert sell["commission"] == pytest.approx(10.692)
    assert sell["realized_pnl"] == pytest.approx(140.418)
    assert result.daily.iloc[-1].equity == pytest.approx(1140.418)
    assert result.metrics["total_return"] == pytest.approx(0.140418)
    assert result.metrics["win_rate"] == 1.0
    assert result.metadata["status"] == "EXPLORATORY"
    assert result.metadata["data_version"] == "synthetic-input-v1"


def test_equal_weight_two_names_and_new_signal_does_not_liquidate_holds():
    rows = [row(stock, day) for stock in ("A", "B") for day in DAYS]
    rows += [row("C", day) for day in DAYS[1:]]
    result = run_backtest(
        strategy(hold=50), DAYS[0], DAYS[2], MemoryRepository(rows),
        BacktestConfig(initial_capital=1000, commission_rate=0, slippage_rate=0),
        universe=["A", "B", "C"],
    )
    assert list(result.trades.stock_id) == ["A", "B"]
    assert result.trades.quantity.tolist() == [5, 5]
    assert result.daily.iloc[1].equity == 1000
    assert result.daily.iloc[-1].cash == 0
    assert set(result.positions[result.positions.trade_date == DAYS[2]].stock_id) == {"A", "B"}
    assert not (result.trades.side == "SELL").any()
    assert "INSUFFICIENT_CASH_OR_TARGET" in result.orders.reason.tolist()


@pytest.mark.parametrize("open_value,volume,reason", [
    (float("nan"), 100, "INVALID_OPEN_PRICE"),
    (100, 0, "UNTRADABLE_VOLUME"),
    (100, float("nan"), "UNKNOWN_TRADABILITY"),
])
def test_missing_open_and_suspended_volume_reject_without_close_fallback(open_value, volume, reason):
    rows = [row("A", DAYS[0], close=120), row("A", DAYS[1], open=open_value, close=300, volume=volume)]
    result = run_backtest(strategy(), DAYS[0], DAYS[1], MemoryRepository(rows), universe=["A"])
    first = result.orders.iloc[0]
    assert first.status == "REJECTED"
    assert first.reason == reason
    assert result.trades.empty
    assert result.daily.iloc[-1].equity == 1_000_000


def test_missing_price_row_rejected_and_sample_end_order_explicit():
    repository = MemoryRepository([row("A", DAYS[0])], calendar_days=DAYS[:2])
    result = run_backtest(strategy(), DAYS[0], DAYS[1], repository, universe=["A"])
    assert result.orders.iloc[0].reason == "MISSING_OPEN_PRICE"
    assert not result.orders.status.eq("PENDING").any()
    one_day = run_backtest(strategy(), DAYS[0], DAYS[0], repository, universe=["A"])
    assert one_day.orders.iloc[0].reason == "NO_NEXT_SESSION_WITHIN_RANGE"


def test_no_negative_cash_when_even_one_share_is_unaffordable():
    rows = [row("A", DAYS[0]), row("A", DAYS[1], open=300)]
    result = run_backtest(
        strategy(), DAYS[0], DAYS[1], MemoryRepository(rows),
        BacktestConfig(initial_capital=100, commission_rate=0.1, slippage_rate=0.1),
        universe=["A"],
    )
    assert result.orders.iloc[0].reason == "INSUFFICIENT_CASH_OR_TARGET"
    assert result.trades.empty
    assert result.daily.cash.min() == 100


def test_future_close_change_cannot_change_earlier_signal():
    before = [row("A", DAYS[0], close=150), row("A", DAYS[1], close=100)]
    altered = [row("A", DAYS[0], close=150), row("A", DAYS[1], close=900)]
    a = run_backtest(strategy(threshold=120), DAYS[0], DAYS[1], MemoryRepository(before), universe=["A"])
    b = run_backtest(strategy(threshold=120), DAYS[0], DAYS[1], MemoryRepository(altered), universe=["A"])
    assert a.signals.iloc[0]["reason"] == b.signals.iloc[0]["reason"]
    assert a.signals.iloc[0]["signal"] == b.signals.iloc[0]["signal"] == "BUY"


def test_raw_open_used_even_when_signal_price_is_adjusted():
    rows = [row("A", DAYS[0], close=100), row("A", DAYS[1], open=100)]
    result = run_backtest(
        strategy(threshold=500), DAYS[0], DAYS[1], MemoryRepository(rows, adjusted_offset=1000),
        BacktestConfig(initial_capital=1000, commission_rate=0, slippage_rate=0),
        universe=["A"],
    )
    assert result.signals.iloc[0]["signal"] == "BUY"
    assert result.trades.iloc[0].raw_open == 100


def test_stale_marks_disclosed_and_performance_marked_exploratory():
    rows = [row("A", DAYS[0]), row("A", DAYS[1], close=float("nan"))]
    result = run_backtest(strategy(), DAYS[0], DAYS[1], MemoryRepository(rows), universe=["A"])
    assert result.positions.iloc[-1].mark_status == "STALE_LAST_KNOWN"
    assert result.daily.iloc[-1].valuation_status == "STALE"
    assert any("carrying previous known mark" in warning for warning in result.warnings)


def test_save_artifacts_refuses_to_overwrite(tmp_path):
    pytest.importorskip("pyarrow")
    rows = [row("A", DAYS[0]), row("A", DAYS[1])]
    result = run_backtest(strategy(), DAYS[0], DAYS[1], MemoryRepository(rows), universe=["A"])
    from hk_quant.backtest.results import save_backtest
    output = tmp_path / "trial"
    save_backtest(result, output)
    assert (output / "summary.json").exists()
    assert (output / "orders.parquet").exists()
    assert (output / "equity.png").exists()
    with pytest.raises(FileExistsError):
        save_backtest(result, output)
