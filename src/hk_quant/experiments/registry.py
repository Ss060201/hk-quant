"""SQLite experiment index with one immutable artifact directory per run.

The registry records *provided* data versions. It cannot infer a content version
from an ingestion date or reconstruct unavailable historical data provenance.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


def _normalize(value: Any) -> Any:
    """Convert supported configuration values to unambiguous JSON values."""
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("configuration object keys must be strings")
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # Accept numpy scalars without importing numpy or altering native Python values.
    if hasattr(value, "item"):
        return _normalize(value.item())
    raise TypeError(f"configuration contains unsupported type: {type(value).__name__}")


def canonical_config(config: Mapping[str, Any]) -> str:
    """Produce stable JSON, rejecting non-JSON numbers and unordered containers."""
    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")
    return json.dumps(
        _normalize(config), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def config_hash(config: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_config(config).encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(_normalize(value), ensure_ascii=False, sort_keys=True, allow_nan=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _commit(root: Path) -> str | None:
    try:
        process = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=True, timeout=2, text=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    result = process.stdout.strip()
    return result if len(result) == 40 else None


def _libraries() -> dict[str, str]:
    versions = {"python": sys.version.split()[0]}
    for name in ("hk-quant", "pandas", "numpy"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            pass
    return versions


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    experiment_type: str
    created_at: str
    updated_at: str
    status: str
    research_question: str
    strategy_id: str | None
    strategy_version: str | None
    strategy_hash: str | None
    data_version: str
    factor_versions: dict[str, str]
    code_commit: str | None
    config: dict[str, Any]
    config_hash: str
    date_range: dict[str, Any]
    universe: dict[str, Any]
    cost_assumptions: dict[str, Any]
    seed: int | None
    library_versions: dict[str, str]
    artifact_dir: Path
    artifacts: dict[str, str]  # filename -> SHA256 of the saved snapshot
    warnings: list[str]
    conclusion: str | None


class ExperimentRegistry:
    """Local SQLite metadata, with content-checked files under ``root/artifacts``.

    Completed/failed/blocked records are terminal. Rerunning the same config
    creates a new record, retaining every earlier artifact and config snapshot.
    """

    _TERMINAL = frozenset({"COMPLETED", "FAILED", "BLOCKED"})
    _STATUSES = _TERMINAL | {"CREATED", "RUNNING"}

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()
        self.artifacts_root = self.root / "artifacts"
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "registry.sqlite3"
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS experiments (
                       experiment_id TEXT PRIMARY KEY,
                       experiment_type TEXT NOT NULL,
                       status TEXT NOT NULL,
                       config_hash TEXT NOT NULL,
                       created_at TEXT NOT NULL,
                       metadata TEXT NOT NULL
                   )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_experiment_search "
                "ON experiments(experiment_type, status, config_hash, created_at)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_experiment(
        self,
        experiment_type: str,
        config: Mapping[str, Any],
        *,
        research_question: str = "",
        strategy_id: str | None = None,
        strategy_version: str | None = None,
        strategy_hash: str | None = None,
        data_version: str | None = None,
        factor_versions: Mapping[str, str] | None = None,
        code_commit: str | None = None,
        date_range: Mapping[str, Any] | None = None,
        universe: Mapping[str, Any] | None = None,
        cost_assumptions: Mapping[str, Any] | None = None,
        seed: int | None = None,
        library_versions: Mapping[str, str] | None = None,
        warnings: Sequence[str] | None = None,
    ) -> ExperimentRecord:
        if not experiment_type or not experiment_type.strip():
            raise ValueError("experiment_type is required")
        canonical = canonical_config(config)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        experiment_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        resolved_data_version = data_version or "unavailable"
        stored_warnings = list(warnings or ())
        if resolved_data_version == "unavailable":
            stored_warnings.append("data_version unavailable: reproducibility cannot be verified")
        elif resolved_data_version.startswith("HK_DAILY_") and len(resolved_data_version) == 19:
            stored_warnings.append(
                "date-labeled data_version does not verify dataset contents; "
                "supply a manifest or content-derived version for exact reproduction"
            )
        record = {
            "experiment_id": experiment_id,
            "experiment_type": experiment_type.strip(),
            "created_at": now,
            "updated_at": now,
            "status": "CREATED",
            "research_question": research_question,
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "strategy_hash": strategy_hash,
            "data_version": resolved_data_version,
            "factor_versions": _normalize(factor_versions or {}),
            "code_commit": code_commit or _commit(self.root),
            "config": json.loads(canonical),
            "config_hash": digest,
            "date_range": _normalize(date_range or {}),
            "universe": _normalize(universe or {}),
            "cost_assumptions": _normalize(cost_assumptions or {}),
            "seed": seed,
            "library_versions": _normalize(library_versions or _libraries()),
            "artifact_dir": f"artifacts/{experiment_id}",
            "artifacts": {},
            "warnings": stored_warnings,
            "conclusion": None,
        }
        directory = self.artifacts_root / experiment_id
        directory.mkdir(mode=0o700)
        config_path = directory / "config.json"
        try:
            with config_path.open("x", encoding="utf-8") as destination:
                destination.write(canonical + "\n")
            record["artifacts"]["config.json"] = _sha256(config_path)
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?)",
                    (experiment_id, record["experiment_type"], "CREATED", digest, now, _json(record)),
                )
        except Exception:
            shutil.rmtree(directory)
            raise
        return self._record(record)

    def _record(self, data: dict[str, Any]) -> ExperimentRecord:
        stored = data.copy()
        stored["artifact_dir"] = self.root / stored["artifact_dir"]
        return ExperimentRecord(**stored)

    def get_experiment(self, experiment_id: str) -> ExperimentRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT metadata FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"experiment does not exist: {experiment_id}")
        return self._record(json.loads(row["metadata"]))

    def list_experiments(
        self,
        *,
        experiment_type: str | None = None,
        status: str | None = None,
        config_hash: str | None = None,
        strategy_id: str | None = None,
        data_version: str | None = None,
        limit: int = 100,
    ) -> list[ExperimentRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        clauses, values = [], []
        for column, value in (("experiment_type", experiment_type),
                              ("status", status), ("config_hash", config_hash)):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT metadata FROM experiments" + where + " ORDER BY created_at DESC",
                values,
            ).fetchall()
        records = [self._record(json.loads(row["metadata"])) for row in rows]
        if strategy_id is not None:
            records = [record for record in records if record.strategy_id == strategy_id]
        if data_version is not None:
            records = [record for record in records if record.data_version == data_version]
        return records[:limit]

    def _edit(self, experiment_id: str, modify: Any) -> ExperimentRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT metadata FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"experiment does not exist: {experiment_id}")
            data = json.loads(row["metadata"])
            if data["status"] in self._TERMINAL:
                raise ValueError(f"experiment is immutable in {data['status']} status")
            modify(data)
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "UPDATE experiments SET status = ?, metadata = ? WHERE experiment_id = ?",
                (data["status"], _json(data), experiment_id),
            )
        return self._record(data)

    def update_experiment_status(
        self,
        experiment_id: str,
        status: str,
        *,
        conclusion: str | None = None,
        warnings: Sequence[str] | None = None,
    ) -> ExperimentRecord:
        if status not in self._STATUSES or status == "CREATED":
            raise ValueError(f"invalid target status: {status}")

        def update(data: dict[str, Any]) -> None:
            if status == "COMPLETED":
                self._verify(data)
            data["status"] = status
            if conclusion is not None:
                data["conclusion"] = conclusion
            for warning in warnings or ():
                if warning not in data["warnings"]:
                    data["warnings"].append(warning)

        return self._edit(experiment_id, update)

    def _artifact_path(self, data: dict[str, Any], name: str) -> Path:
        if not name or Path(name).name != name or name in {".", ".."} or "\\" in name:
            raise ValueError("artifact name must be a simple filename")
        directory = self.root / data["artifact_dir"]
        path = directory / name
        if path.parent.resolve() != directory.resolve() or path.is_symlink():
            raise ValueError("artifact must remain inside its experiment directory")
        return path

    def _register_existing(self, experiment_id: str, name: str) -> ExperimentRecord:
        def update(data: dict[str, Any]) -> None:
            path = self._artifact_path(data, name)
            if name in data["artifacts"]:
                raise FileExistsError(f"artifact already registered: {name}")
            if not path.is_file():
                raise FileNotFoundError(f"missing artifact: {path}")
            data["artifacts"][name] = _sha256(path)

        return self._edit(experiment_id, update)

    def save_artifact(self, experiment_id: str, name: str, content: Any) -> Path:
        """Save one new JSON, Parquet, text, or binary artifact before completion."""
        record = self.get_experiment(experiment_id)
        if record.status in self._TERMINAL:
            raise ValueError(f"experiment is immutable in {record.status} status")
        data = asdict(record)
        data["artifact_dir"] = f"artifacts/{experiment_id}"
        path = self._artifact_path(data, name)
        if path.exists():
            raise FileExistsError(f"artifact already exists: {path}")
        try:
            if name.endswith(".json"):
                with path.open("x", encoding="utf-8") as destination:
                    destination.write(_json(content) + "\n")
            elif name.endswith(".parquet"):
                import pandas as pd

                if not isinstance(content, pd.DataFrame):
                    raise TypeError("Parquet artifact requires a pandas DataFrame")
                content.to_parquet(path, index=False)
            elif isinstance(content, str) and name.endswith((".txt", ".md")):
                with path.open("x", encoding="utf-8") as destination:
                    destination.write(content)
            elif isinstance(content, bytes):
                with path.open("xb") as destination:
                    destination.write(content)
            else:
                raise TypeError(f"unsupported artifact content for {name}")
            self._register_existing(experiment_id, name)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    def attach_artifact(self, experiment_id: str, source: str | os.PathLike[str], name: str | None = None) -> Path:
        """Copy an already generated file into the run's immutable snapshot."""
        record = self.get_experiment(experiment_id)
        if record.status in self._TERMINAL:
            raise ValueError(f"experiment is immutable in {record.status} status")
        source_path = Path(source)
        artifact_name = name or source_path.name
        data = asdict(record)
        data["artifact_dir"] = f"artifacts/{experiment_id}"
        destination = self._artifact_path(data, artifact_name)
        if source_path.resolve() == destination.resolve():
            self._register_existing(experiment_id, artifact_name)
            return destination
        if destination.exists():
            raise FileExistsError(f"artifact already exists: {destination}")
        if not source_path.is_file():
            raise FileNotFoundError(f"missing source artifact: {source_path}")
        try:
            with source_path.open("rb") as reader, destination.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            self._register_existing(experiment_id, artifact_name)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return destination

    def _verify(self, data: dict[str, Any]) -> None:
        for name, digest in data["artifacts"].items():
            path = self._artifact_path(data, name)
            if not path.is_file():
                raise FileNotFoundError(f"missing artifact: {path}")
            if _sha256(path) != digest:
                raise ValueError(f"artifact content changed: {path}")

    def load_experiment_artifacts(self, experiment_id: str) -> dict[str, Any]:
        """Verify recorded checksums, then load JSON, Parquet and other files."""
        record = self.get_experiment(experiment_id)
        data = asdict(record)
        data["artifact_dir"] = f"artifacts/{experiment_id}"
        self._verify(data)
        loaded: dict[str, Any] = {}
        for name in record.artifacts:
            path = self._artifact_path(data, name)
            if name.endswith(".json"):
                loaded[name] = json.loads(path.read_text(encoding="utf-8"))
            elif name.endswith(".parquet"):
                import pandas as pd

                loaded[name] = pd.read_parquet(path)
            elif name.endswith((".txt", ".md", ".yaml", ".yml")):
                loaded[name] = path.read_text(encoding="utf-8")
            else:
                loaded[name] = path.read_bytes()
        return loaded

    def compare_experiments(self, experiment_ids: Sequence[str]) -> dict[str, Any]:
        """Compare config, provenance and saved JSON summaries across runs."""
        if len(experiment_ids) < 2:
            raise ValueError("compare_experiments requires at least two IDs")
        records = [self.get_experiment(experiment_id) for experiment_id in experiment_ids]
        rows = []
        for record in records:
            artifacts = self.load_experiment_artifacts(record.experiment_id)
            rows.append({
                "experiment_id": record.experiment_id,
                "experiment_type": record.experiment_type,
                "status": record.status,
                "config_hash": record.config_hash,
                "config": record.config,
                "data_version": record.data_version,
                "strategy_hash": record.strategy_hash,
                "warnings": record.warnings,
                "conclusion": record.conclusion,
                "summary": artifacts.get("summary.json"),
            })
        fields = ("experiment_type", "status", "config_hash", "config", "data_version",
                  "strategy_hash", "warnings", "conclusion", "summary")
        differences = {
            field: {row["experiment_id"]: row[field] for row in rows}
            for field in fields
            if len({_json(row[field]) for row in rows}) > 1
        }
        return {"experiments": rows, "differences": differences}

    def register_research_result(
        self, result: Any, *, research_question: str = "",
        strategy_id: str | None = None, strategy_version: str | None = None,
        strategy_hash: str | None = None, seed: int | None = None,
    ) -> ExperimentRecord:
        """Snapshot a Phase 4 ResearchResult with its standard files."""
        from hk_quant.research.results import save_research_result

        config = result.parameters
        record = self.create_experiment(
            "research", config, research_question=research_question or result.name,
            strategy_id=strategy_id, strategy_version=strategy_version,
            strategy_hash=strategy_hash, data_version=result.data_version,
            date_range=config.get("date_range"), universe=config.get("universe"),
            warnings=result.warnings, seed=seed,
        )
        try:
            self.update_experiment_status(record.experiment_id, "RUNNING")
            save_research_result(result, record.artifact_dir)
            for name in ("summary.json", "events.parquet", "forward_returns.parquet", "config.yaml"):
                self.attach_artifact(record.experiment_id, record.artifact_dir / name)
            return self.update_experiment_status(
                record.experiment_id, "COMPLETED", conclusion=result.status.value,
            )
        except Exception:
            self.update_experiment_status(record.experiment_id, "FAILED")
            raise

    def register_backtest_result(self, result: Any, *, research_question: str = "") -> ExperimentRecord:
        """Snapshot a Phase 7 BacktestResult without modifying its calculations."""
        from hk_quant.backtest.results import save_backtest

        from dataclasses import asdict as to_dict

        config = to_dict(result.config) if is_dataclass(result.config) else result.config
        metadata = result.metadata
        record = self.create_experiment(
            "backtest", config, research_question=research_question,
            strategy_id=metadata.get("strategy_id"),
            strategy_version=metadata.get("strategy_version"),
            strategy_hash=metadata.get("strategy_hash"),
            data_version=metadata.get("data_version"),
            factor_versions=metadata.get("factor_versions"),
            date_range={"start": metadata.get("start_date"), "end": metadata.get("end_date")},
            universe={"mode": metadata.get("universe")},
            cost_assumptions=metadata.get("assumptions", {}),
            warnings=result.warnings,
        )
        try:
            self.update_experiment_status(record.experiment_id, "RUNNING")
            # Backtest's own writer also produces config.json. Write in an
            # isolated staging dir so it cannot replace the canonical config
            # snapshot created with the experiment.
            with tempfile.TemporaryDirectory(prefix="backtest-", dir=self.root) as temporary:
                staging = Path(temporary)
                save_backtest(result, staging)
                for path in staging.iterdir():
                    if path.is_file() and path.name != "config.json":
                        self.attach_artifact(record.experiment_id, path)
                if (staging / "config.json").is_file():
                    self.attach_artifact(
                        record.experiment_id, staging / "config.json", "backtest_config.json"
                    )
            completed = self.update_experiment_status(
                record.experiment_id, "COMPLETED",
                conclusion=metadata.get("status", "EXPLORATORY"),
            )
            try:
                result.artifact_dir = str(completed.artifact_dir)
            except (AttributeError, TypeError):
                pass  # Some result dataclasses are intentionally immutable.
            return completed
        except Exception:
            self.update_experiment_status(record.experiment_id, "FAILED")
            raise
