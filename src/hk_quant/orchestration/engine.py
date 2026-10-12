"""Connect deterministic candidate/risk/news tools without placing orders.

All inputs are injected so a missing data or news provider cannot be silently
replaced with guesses. The bounded packet is evidence for a human decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


@dataclass
class ResearchPacket:
    run_id: str
    strategy_id: str
    as_of_date: str
    candidates: list[dict[str, Any]]
    skipped_count: int
    warnings: list[str] = field(default_factory=list)
    as_of_at: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _known_at(value: Any, cutoff: datetime) -> bool:
    if not isinstance(value, str):
        return False
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return observed.tzinfo is not None and observed.astimezone(timezone.utc) <= cutoff


class ResearchOrchestrator:
    """A reproducible small-batch research coordinator, not a trading agent."""

    def __init__(
        self, *, candidate_tool: Callable[[str, str], Sequence[Mapping[str, Any]]],
        coverage_tool: Callable[[], Mapping[str, Any]],
        risk_tool: Callable[[str, str], Mapping[str, Any]],
        document_tool: Callable[[str, str], Sequence[Mapping[str, Any]]],
        output_dir: str | Path, max_candidates: int = 20, max_documents: int = 5,
    ) -> None:
        if max_candidates < 1 or max_documents < 0:
            raise ValueError("candidate budget must be positive; document budget nonnegative")
        self.candidate_tool = candidate_tool
        self.coverage_tool = coverage_tool
        self.risk_tool = risk_tool
        self.document_tool = document_tool
        self.output_dir = Path(output_dir)
        self.max_candidates = max_candidates
        self.max_documents = max_documents

    def run(self, strategy_id: str, as_of_date: str, *, strategy_hash: str,
            data_version: str, as_of_at: str | None = None) -> ResearchPacket:
        if not strategy_id or not strategy_hash or not data_version:
            raise ValueError("strategy id/hash and data version are required")
        day = datetime.fromisoformat(as_of_date).date().isoformat()
        # A date alone grants only facts known *before* the HK trading day.
        # An explicit, timezone-aware instant is required for later intraday facts.
        cutoff = (datetime.fromisoformat(as_of_at.replace("Z", "+00:00"))
                  if as_of_at is not None else
                  datetime.combine(datetime.fromisoformat(day).date(), time.min,
                                   ZoneInfo("Asia/Hong_Kong")))
        if cutoff.tzinfo is None or cutoff.astimezone(ZoneInfo("Asia/Hong_Kong")).date().isoformat() != day:
            raise ValueError("as_of_at must include a timezone and match as_of_date")
        cutoff_utc = cutoff.astimezone(timezone.utc)
        identity = [strategy_id, strategy_hash, day, cutoff_utc.isoformat(), data_version,
                    self.max_candidates, self.max_documents]
        run_id = hashlib.sha256(_canonical(identity).encode()).hexdigest()[:24]
        path = self.output_dir / f"{run_id}.json"
        if path.exists():
            return ResearchPacket(**json.loads(path.read_text(encoding="utf-8")))

        coverage = dict(self.coverage_tool())
        if coverage.get("status") == "BLOCKED":
            raise RuntimeError("required data coverage is blocked; research not run")
        all_candidates = [dict(item) for item in self.candidate_tool(strategy_id, day)]
        limited = all_candidates[:self.max_candidates]
        warnings: list[str] = []
        if coverage.get("status") != "AVAILABLE":
            warnings.append("data coverage was not confirmed AVAILABLE")
        if len(all_candidates) > len(limited):
            warnings.append(f"candidate budget reached; {len(all_candidates)-len(limited)} unprocessed")

        results: list[dict[str, Any]] = []
        for candidate in limited:
            stock_id = candidate.get("stock_id")
            if not isinstance(stock_id, str) or not stock_id:
                raise ValueError("candidate must include a stock_id")
            trigger = candidate.get("trigger_reason")
            if not trigger:
                raise ValueError("candidate must include a trigger_reason")
            if not candidate.get("rule_version") or not candidate.get("candidate_source"):
                raise ValueError("candidate requires trigger rule version and source")
            if not _known_at(candidate.get("available_at"), cutoff_utc):
                raise ValueError("candidate is not proven available as of research cutoff")
            try:
                risk = dict(self.risk_tool(stock_id, day))
                if not _known_at(risk.get("available_at"), cutoff_utc):
                    risk = {"status": "UNAVAILABLE", "reason": "RISK_AS_OF_UNVERIFIED"}
                    warnings.append(f"{stock_id}: risk availability unverified")
            except Exception as exc:
                risk = {"status": "UNAVAILABLE", "reason": type(exc).__name__}
                warnings.append(f"{stock_id}: risk tool unavailable")
            try:
                documents = [dict(doc) for doc in self.document_tool(stock_id, day)]
            except Exception as exc:
                documents = []
                warnings.append(f"{stock_id}: document tool unavailable ({type(exc).__name__})")
            for document in documents:
                available = document.get("available_at")
                if not _known_at(available, cutoff_utc):
                    raise ValueError("document is not proven available as of research date")
                if not document.get("source_id"):
                    raise ValueError("document has no source_id")
            if len(documents) > self.max_documents:
                warnings.append(f"{stock_id}: {len(documents)-self.max_documents} documents unprocessed")
            if not documents:
                warnings.append(f"{stock_id}: no source documents available")
            results.append({**candidate, "risk": risk,
                            "documents": documents[:self.max_documents],
                            "data_version": data_version, "strategy_hash": strategy_hash})

        packet = ResearchPacket(run_id, strategy_id, day, results,
                                len(all_candidates)-len(limited), warnings,
                                cutoff_utc.isoformat())
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Exclusive creation avoids silently changing a completed packet.
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(asdict(packet), stream, ensure_ascii=False, indent=2)
        except FileExistsError:
            return ResearchPacket(**json.loads(path.read_text(encoding="utf-8")))
        return packet

    @staticmethod
    def register_packet(packet: ResearchPacket, registry: Any, *, strategy_hash: str,
                        data_version: str) -> str:
        """Record an already computed packet and its assumptions immutably."""
        record = registry.create_experiment(
            "orchestration", {"run_id": packet.run_id, "as_of_at": packet.as_of_at},
            strategy_id=packet.strategy_id, strategy_hash=strategy_hash,
            data_version=data_version,
            date_range={"as_of_date": packet.as_of_date}, warnings=packet.warnings,
        )
        registry.save_artifact(record.experiment_id, "summary.json", asdict(packet))
        registry.update_experiment_status(record.experiment_id, "COMPLETED")
        return record.experiment_id
