"""Factor model tests."""

from __future__ import annotations

from hk_quant.factors.models import FactorDefinition


def test_factor_definition() -> None:
    definition = FactorDefinition(
        factor_id="momentum_20",
        version="1.0.0",
        description="20d momentum",
        required_fields=("close",),
        parameters={"window": 20},
    )
    data = definition.to_dict()
    assert data["factor_id"] == "momentum_20"
    assert data["version"] == "1.0.0"
    assert data["required_fields"] == ["close"]
    assert data["parameters"] == {"window": 20}
