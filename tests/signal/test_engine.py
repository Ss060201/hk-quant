"""Signal engine tests (BUY / SELL / HOLD, holding period, determinism)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.signal.engine import generate_signal
from hk_quant.signal.models import SignalStatus, SignalType
from hk_quant.signal.state import PositionState
from hk_quant.strategy.models import (
    Condition,
    ConditionGroup,
    ExitSpec,
    HoldingPeriod,
    PriceDefinition,
    StrategyDefinition,
    UniverseSpec,
)

SIGNAL_DATE = "2026-09-24"


def _close_strategy(
    threshold: float = 400.0,
    holding: int = 5,
    exit_spec: ExitSpec | None = None,
) -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id="close_strategy",
        name="Close Strategy",
        version="1.0.0",
        universe=UniverseSpec(type="observed_price_universe"),
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="data", field="close", operator=">", value=threshold, unit="currency")
            ],
        ),
        holding_period=HoldingPeriod(type="trading_days", value=holding),
        exit=exit_spec,
        price=PriceDefinition(adjusted=False),
    )


def test_entry_true_without_position_is_buy(make_repository) -> None:
    from tests.signal.conftest import make_rows

    repo = make_repository(make_rows("TEST001", 1, SIGNAL_DATE, start_close=500.0))
    signal = generate_signal(_close_strategy(), SIGNAL_DATE, "TEST001", repository=repo)

    assert signal.signal == SignalType.BUY.value
    assert signal.status == SignalStatus.VALID
    assert signal.strategy_hash
    assert signal.data_version


def test_entry_false_without_position_is_hold(make_repository) -> None:
    from tests.signal.conftest import make_rows

    repo = make_repository(make_rows("TEST001", 1, SIGNAL_DATE, start_close=300.0))
    signal = generate_signal(_close_strategy(), SIGNAL_DATE, "TEST001", repository=repo)

    assert signal.signal == SignalType.HOLD.value
    assert signal.status == SignalStatus.VALID


def test_holding_period_expired_is_sell(make_repository) -> None:
    from tests.signal.conftest import make_rows

    repo = make_repository(make_rows("TEST001", 10, SIGNAL_DATE, start_close=500.0))
    calendar = repo.get_calendar()
    days = calendar.get_trading_days(end_date=SIGNAL_DATE)
    entry_date = days[-6].isoformat()  # 5 trading days before signal date

    state = PositionState(
        stock_id="TEST001",
        entry_date=entry_date,
        strategy_id="close_strategy",
        strategy_version="1.0.0",
    )
    signal = generate_signal(_close_strategy(), SIGNAL_DATE, "TEST001", state=state, repository=repo)
    assert signal.signal == SignalType.SELL.value
    assert signal.reason["holding_period"]["trading_days_held"] == 5


def test_holding_period_not_expired_is_hold(make_repository) -> None:
    from tests.signal.conftest import make_rows

    repo = make_repository(make_rows("TEST001", 10, SIGNAL_DATE, start_close=500.0))
    calendar = repo.get_calendar()
    days = calendar.get_trading_days(end_date=SIGNAL_DATE)
    entry_date = days[-2].isoformat()  # only 1 trading day held

    state = PositionState("TEST001", entry_date, "close_strategy", "1.0.0")
    signal = generate_signal(_close_strategy(), SIGNAL_DATE, "TEST001", state=state, repository=repo)
    assert signal.signal == SignalType.HOLD.value


def test_exit_condition_is_sell(make_repository) -> None:
    from tests.signal.conftest import make_rows

    exit_spec = ExitSpec(
        conditions=ConditionGroup(
            logic="any",
            conditions=[Condition(source="data", field="close", operator="<", value=350.0)],
        )
    )
    repo = make_repository(make_rows("TEST001", 3, SIGNAL_DATE, start_close=300.0))
    state = PositionState("TEST001", "2026-09-22", "close_strategy", "1.0.0")

    signal = generate_signal(
        _close_strategy(exit_spec=exit_spec), SIGNAL_DATE, "TEST001", state=state, repository=repo
    )
    assert signal.signal == SignalType.SELL.value


def test_signal_is_deterministic(make_repository) -> None:
    from tests.signal.conftest import make_rows

    repo = make_repository(make_rows("TEST001", 10, SIGNAL_DATE, start_close=500.0))
    strategy = _close_strategy()

    first = generate_signal(strategy, SIGNAL_DATE, "TEST001", repository=repo)
    second = generate_signal(strategy, SIGNAL_DATE, "TEST001", repository=repo)
    assert first.to_dict() == second.to_dict()


def test_reason_is_structured(make_repository) -> None:
    from tests.signal.conftest import make_rows

    repo = make_repository(make_rows("TEST001", 1, SIGNAL_DATE, start_close=500.0))
    signal = generate_signal(_close_strategy(), SIGNAL_DATE, "TEST001", repository=repo)
    results = signal.reason["entry"]["condition_results"]
    assert results[0]["field"] == "close"
    assert results[0]["actual_value"] == pytest.approx(500.0)
    assert results[0]["passed"] is True
