"""Research result artifact tests."""

from __future__ import annotations

import json

import pandas as pd

from hk_quant.research.models import (
    ResearchDefinition,
    ResearchResult,
    ResearchStatus,
    VariableSpec,
)
from hk_quant.research.results import build_summary, save_research_result


def _result() -> ResearchResult:
    definition = ResearchDefinition(
        name="turnover_v1",
        variable=VariableSpec(name="turnover_rate", thresholds=[0.1, 0.5]),
        forward_periods=[1, 5],
    )
    return ResearchResult(
        research_id="turnover_v1",
        name="turnover_v1",
        data_version="HK_DAILY_2026_09_24",
        parameters=definition.to_dict(),
        events=pd.DataFrame(
            {
                "stock_id": ["A"],
                "event_date": pd.to_datetime(["2020-01-02"]),
                "variable_name": ["turnover_rate"],
                "variable_value": [0.2],
                "threshold": [0.1],
            }
        ),
        forward_returns=pd.DataFrame(
            {
                "stock_id": ["A"],
                "event_date": pd.to_datetime(["2020-01-02"]),
                "variable_name": ["turnover_rate"],
                "variable_value": [0.2],
                "threshold": [0.1],
                "forward_period": [1],
                "forward_return": [0.01],
                "valid_sample": [True],
                "exit_date": pd.to_datetime(["2020-01-03"]),
            }
        ),
        statistics=pd.DataFrame(
            {
                "threshold": [0.1],
                "forward_period": [1],
                "sample_count": [1],
                "valid_sample_count": [1],
                "mean": [0.01],
                "median": [0.01],
                "std": [float("nan")],
                "win_rate": [1.0],
                "q25": [0.01],
                "q75": [0.01],
                "min": [0.01],
                "max": [0.01],
                "ci_lower": [float("nan")],
                "ci_upper": [float("nan")],
            }
        ),
        relationship_analysis={"threshold_return_relationships": []},
        warnings=["exploratory"],
        status=ResearchStatus.NO_EVIDENCE,
        tested_combinations=4,
    )


def test_build_summary_has_required_keys() -> None:
    summary = build_summary(_result())
    required = {
        "research_id",
        "research_name",
        "data_version",
        "thresholds",
        "forward_periods",
        "return_definition",
        "event_mode",
        "sample_counts",
        "summary_statistics",
        "relationship_analysis",
        "warnings",
        "conclusion_status",
    }
    assert required.issubset(set(summary.keys()))


def test_save_research_result_writes_artifacts(tmp_path) -> None:
    root = save_research_result(_result(), tmp_path / "research" / "turnover_v1")
    assert (root / "summary.json").exists()
    assert (root / "events.parquet").exists()
    assert (root / "forward_returns.parquet").exists()
    assert (root / "config.yaml").exists()

    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert summary["conclusion_status"] == "NO_EVIDENCE"
