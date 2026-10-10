"""Strategy Builder integration tests.

Covers the full chain::

    ResearchResult -> explicit strategy config -> Strategy Builder
                   -> validation -> artifact -> load -> same definition

These are deterministic (no network); the turnover example is verified to
fail validation honestly because turnover_rate is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hk_quant.research.models import ResearchResult, ResearchStatus
from hk_quant.strategy import (
    StrategyValidationError,
    build_strategy,
    create_strategy_from_research,
    load_strategy,
    validate_strategy,
)
from hk_quant.strategy.config import load_strategy_definition

pytestmark = pytest.mark.integration

_EXAMPLES = Path(__file__).resolve().parents[2] / "strategies" / "examples"


def test_synthetic_strategy_full_chain(tmp_path) -> None:
    config = _EXAMPLES / "synthetic_momentum_strategy.yaml"
    strategy = build_strategy(config, strategies_dir=tmp_path / "strategies")

    loaded = load_strategy(
        "synthetic_momentum_strategy", "1.0.0", tmp_path / "strategies"
    )
    assert loaded.to_dict() == strategy.to_dict()
    assert loaded.strategy_hash == strategy.strategy_hash
    assert loaded.research.research_id == "turnover_forward_return_v1_synthetic"


def _research_result() -> ResearchResult:
    return ResearchResult(
        research_id="turnover_forward_return_v1_synthetic",
        name="turnover_forward_return_v1_synthetic",
        data_version="HK_DAILY_2026_09_24",
        parameters={},
        events=pd.DataFrame(),
        forward_returns=pd.DataFrame(),
        statistics=pd.DataFrame(),
        relationship_analysis={},
        warnings=[],
        status=ResearchStatus.WORTH_FURTHER_RESEARCH,
        tested_combinations=1,
    )


def test_research_to_strategy_chain(tmp_path) -> None:
    strategy = create_strategy_from_research(
        _research_result(),
        _EXAMPLES / "synthetic_momentum_strategy.yaml",
        strategies_dir=tmp_path / "strategies",
    )
    assert strategy.research.research_id == "turnover_forward_return_v1_synthetic"
    assert strategy.research.source_status == "WORTH_FURTHER_RESEARCH"

    loaded = load_strategy(
        "synthetic_momentum_strategy", "1.0.0", tmp_path / "strategies"
    )
    assert loaded.to_dict() == strategy.to_dict()


def test_turnover_strategy_fails_validation_honestly() -> None:
    definition = load_strategy_definition(_EXAMPLES / "turnover_strategy_v1.yaml")
    with pytest.raises(StrategyValidationError, match="turnover_rate"):
        validate_strategy(definition)
