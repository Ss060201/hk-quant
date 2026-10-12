"""Data provenance and version metadata.

Each dataset should be able to answer: where did it come from, when was it
ingested, and which data version does it belong to.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Union

PathLike = Union[str, os.PathLike[str]]


@dataclass
class DataProvenance:
    """Metadata describing one dataset's origin and version."""

    source: str
    ingested_at: str
    data_version: str
    provider_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataProvenance":
        return cls(**data)


def make_data_version(prefix: str, run_date: date | None = None) -> str:
    """Build a version label such as ``HK_DAILY_2026_09_24``."""
    d = run_date or date.today()
    return f"{prefix}_{d.strftime('%Y_%m_%d')}"


def build_provenance(
    source: str,
    prefix: str,
    provider_version: str | None = None,
) -> DataProvenance:
    """Build a provenance record stamped with the current UTC time."""
    return DataProvenance(
        source=source,
        ingested_at=datetime.now(timezone.utc).isoformat(),
        data_version=make_data_version(prefix),
        provider_version=provider_version,
    )


def write_provenance(provenance: DataProvenance, root: PathLike, dataset: str) -> Path:
    """Write a provenance record to ``<root>/provenance/<dataset>.json``."""
    dest = Path(root) / "provenance"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{dataset}.json"
    path.write_text(
        json.dumps(provenance.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def read_provenance(root: PathLike, dataset: str) -> DataProvenance:
    """Read a provenance record from ``<root>/provenance/<dataset>.json``."""
    path = Path(root) / "provenance" / f"{dataset}.json"
    if not path.exists():
        raise FileNotFoundError(f"no provenance record at {path}")
    return DataProvenance.from_dict(json.loads(path.read_text(encoding="utf-8")))


def hash_file(path: PathLike) -> str:
    """SHA-256 of a file's bytes, including all canonical Parquet columns."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(files: dict[str, str]) -> dict[str, Any]:
    """The version changes if any included path or file content changes."""
    canonical = dict(sorted(files.items()))
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {"schema_version": 1, "data_version": f"HK_DATA_{digest[:20]}",
            "sha256": digest, "files": canonical}


def build_data_manifest(processed_dir: PathLike) -> dict[str, Any]:
    """Fingerprint the current processed Parquet files, independent of the clock.

    This identifies exact bytes and is not a snapshot. Retain the raw inputs or
    a processed snapshot to reproduce a prior version after source data changes.
    """
    root = Path(processed_dir)
    files = {path.relative_to(root).as_posix(): hash_file(path)
             for path in sorted(root.rglob("*.parquet"))} if root.exists() else {}
    return _manifest(files)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_data_manifest(processed_dir: PathLike, manifest: dict[str, Any]) -> Path:
    """Persist the current fingerprint; archive a copy with each experiment."""
    root = Path(processed_dir)
    path = root / "provenance" / "manifest.json"
    _write_json_atomic(path, manifest)
    return path


def read_data_manifest(processed_dir: PathLike) -> dict[str, Any]:
    path = Path(processed_dir) / "provenance" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def update_data_manifest(
    processed_dir: PathLike, changed_paths: list[Path]
) -> dict[str, Any]:
    """Update a manifest for files written by DataStorage, hashing changed files.

    Use :func:`build_data_manifest` for full verification after out-of-band
    edits to processed files. This method assumes one writer at a time.
    """
    root = Path(processed_dir)
    try:
        previous = read_data_manifest(root)
        files = dict(previous["files"])
        if previous.get("schema_version") != 1 or not isinstance(files, dict):
            raise ValueError("unexpected manifest schema")
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        manifest = build_data_manifest(root)
    else:
        for path in changed_paths:
            path = Path(path)
            rel = path.relative_to(root).as_posix()
            if path.exists():
                files[rel] = hash_file(path)
            else:
                files.pop(rel, None)
        manifest = _manifest(files)
    write_data_manifest(root, manifest)
    return manifest


def get_data_version(processed_dir: PathLike) -> str:
    """Return a verified content-based version; refresh stale manifests."""
    root = Path(processed_dir)
    actual = build_data_manifest(root)
    try:
        stored = read_data_manifest(root)
    except (FileNotFoundError, ValueError):
        stored = None
    if stored != actual:
        write_data_manifest(root, actual)
    return actual["data_version"]
