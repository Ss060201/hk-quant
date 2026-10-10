"""Strategy model tests."""

from __future__ import annotations

from hk_quant.strategy.models import (
    Condition,
    ConditionGroup,
    HoldingPeriod,
    ResearchProvenance,
    StrategyDefinition,
    StrategyStatus,
    UniverseSpec,
    compute_strategy_hash,
)


def _definition(threshold: float = 0.4) -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id="turnover_strategy",
        name="Turnover Strategy",
        version="1.0.0",
        universe=UniverseSpec(type="observed_price_universe"),
        entry=ConditionGroup(
            logic="all",
            conditions=[
                Condition(source="data", field="close", operator=">", value=threshold)
            ],
        ),
        holding_period=HoldingPeriod(type="trading_days", value=30),
        research=ResearchProvenance(
            research_id="turnover_forward_return_v1",
            source_status="WORTH_FURTHER_RESEARCH",
        ),
        status=StrategyStatus.DRAFT,
    )


def test_strategy_definition_round_trip_dict() -> None:
    definition = _definition()
    data = definition.to_dict()
    assert data["id"] == "turnover_strategy"
    assert data["version"] == "1.0.0"
    assert data["status"] == "DRAFT"
    assert data["entry"]["all"][0]["field"] == "close"


def test_hash_same_definition_same_hash() -> None:
    a = _definition()
    b = _definition()
    assert compute_strategy_hash(a) == compute_strategy_hash(b)


def test_hash_different_definition_different_hash() -> None:
    a = _definition(threshold=0.4)
    b = _definition(threshold=0.5)
    assert compute_strategy_hash(a) != compute_strategy_hash(b)


def test_hash_excludes_lifecycle_metadata() -> None:
    a = _definition()
    b = _definition()
    b.status = StrategyStatus.VALIDATED
    b.created_at = "2099-01-01T00:00:00+00:00"
    assert compute_strategy_hash(a) == compute_strategy_hash(b)
