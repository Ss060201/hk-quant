"""Strategy builder tests."""

from __future__ import annotations

import pandas as pd

from hk_quant.research.models import ResearchResult, ResearchStatus
from hk_quant.strategy.builder import (
    build_strategy_from_dict,
    create_strategy_from_research,
)
from hk_quant.strategy.models import compute_strategy_hash

_VALID = {
    "id": "turnover_strategy",
    "name": "Turnover Strategy",
    "version": "1.0.0",
    "research": {"research_id": "turnover_forward_return_v1"},
    "universe": {"type": "observed_price_universe"},
    "entry": {
        "all": [
            {"source": "data", "field": "close", "operator": ">", "value": 0.0, "unit": "hkd"}
        ]
    },
    "holding_period": {"type": "trading_days", "value": 30},
    "exit": {"type": "holding_period"},
    "status": "draft",
}


def test_build_strategy_from_dict(tmp_path) -> None:
    strategy = build_strategy_from_dict(_VALID, strategies_dir=tmp_path / "strategies")
    assert strategy.strategy_id == "turnover_strategy"
    assert strategy.strategy_hash == compute_strategy_hash(strategy)
    assert strategy.status.value == "DRAFT"
    assert (tmp_path / "strategies" / "turnover_strategy" / "v1.0.0.yaml").exists()


def test_build_strategy_saves_artifact(tmp_path) -> None:
    build_strategy_from_dict(_VALID, strategies_dir=tmp_path / "strategies")
    path = tmp_path / "strategies" / "turnover_strategy" / "v1.0.0.yaml"
    assert path.exists()


def _research_result() -> ResearchResult:
    return ResearchResult(
        research_id="turnover_forward_return_v1",
        name="turnover_forward_return_v1",
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


def test_create_strategy_from_research_provenance(tmp_path) -> None:
    config = {
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
    strategy = create_strategy_from_research(
        _research_result(), config, strategies_dir=tmp_path / "strategies"
    )
    assert strategy.research.research_id == "turnover_forward_return_v1"
    assert strategy.research.source_status == "WORTH_FURTHER_RESEARCH"
