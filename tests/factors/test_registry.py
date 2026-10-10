"""Factor registry tests."""

from __future__ import annotations

import pytest

from hk_quant.factors import get_factor, list_factors
from hk_quant.factors.models import FactorDefinition
from hk_quant.factors.registry import FactorRegistry


def test_register_and_get() -> None:
    registry = FactorRegistry()
    registry.register(
        FactorDefinition("x", "1.0.0", "d", ("close",)), lambda close: 0.0
    )
    assert registry.get("x").factor_id == "x"
    assert registry.get_calculator("x") is not None


def test_latest_version_lookup() -> None:
    registry = FactorRegistry()
    registry.register(FactorDefinition("x", "1.0.0", "d", ("close",)), lambda c: 1.0)
    registry.register(FactorDefinition("x", "2.0.0", "d", ("close",)), lambda c: 2.0)
    assert registry.get("x").version == "2.0.0"
    assert registry.get("x", version="1.0.0").version == "1.0.0"


def test_unknown_factor_raises() -> None:
    with pytest.raises(KeyError):
        get_factor("does_not_exist")


def test_builtins_are_registered() -> None:
    assert get_factor("momentum_20").version == "1.0.0"
    assert get_factor("volatility_20").version == "1.0.0"
    ids = {f.factor_id for f in list_factors()}
    assert {"momentum_20", "volatility_20"}.issubset(ids)
