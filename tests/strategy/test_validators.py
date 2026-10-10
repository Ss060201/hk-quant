"""Strategy validator tests."""

from __future__ import annotations

import pytest

from hk_quant.data.universe import UniverseDataUnavailableError
from hk_quant.strategy.models import (
    Condition,
    ConditionGroup,
    HoldingPeriod,
    StrategyDefinition,
    UniverseSpec,
)
from hk_quant.strategy.validators import StrategyValidationError, validate_strategy


def _definition(**overrides) -> StrategyDefinition:
    data = dict(
        strategy_id="test_strategy",
        name="Test Strategy",
        version="1.0.0",
        universe=UniverseSpec(type="observed_price_universe"),
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="data", field="close", operator=">", value=0.0, unit="hkd")
            ],
        ),
        holding_period=HoldingPeriod(type="trading_days", value=30),
    )
    data.update(overrides)
    return StrategyDefinition(**data)


def test_valid_strategy_passes() -> None:
    validate_strategy(_definition())


def test_missing_id_raises() -> None:
    with pytest.raises(StrategyValidationError, match="strategy_id"):
        validate_strategy(_definition(strategy_id=""))


def test_invalid_version_raises() -> None:
    with pytest.raises(StrategyValidationError, match="version"):
        validate_strategy(_definition(version="1.0"))


def test_invalid_operator_raises() -> None:
    definition = _definition(
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="data", field="close", operator="<>", value=0.0)
            ],
        )
    )
    with pytest.raises(StrategyValidationError, match="operator"):
        validate_strategy(definition)


def test_nan_value_raises() -> None:
    definition = _definition(
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="data", field="close", operator=">", value=float("nan"))
            ],
        )
    )
    with pytest.raises(StrategyValidationError, match="finite"):
        validate_strategy(definition)


def test_unknown_field_raises() -> None:
    definition = _definition(
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="data", field="does_not_exist", operator=">", value=1.0)
            ],
        )
    )
    with pytest.raises(StrategyValidationError, match="unknown data field"):
        validate_strategy(definition)


def test_unknown_factor_field_raises() -> None:
    definition = _definition(
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="factor", field="unknown_factor_99", operator=">", value=0.1)
            ],
        )
    )
    with pytest.raises(StrategyValidationError, match="unknown factor"):
        validate_strategy(definition)


def test_registered_factor_field_passes() -> None:
    definition = _definition(
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="factor", field="momentum_20", operator=">", value=0.05, unit="ratio")
            ],
        )
    )
    validate_strategy(definition)


def test_turnover_rate_unavailable_raises() -> None:
    definition = _definition(
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="data", field="turnover_rate", operator=">", value=0.4, unit="ratio")
            ],
        )
    )
    with pytest.raises(StrategyValidationError, match="unavailable"):
        validate_strategy(definition)


def test_negative_turnover_rate_rejected() -> None:
    # Even if turnover_rate were available, -5% is an invalid ratio.
    definition = _definition(
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="data", field="close", operator=">", value=-5.0)
            ],
        )
    )
    with pytest.raises(StrategyValidationError, match="non-negative"):
        validate_strategy(definition)


def test_invalid_holding_period_raises() -> None:
    definition = _definition(holding_period=HoldingPeriod(type="calendar_days", value=30))
    with pytest.raises(StrategyValidationError, match="holding_period"):
        validate_strategy(definition)

    definition = _definition(holding_period=HoldingPeriod(type="trading_days", value=0))
    with pytest.raises(StrategyValidationError, match="positive"):
        validate_strategy(definition)


def test_invalid_universe_raises() -> None:
    definition = _definition(universe=UniverseSpec(type="nonsense"))
    with pytest.raises(StrategyValidationError, match="universe"):
        validate_strategy(definition)


class _FakeRepo:
    def get_universe(self, as_of_date):
        raise UniverseDataUnavailableError("listing_date unavailable")


def test_historical_universe_unavailable_raises() -> None:
    definition = _definition(universe=UniverseSpec(type="historical_universe"))
    with pytest.raises(StrategyValidationError, match="historical_universe"):
        validate_strategy(definition, repository=_FakeRepo())
