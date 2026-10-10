"""Strategy storage tests."""

from __future__ import annotations

import pytest

from hk_quant.strategy.builder import build_strategy_from_dict
from hk_quant.strategy.models import compute_strategy_hash
from hk_quant.strategy.storage import (
    StrategyImmutabilityError,
    load_strategy,
    save_strategy,
)

_VALID = {
    "id": "turnover_strategy",
    "name": "Turnover Strategy",
    "version": "1.0.0",
    "universe": {"type": "observed_price_universe"},
    "entry": {
        "all": [
            {"source": "data", "field": "close", "operator": ">", "value": 0.0}
        ]
    },
    "holding_period": {"type": "trading_days", "value": 30},
}


def test_save_and_load_identical(tmp_path) -> None:
    strategy = build_strategy_from_dict(_VALID, strategies_dir=tmp_path / "strategies")
    loaded = load_strategy("turnover_strategy", "1.0.0", tmp_path / "strategies")

    assert loaded.to_dict() == strategy.to_dict()
    assert loaded.strategy_hash == strategy.strategy_hash
    assert compute_strategy_hash(loaded) == compute_strategy_hash(strategy)


def test_version_is_immutable(tmp_path) -> None:
    build_strategy_from_dict(_VALID, strategies_dir=tmp_path / "strategies")

    changed = dict(_VALID)
    changed["entry"] = {
        "all": [
            {"source": "data", "field": "close", "operator": ">", "value": 100.0}
        ]
    }
    with pytest.raises(StrategyImmutabilityError):
        build_strategy_from_dict(changed, strategies_dir=tmp_path / "strategies")


def test_new_version_is_separate(tmp_path) -> None:
    build_strategy_from_dict(_VALID, strategies_dir=tmp_path / "strategies")

    v110 = dict(_VALID)
    v110["version"] = "1.1.0"
    v110["entry"] = {
        "all": [
            {"source": "data", "field": "close", "operator": ">", "value": 100.0}
        ]
    }
    build_strategy_from_dict(v110, strategies_dir=tmp_path / "strategies")

    v1 = load_strategy("turnover_strategy", "1.0.0", tmp_path / "strategies")
    v11 = load_strategy("turnover_strategy", "1.1.0", tmp_path / "strategies")
    assert v1.entry.conditions[0].value == 0.0
    assert v11.entry.conditions[0].value == 100.0


def test_idempotent_save_same_content(tmp_path) -> None:
    strategy = build_strategy_from_dict(_VALID, strategies_dir=tmp_path / "strategies")
    # saving the same content again is a no-op, not an error
    save_strategy(strategy, tmp_path / "strategies")
