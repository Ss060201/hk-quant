"""Research result artifacts: summary.json, parquet tables, config copy."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Union

import pandas as pd
import yaml

from hk_quant.research.models import ResearchResult

PathLike = Union[str, os.PathLike[str]]


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def build_summary(result: ResearchResult) -> dict[str, Any]:
    """Build the summary.json dictionary for a research result."""
    return {
        "research_id": result.research_id,
        "research_name": result.name,
        "data_version": result.data_version,
        "parameters": result.parameters,
        "date_range": result.parameters.get("date_range"),
        "universe_definition": result.parameters.get("universe"),
        "variable": result.parameters.get("variable"),
        "thresholds": result.parameters.get("variable", {}).get("thresholds"),
        "forward_periods": result.parameters.get("forward_periods"),
        "return_definition": result.parameters.get("return"),
        "event_mode": result.parameters.get("event_mode"),
        "sample_counts": _jsonable(
            result.statistics[
                ["threshold", "forward_period", "sample_count", "valid_sample_count"]
            ].to_dict(orient="records")
        ),
        "summary_statistics": _jsonable(
            result.statistics.to_dict(orient="records")
        ),
        "relationship_analysis": _jsonable(result.relationship_analysis),
        "warnings": result.warnings,
        "conclusion_status": result.status.value,
        "tested_combinations": result.tested_combinations,
        "exploratory_research": result.exploratory,
    }


def save_research_result(
    result: ResearchResult,
    output_dir: PathLike,
) -> Path:
    """Save config, summary.json, events.parquet and forward_returns.parquet."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    summary_path = root / "summary.json"
    summary_path.write_text(
        json.dumps(build_summary(result), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )

    result.events.to_parquet(root / "events.parquet", index=False)
    result.forward_returns.to_parquet(root / "forward_returns.parquet", index=False)

    config_path = root / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(result.parameters, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return root
