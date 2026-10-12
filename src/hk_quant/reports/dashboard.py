"""Offline, read-only HTML index of registered experiment artifacts.

No price/factor/return computation lives in this presentation module.
HTML is escaped and artifact links are restricted to the Registry root.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote


def _show(value: Any) -> str:
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if value is None:
        value = "unavailable"
    return html.escape(str(value), quote=True)


def _artifact(record: Any, name: str, artifacts_root: Path) -> Path | None:
    """Reject unexpected locations and changed results before displaying them."""
    if name not in record.artifacts:
        return None
    path = record.artifact_dir / name
    if not path.is_file() or not path.resolve().is_relative_to(artifacts_root.resolve()):
        return None
    if hashlib.sha256(path.read_bytes()).hexdigest() != record.artifacts[name]:
        return None
    return path


def render_dashboard(registry: Any, coverage: Mapping[str, Any], *, limit: int = 50, output: str | Path) -> Path:
    """Build a local dashboard from existing immutable experiment records.

    This is a static artifact viewer. Research creation stays in the bounded
    agent tool protocol; no web server, credentials or order endpoints exist.
    """
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be 1–100")
    root = Path(output)
    root.parent.mkdir(parents=True, exist_ok=True)
    records = registry.list_experiments(limit=limit)
    lines = [
        "<!doctype html>",
        '<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>HK Quant｜研究紀錄</title>",
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#193140;background:#f6f8fa}h1,h2{color:#123047}section,details{background:white;border:1px solid #d5e0e6;border-radius:.6rem;padding:1rem;margin:1rem 0}summary{cursor:pointer;font-weight:700}table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}td,th{text-align:left;border-bottom:1px solid #d5e0e6;padding:.45rem}pre{overflow:auto;white-space:pre-wrap;word-break:break-word}a{color:#176997}.warn{color:#a84913}.state{font-weight:700}</style>",
        "</head><body><h1>HK Quant｜研究紀錄</h1>",
        "<p>本頁只展示已儲存的結果。探索性結果不代表策略經驗證。沒有連接真實交易帳戶。</p>",
        "<section><h2>資料狀態</h2><pre>" + _show(coverage) + "</pre></section>",
        "<section><h2>實驗</h2>",
    ]
    if not records:
        lines.append("<p>尚未登記實驗。</p>")
    for record in records:
        title = f"{record.experiment_type} · {record.status} · {record.experiment_id}"
        lines.extend([
            "<details><summary>" + _show(title) + "</summary>",
            "<p>Config hash: " + _show(record.config_hash) + " · Data version: " + _show(record.data_version) + "</p>",
            "<p>Research question: " + _show(record.research_question) + "</p>",
            "<p>Conclusion: <span class=state>" + _show(record.conclusion) + "</span></p>",
            "<p>Config:</p><pre>" + _show(record.config) + "</pre>",
        ])
        if record.warnings:
            lines.append('<p class="warn">Warnings:</p><ul>')
            lines.extend("<li>" + _show(warning) + "</li>" for warning in record.warnings)
            lines.append("</ul>")
        summary = _artifact(record, "summary.json", registry.artifacts_root)
        if summary is None:
            lines.append("<p>沒有可校驗的 summary.json；結果不可用。</p>")
        else:
            data = json.loads(summary.read_text(encoding="utf-8"))
            href = html.escape(quote(os.path.relpath(summary, root.parent).replace(os.sep, "/"), safe="/.-_"), quote=True)
            lines.append('<p><a href="' + href + '">下載原始 summary.json</a></p>')
            if record.experiment_type == "research":
                lines.append("<p>Research classification: " + _show(data.get("conclusion_status")) + "</p>")
                lines.append("<p>Recorded sample counts: " + _show(data.get("sample_counts")) + "</p>")
                lines.append("<p>Recorded relationship analysis: " + _show(data.get("relationship_analysis")) + "</p>")
            elif record.experiment_type == "backtest":
                lines.append("<p>Recorded metrics: " + _show(data.get("metrics")) + "</p>")
            else:
                lines.append("<pre>" + _show(data) + "</pre>")
        lines.append("</details>")
    lines.append("</section></body></html>")
    with root.open("x", encoding="utf-8") as destination:
        destination.write("\n".join(lines) + "\n")
    return root
