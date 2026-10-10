"""Research model tests."""

from __future__ import annotations

from hk_quant.research.models import (
    ResearchDefinition,
    ResearchStatus,
    VariableSpec,
)


def test_definition_basics() -> None:
    definition = ResearchDefinition(
        name="turnover_v1",
        variable=VariableSpec(name="turnover_rate", thresholds=[0.1, 0.5]),
        forward_periods=[1, 5],
    )
    assert definition.research_id == "turnover_v1"
    assert definition.thresholds == [0.1, 0.5]
    assert definition.to_dict()["variable"]["name"] == "turnover_rate"


def test_research_status_is_not_investment_rating() -> None:
    assert "BUY" not in {s.value for s in ResearchStatus}
    assert "SELL" not in {s.value for s in ResearchStatus}
