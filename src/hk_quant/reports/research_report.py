"""Evidence-linked Markdown report built from an existing summary artifact.

The renderer does not calculate or infer any quantitative result. Every number
in its table is copied from a named result field and retains its stored value.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

_ID = re.compile(r"[a-f0-9]{32}\Z")
_STATS = ("threshold", "forward_period", "sample_count", "valid_sample_count", "mean", "median", "win_rate", "ci_lower", "ci_upper")


def _cell(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return json.dumps(value, allow_nan=False)
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    elif isinstance(value, list):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False)
    return re.sub(r"([\\|\[\]<>`*_])", r"\\\1", str(value).replace("\n", " ").replace("\r", " "))


def render_research_report(summary: Mapping[str, Any], *, experiment_id: str | None = None, source: str = "summary.json") -> str:
    """Render saved facts and clearly labeled limitations.

    ``experiment_id`` must be an issued Registry ID. Older standalone files
    are labeled unregistered; a filename or research_id does not become a run
    ID by implication. ``source`` is descriptive text, never a raw link.
    """
    if experiment_id is not None and not _ID.fullmatch(experiment_id):
        raise ValueError("experiment_id must be a Registry UUID hex value")
    if not isinstance(summary, Mapping):
        raise TypeError("summary must be a mapping")
    if not isinstance(summary.get("summary_statistics"), list):
        raise ValueError("summary_statistics array is required")
    rows = summary["summary_statistics"]
    if len(rows) > 1000:
        raise ValueError("report refuses to render more than 1000 statistic rows")
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("summary_statistics rows must be mappings")

    params = summary.get("parameters") if isinstance(summary.get("parameters"), Mapping) else {}
    universe = summary.get("universe_definition") or params.get("universe")
    period = summary.get("date_range") or params.get("date_range")
    warnings = summary.get("warnings") or []
    if not isinstance(warnings, list):
        raise ValueError("warnings must be an array")
    exploratory = summary.get("exploratory_research", True)
    status = summary.get("conclusion_status", "unavailable")
    lines = [
        f"# Research report: {_cell(summary.get('research_name') or summary.get('research_id') or 'unnamed')}",
        "",
        f"- Experiment ID: `{experiment_id}`" if experiment_id else "- Experiment ID: unavailable (standalone, unregistered result)",
        f"- Source: {_cell(source)} (`summary.json`)",
        f"- Status field: `{_cell(status)}` (exploratory classification, **not** evidence of an investable strategy)",
        f"- Exploratory: {_cell(exploratory)}",
        "",
        "## Question and method",
        "",
        f"- Research question/name: {_cell(summary.get('research_name') or summary.get('research_id'))}",
        f"- Variable and thresholds (`variable`): {_cell(summary.get('variable') or params.get('variable'))}",
        f"- Forward periods (`forward_periods`): {_cell(summary.get('forward_periods') or params.get('forward_periods'))}",
        f"- Return definition (`return_definition`): {_cell(summary.get('return_definition') or params.get('return'))}",
        f"- Event mode (`event_mode`): {_cell(summary.get('event_mode') or params.get('event_mode'))}",
        f"- Date range (`date_range`): {_cell(period)}",
        f"- Universe (`universe_definition`): {_cell(universe)}",
        f"- Data version (`data_version`): {_cell(summary.get('data_version'))}",
        f"- Tested combinations (`tested_combinations`): {_cell(summary.get('tested_combinations'))}",
        "",
        "## Recorded statistics",
        "",
        "Every value below is copied from `summary_statistics` in the saved result; missing cells are shown as unavailable.",
        "",
        "| " + " | ".join(_STATS) + " |",
        "| " + " | ".join("---" for _ in _STATS) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(row.get(field)) for field in _STATS) + " |")
    lines += [
        "",
        "## Recorded relationship analysis",
        "",
        "The following JSON is copied from `relationship_analysis`; overlapping events and multiple comparisons can weaken the evidence.",
        "",
        "```json",
        json.dumps(summary.get("relationship_analysis", {}), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False),
        "```",
        "",
        "## Limits and warnings",
        "",
    ]
    if not warnings:
        lines.append("- No warnings were recorded; this does not establish completeness of the data.")
    else:
        lines.extend(f"- {_cell(warning)}" for warning in warnings)
    lines += [
        "- Baseline, out-of-sample testing, costs, risk, ML and news are unavailable in this research artifact unless separately linked to registered experiments.",
        "- The summary is a research observation and does not authorize an order.",
        "",
        "## Reproducibility",
        "",
        "Inspect the source `summary.json`, `config.yaml`, and the Experiment Registry (when an experiment ID exists).",
        "",
    ]
    return "\n".join(lines)


def render_report_file(source: Path, destination: Path, *, experiment_id: str | None = None) -> Path:
    """Write a new report from a trusted local summary; never overwrite."""
    if not source.is_file():
        raise FileNotFoundError(source)
    summary = json.loads(source.read_text(encoding="utf-8"))
    rendered = render_research_report(summary, experiment_id=experiment_id, source=source.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as output:
        output.write(rendered)
    return destination
