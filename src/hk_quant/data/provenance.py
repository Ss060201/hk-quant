"""Data provenance and version metadata.

Each dataset should be able to answer: where did it come from, when was it
ingested, and which data version does it belong to.
"""

from __future__ import annotations

import json
import os
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
