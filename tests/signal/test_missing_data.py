"""Missing-data and universe handling tests."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.signal.engine import SignalDataError, generate_signal, generate_signals
from hk_quant.signal.models import SignalStatus
from hk_quant.strategy.models import (
    Condition,
    ConditionGroup,
    HoldingPeriod,
    PriceDefinition,
    StrategyDefinition,
    UniverseSpec,
)

SIGNAL_DATE = "2026-09-24"


def _data_strategy() -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id="close_strategy",
        name="Close Strategy",
        version="1.0.0",
        universe=UniverseSpec(type="observed_price_universe"),
        entry=ConditionGroup(
            logic="all",
            conditions=[Condition(source="data", field="close", operator=">", value=400.0)],
        ),
        holding_period=HoldingPeriod(type="trading_days", value=5),
        price=PriceDefinition(adjusted=False),
    )


def _factor_strategy() -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id="momentum_strategy",
        name="Momentum Strategy",
        version="1.0.0",
        universe=UniverseSpec(type="observed_price_universe"),
        entry=ConditionGroup(
            logic="all",
            conditions=[Condition(source="factor", field="momentum_20", operator=">", value=0.05, unit="ratio")],
        ),
        holding_period=HoldingPeriod(type="trading_days", value=5),
        price=PriceDefinition(adjusted=False),
    )


def test_missing_data_field_is_data_unavailable(make_repository) -> None:
    from tests.signal.conftest import make_rows

    repo = make_repository(make_rows("TEST001", 3, SIGNAL_DATE, missing_last=True))
    signal = generate_signal(_data_strategy(), SIGNAL_DATE, "TEST001", repository=repo)

    assert signal.signal is None
    assert signal.status == SignalStatus.DATA_UNAVAILABLE


def test_out_of_universe_observed(make_repository) -> None:
    from tests.signal.conftest import make_rows

    repo = make_repository(make_rows("TEST001", 3, SIGNAL_DATE))
    signal = generate_signal(_data_strategy(), SIGNAL_DATE, "NOT_PRESENT", repository=repo)

    assert signal.signal is None
    assert signal.status == SignalStatus.OUT_OF_UNIVERSE


def test_out_of_universe_historical(make_repository) -> None:
    from tests.signal.conftest import make_rows

    universe_df = pd.DataFrame(
        {"stock_id": ["TEST001"], "listing_date": [pd.Timestamp("2020-01-01")], "delisting_date": [pd.NaT]}
    )
    repo = make_repository(make_rows("TEST001", 3, SIGNAL_DATE), universe_df=universe_df)
    strategy = _data_strategy()
    strategy.universe = UniverseSpec(type="historical_universe")

    signal = generate_signal(strategy, SIGNAL_DATE, "OTHER", repository=repo)
    assert signal.status == SignalStatus.OUT_OF_UNIVERSE


def test_historical_universe_unavailable_raises(make_repository) -> None:
    from tests.signal.conftest import make_rows

    repo = make_repository(make_rows("TEST001", 3, SIGNAL_DATE))  # no universe_df -> raises
    strategy = _data_strategy()
    strategy.universe = UniverseSpec(type="historical_universe")

    with pytest.raises(SignalDataError, match="historical_universe"):
        generate_signals(strategy, SIGNAL_DATE, universe=None, repository=repo)


def test_factor_missing_is_data_unavailable(make_repository) -> None:
    from tests.signal.conftest import make_rows

    # only 5 days of history -> momentum_20 cannot be computed
    repo = make_repository(make_rows("TEST001", 5, SIGNAL_DATE))
    signal = generate_signal(_factor_strategy(), SIGNAL_DATE, "TEST001", repository=repo)

    assert signal.signal is None
    assert signal.status == SignalStatus.DATA_UNAVAILABLE
