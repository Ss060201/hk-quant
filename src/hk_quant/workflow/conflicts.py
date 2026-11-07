"""Persistent unresolved conflicts, including preparation reports from older versions.

Evidence is never silently cleared by a successful retry. Resolution is a separate
reviewed data correction; this module deliberately has no mark-all-resolved switch.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from pathlib import Path

import pandas as pd

from hk_quant.data.storage import DataStorage


class ConflictHistoryError(ValueError):
    """Fail closed when evidence cannot be read or durably recorded."""


def _read(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        rows = value["conflicts"]
        if not isinstance(rows, list):
            raise ValueError("conflicts must be a list")
        return rows
    except (ValueError, KeyError, TypeError) as exc:
        raise ConflictHistoryError(f"CONFLICT_HISTORY_UNREADABLE: {path}") from exc


def collect_conflicts(root, new=()):
    root = Path(root)
    ledger = root / "quality" / "unresolved_conflicts.json"
    rows = _read(ledger) if ledger.exists() else []
    # Import earlier reports as well: an upgrade must not forget past conflicts.
    for path in sorted((root / "preparations").glob("*/report.json")):
        rows.extend(_read(path))
    rows.extend(new)
    unique = {}
    for raw in rows:
        if not isinstance(raw, dict) or not {"stock_id", "date", "fields"}.issubset(raw):
            raise ConflictHistoryError("CONFLICT_HISTORY_INVALID_RECORD")
        row = dict(raw)
        row.pop("conflict_id", None)
        row["date"] = str(pd.Timestamp(row["date"]).date())
        if row["date"] == "NaT" or not isinstance(row["fields"], list) or not row["fields"]:
            raise ConflictHistoryError("CONFLICT_HISTORY_INVALID_RECORD")
        row["fields"] = sorted(row["fields"])
        digest = hashlib.sha256(json.dumps(row, sort_keys=True, allow_nan=False).encode()).hexdigest()
        row["conflict_id"] = digest
        unique[digest] = row
    return list(unique.values())


def persist_conflicts(root, new=()):
    """Call under the preparation writer lock, BEFORE any processed writes."""
    try:
        rows = collect_conflicts(root, new)
        if rows:
            DataStorage._atomic_json({"schema_version": 1, "conflicts": rows},
                                     Path(root) / "quality" / "unresolved_conflicts.json")
    except (OSError, ValueError, TypeError) as exc:
        raise ConflictHistoryError(f"CONFLICT_HISTORY_NOT_SAVED: {exc}") from exc
    return rows


def relevant_conflicts(spec, rows):
    # Warmup observations can affect scores even before the requested start.
    start = (pd.Timestamp(spec.start) - pd.Timedelta(days=spec.warmup_days)).date().isoformat()
    return [r for r in rows if r["stock_id"] in spec.stocks and start <= r["date"] <= spec.end]


def conflict_blockers(spec, root):
    rows = relevant_conflicts(spec, unresolved_conflicts(root))
    return ([f"UNRESOLVED_SOURCE_CONFLICT: {len(rows)} records; review quality/unresolved_conflicts.json and preparation reports"]
            if rows else [])


def unresolved_conflicts(root, rows=None, *, storage=None):
    """A reviewed resolution applies only while the saved values still match."""
    root = Path(root)
    rows = collect_conflicts(root) if rows is None else rows
    accepted = {}
    for path in sorted((root / "quality" / "resolutions").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            evidence = path.with_suffix(".evidence")
            if hashlib.sha256(evidence.read_bytes()).hexdigest() != record["evidence_sha256"]:
                raise ValueError("resolution evidence checksum mismatch")
            previous = accepted.get(record["conflict_id"])
            if previous is None or record["recorded_at"] > previous["recorded_at"]:
                accepted[record["conflict_id"]] = record
        except (OSError, ValueError, KeyError) as exc:
            raise ConflictHistoryError(f"RESOLUTION_UNREADABLE: {path}") from exc
    if not accepted:
        return rows
    storage = storage or DataStorage(root / "raw", root / "processed")
    open_rows = []
    for row in rows:
        record = accepted.get(row["conflict_id"])
        if record is None:
            open_rows.append(row)
            continue
        frame = storage.load_daily_prices(row["stock_id"], row["date"], row["date"])
        if len(frame) != 1 or any(
            c not in record["accepted_values"] or c not in frame or
            not math.isclose(float(frame.iloc[0][c]), float(record["accepted_values"][c]), rel_tol=0, abs_tol=1e-12)
            for c in row["fields"]
        ):
            open_rows.append(row)
    return open_rows


def resolve_conflict(root, request_path, *, storage=None):
    """Record a human/agent-reviewed decision; NEVER change market values here.

    Call under writer_lock. Evidence attribution is an operator assertion, not
    automatic authentication of the source's correctness.
    """
    root, request_path = Path(root), Path(request_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    for key in ("conflict_id", "reason", "source_url", "reviewed_by", "evidence_file"):
        if not isinstance(request.get(key), str) or not request[key].strip():
            raise ValueError(f"resolution requires {key}")
    if not request["source_url"].startswith(("https://", "http://")):
        raise ValueError("resolution requires a source URL")
    rows = persist_conflicts(root)
    matches = [r for r in rows if r["conflict_id"] == request["conflict_id"]]
    if len(matches) != 1:
        raise ValueError("unknown conflict_id")
    row = matches[0]
    values = request.get("accepted_values", {})
    if set(values) != set(row["fields"]) or any(isinstance(v, bool) or not math.isfinite(float(v)) for v in values.values()):
        raise ValueError("accepted_values must contain every disputed field and finite numbers")
    storage = storage or DataStorage(root / "raw", root / "processed")
    frame = storage.load_daily_prices(row["stock_id"], row["date"], row["date"])
    if len(frame) != 1 or any(c not in frame or not math.isclose(float(frame.iloc[0][c]), float(v), rel_tol=0, abs_tol=1e-12) for c, v in values.items()):
        raise ValueError("accepted values differ from stored data; apply a backed-up, reviewed correction first")
    evidence_path = Path(request["evidence_file"])
    if not evidence_path.is_absolute(): evidence_path = request_path.parent / evidence_path
    evidence = evidence_path.read_bytes()
    if not evidence:
        raise ValueError("empty evidence")
    directory = root / "quality" / "resolutions"
    directory.mkdir(parents=True, exist_ok=True)
    identity = uuid.uuid4().hex
    record = {k: request[k] for k in ("conflict_id", "reason", "source_url", "reviewed_by")}
    record.update(accepted_values={k: float(v) for k, v in values.items()},
                  evidence_sha256=hashlib.sha256(evidence).hexdigest(),
                  recorded_at=pd.Timestamp.now("UTC").isoformat())
    (directory / f"{identity}.evidence").write_bytes(evidence)
    DataStorage._atomic_json(record, directory / f"{identity}.json")
    return {"status": "RESOLUTION_RECORDED", "resolution_id": identity, "conflict_id": row["conflict_id"]}
