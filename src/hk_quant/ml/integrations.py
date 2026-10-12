"""Record a conditional outcome evaluation with its real inputs or block it."""

from __future__ import annotations

from typing import Any

import pandas as pd

from hk_quant.ml.models import ConditionalDataset, ConditionalModelResult


def _records(frame: pd.DataFrame) -> list[dict]:
    cleaned = frame.astype(object).where(pd.notna(frame), None)
    return cleaned.to_dict(orient="records")


def register_conditional_result(
    result: ConditionalModelResult,
    dataset: ConditionalDataset,
    registry: Any,
) -> Any:
    """Immutable record includes the labeled snapshot used in evaluation.

    Saving complete input samples is intentional: a model version without
    dated features/labels cannot be reproduced merely by storing a random
    seed and a statement about the code version. Provider raw data stays in
    its own data store; this file holds only the selected experiment samples.
    """
    if (result.strategy_id, result.strategy_version, result.data_version,
        result.feature_columns, result.label_definition) != (
        dataset.strategy_id, dataset.strategy_version, dataset.data_version,
        dataset.feature_columns, dataset.label_definition
    ):
        raise ValueError("result and dataset provenance mismatch")
    config = {"label_definition": dataset.label_definition,
              "feature_source": dataset.feature_source,
              "feature_columns": list(dataset.feature_columns),
              "model_config": result.model_config,
              "split_config": result.split_config,
              "discarded": dataset.discarded}
    record = registry.create_experiment(
        "conditional_outcome_ml", config,
        research_question="Which fixed-strategy BUY signals suffer >5% raw price loss over 20 trading days?",
        strategy_id=dataset.strategy_id, strategy_version=dataset.strategy_version,
        data_version=dataset.data_version, seed=result.model_config.get("seed"),
        warnings=result.warnings,
    )
    try:
        registry.update_experiment_status(record.experiment_id, "RUNNING")
        registry.save_artifact(record.experiment_id, "dataset.json", _records(dataset.samples))
        registry.save_artifact(record.experiment_id, "predictions.json", _records(result.predictions))
        registry.save_artifact(record.experiment_id, "summary.json", {
            "status": result.status, "model_version": result.model_version,
            "label_definition": result.label_definition,
            "feature_columns": result.feature_columns,
            "fold_metrics": result.fold_metrics,
            "strategy_comparison": result.strategy_comparison,
            "comparison_status": result.comparison_status,
            "warnings": result.warnings,
        })
        completed = registry.update_experiment_status(
            record.experiment_id, "COMPLETED" if result.status == "EVALUATED" else "BLOCKED",
            conclusion="OOS conditional failure classification" if result.status == "EVALUATED" else "Insufficient real data or missing ML dependency",
        )
        result.experiment_id = completed.experiment_id
        return completed
    except Exception:
        registry.update_experiment_status(record.experiment_id, "FAILED")
        raise
