"""Experiment history should remain identifiable and intact across reruns."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
import pytest

from hk_quant.experiments import ExperimentRegistry, canonical_config, config_hash
from hk_quant.research.models import ResearchResult, ResearchStatus


def test_config_is_canonical_and_order_insensitive() -> None:
    left = {"b": [1, {"z": False, "a": 3}], "a": "研究"}
    right = {"a": "研究", "b": [1, {"a": 3, "z": False}]}
    assert canonical_config(left) == canonical_config(right)
    assert config_hash(left) == config_hash(right)
    assert config_hash(left) != config_hash({"a": "研究", "b": [2]})
    with pytest.raises(ValueError):
        config_hash({"invalid": float("nan")})
    with pytest.raises(TypeError):
        config_hash({"unordered": {1, 2}})


def test_create_list_compare_reruns_and_immutable_completion(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments")
    first = registry.create_experiment(
        "validation", {"baseline": "hold", "split": {"end": "2025-01-01"}},
        strategy_id="s1", research_question="is s1 better than hold?",
    )
    registry.update_experiment_status(first.experiment_id, "RUNNING")
    registry.save_artifact(first.experiment_id, "summary.json", {"sharpe": 0.2})
    first = registry.update_experiment_status(first.experiment_id, "COMPLETED", conclusion="exploratory")
    second = registry.create_experiment(
        "validation", {"split": {"end": "2025-01-01"}, "baseline": "hold"},
        strategy_id="s2", data_version="sha256:abc",
    )
    registry.save_artifact(second.experiment_id, "summary.json", {"sharpe": 0.4})
    second = registry.update_experiment_status(second.experiment_id, "COMPLETED")
    assert first.config_hash == second.config_hash
    assert first.experiment_id != second.experiment_id
    assert first.artifact_dir != second.artifact_dir
    assert first.data_version == "unavailable"
    assert any("data_version unavailable" in item for item in first.warnings)
    assert len(registry.list_experiments(experiment_type="validation", strategy_id="s1")) == 1
    assert len(registry.list_experiments(config_hash=first.config_hash)) == 2
    assert len(registry.list_experiments(data_version="sha256:abc")) == 1
    assert registry.get_experiment(first.experiment_id).config == first.config
    assert registry.load_experiment_artifacts(first.experiment_id)["summary.json"] == {"sharpe": 0.2}
    difference = registry.compare_experiments([first.experiment_id, second.experiment_id])
    assert difference["differences"]["summary"][first.experiment_id]["sharpe"] == 0.2
    assert "config_hash" not in difference["differences"]
    with pytest.raises(ValueError, match="immutable"):
        registry.update_experiment_status(first.experiment_id, "COMPLETED")
    with pytest.raises(ValueError, match="immutable"):
        registry.save_artifact(first.experiment_id, "summary2.json", {})
    assert json.loads((first.artifact_dir / "config.json").read_text()) == first.config


def test_missing_modified_and_unsafe_artifacts(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path)
    run = registry.create_experiment("research", {"a": 1})
    with pytest.raises(ValueError, match="simple filename"):
        registry.save_artifact(run.experiment_id, "../escape.json", {"a": 1})
    registry.save_artifact(run.experiment_id, "summary.json", {"result": True})
    with pytest.raises(FileExistsError):
        registry.save_artifact(run.experiment_id, "summary.json", {"result": False})
    registry.update_experiment_status(run.experiment_id, "COMPLETED")
    (run.artifact_dir / "summary.json").unlink()
    with pytest.raises(FileNotFoundError, match="missing artifact"):
        registry.load_experiment_artifacts(run.experiment_id)
    with pytest.raises(FileNotFoundError, match="missing artifact"):
        registry.compare_experiments([run.experiment_id, run.experiment_id])
    (run.artifact_dir / "summary.json").write_text('{"result": false}')
    with pytest.raises(ValueError, match="content changed"):
        registry.load_experiment_artifacts(run.experiment_id)


def _synthetic_research() -> ResearchResult:
    return ResearchResult(
        research_id="synthetic", name="synthetic", data_version="sha256:prices",
        parameters={"variable": {"name": "turnover_rate", "thresholds": [0.1]},
                    "forward_periods": [1], "date_range": {"start": "2020-01-01", "end": "2020-01-02"},
                    "universe": {"mode": "observed_price_universe"}},
        events=pd.DataFrame({"stock_id": ["00001"], "event_date": ["2020-01-01"]}),
        forward_returns=pd.DataFrame({"stock_id": ["00001"], "forward_return": [0.02]}),
        statistics=pd.DataFrame({"threshold": [0.1], "forward_period": [1],
                                 "sample_count": [1], "valid_sample_count": [1],
                                 "std": [float("nan")]}),
        relationship_analysis={}, warnings=["synthetic data only"],
        status=ResearchStatus.NO_EVIDENCE, tested_combinations=1,
    )


def test_research_result_snapshots_have_distinct_artifacts(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path)
    result = _synthetic_research()
    first = registry.register_research_result(result)
    second = registry.register_research_result(result)
    assert first.status == second.status == "COMPLETED"
    assert first.config_hash == second.config_hash
    assert first.artifact_dir != second.artifact_dir
    summary = registry.load_experiment_artifacts(first.experiment_id)["summary.json"]
    assert summary["research_id"] == "synthetic"
    assert summary["summary_statistics"][0]["std"] is None
    assert len(registry.load_experiment_artifacts(first.experiment_id)["events.parquet"]) == 1


def test_backtest_result_snapshots_keep_canonical_config(tmp_path, monkeypatch) -> None:
    from hk_quant.backtest import results as backtest_results

    @dataclass
    class FakeBacktestConfig:
        initial_cash: int = 1_000
        commission_rate: float = 0.01

    @dataclass
    class FakeBacktestResult:
        config: FakeBacktestConfig
        metadata: dict
        warnings: list[str]
        artifact_dir: str | None = None

    def fake_save_backtest(result, output_dir):
        output_dir.mkdir(exist_ok=True)
        (output_dir / "config.json").write_text('{"writer": "backtest"}')
        (output_dir / "summary.json").write_text('{"total_return": 0.15}')

    monkeypatch.setattr(backtest_results, "save_backtest", fake_save_backtest)
    result = FakeBacktestResult(
        FakeBacktestConfig(),
        {"strategy_id": "s1", "strategy_version": "1.0", "strategy_hash": "abc",
         "data_version": "sha256:prices", "status": "EXPLORATORY",
         "start_date": "2020-01-01", "end_date": "2020-01-31"},
        ["observed universe"],
    )
    record = ExperimentRegistry(tmp_path).register_backtest_result(result)
    artifacts = ExperimentRegistry(tmp_path).load_experiment_artifacts(record.experiment_id)
    assert record.status == "COMPLETED"
    assert artifacts["summary.json"]["total_return"] == 0.15
    assert artifacts["config.json"] == {"initial_cash": 1_000, "commission_rate": 0.01}
    assert artifacts["backtest_config.json"] == {"writer": "backtest"}
    assert result.artifact_dir == str(record.artifact_dir)
