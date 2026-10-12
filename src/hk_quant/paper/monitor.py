"""Read-only paper account snapshots, discrepancy reports and lifecycle audit."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Protocol


@contextmanager
def _lifecycle_db(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open the lifecycle DB, commit the transaction, and always close."""
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class PaperAccountReader(Protocol):
    def get_account(self) -> dict[str, Any]: ...
    def get_positions(self) -> list[dict[str, Any]]: ...
    def get_open_orders(self) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class PaperSnapshot:
    snapshot_id: str
    captured_at: str
    strategy_id: str
    strategy_version: str
    data_version: str
    account: dict[str, Any]
    positions: list[dict[str, Any]]
    open_orders: list[dict[str, Any]]
    limitations: tuple[str, ...]


class PaperMonitor:
    """Never places an order; preserves broker responses before comparing."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def sync(self, broker: PaperAccountReader, *, strategy_id: str,
             strategy_version: str, data_version: str) -> PaperSnapshot:
        account = broker.get_account()
        positions = broker.get_positions()
        orders = broker.get_open_orders()
        snapshot = PaperSnapshot(
            snapshot_id=uuid.uuid4().hex,
            captured_at=datetime.now(timezone.utc).isoformat(),
            strategy_id=strategy_id, strategy_version=strategy_version,
            data_version=data_version, account=account, positions=positions,
            open_orders=orders,
            limitations=(
                "paper fills and fees may be unavailable from broker API; "
                "order dealt quantity is not an independent fill ledger",
            ),
        )
        path = self.output_dir / f"{snapshot.snapshot_id}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(snapshot.__dict__, stream, indent=2, ensure_ascii=False, default=str)
        return snapshot

    @staticmethod
    def compare_positions(snapshot: PaperSnapshot,
                          expected: Mapping[str, float]) -> list[dict[str, Any]]:
        """Classify holdings differences; absent price/cost data stays unknown."""
        observed = {str(row["code"]): float(row.get("qty", 0)) for row in snapshot.positions}
        result: list[dict[str, Any]] = []
        for symbol in sorted(set(expected) | set(observed)):
            target, actual = float(expected.get(symbol, 0)), observed.get(symbol, 0.0)
            if target == actual:
                continue
            open_for_symbol = [order for order in snapshot.open_orders if order.get("code") == symbol]
            reason = "OPEN_ORDER" if open_for_symbol else "UNEXPLAINED_POSITION_MISMATCH"
            result.append({"code": symbol, "expected_qty": target,
                           "actual_qty": actual, "reason": reason})
        return result


_ALLOWED: dict[str, set[str]] = {
    "DRAFT": {"BACKTESTED", "RETIRED"},
    "BACKTESTED": {"OOS_VALIDATED", "RETIRED"},
    "OOS_VALIDATED": {"PAPER_TRADING", "RETIRED"},
    "PAPER_TRADING": {"PAPER_REVIEW", "RETIRED"},
    "PAPER_REVIEW": {"APPROVED", "RETIRED", "PAPER_TRADING"},
    "APPROVED": {"RETIRED"},
    "RETIRED": set(),
}


class StrategyLifecycle:
    """Append-only audit for a fixed strategy version; transitions are manual."""

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _lifecycle_db(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL, strategy_version TEXT NOT NULL,
                old_status TEXT, new_status TEXT NOT NULL, actor TEXT NOT NULL,
                reason TEXT NOT NULL, evidence_id TEXT NOT NULL,
                changed_at TEXT NOT NULL
            )""")

    def current(self, strategy_id: str, version: str) -> str:
        with _lifecycle_db(self.path) as db:
            row = db.execute(
                "SELECT new_status FROM transitions WHERE strategy_id=? AND strategy_version=? "
                "ORDER BY id DESC LIMIT 1", (strategy_id, version),
            ).fetchone()
        return row[0] if row else "DRAFT"

    def transition(self, strategy_id: str, version: str, new_status: str,
                   *, actor: str, reason: str, evidence_id: str) -> None:
        if not all((strategy_id, version, actor, reason, evidence_id)):
            raise ValueError("identity, actor, reason and evidence are required")
        with _lifecycle_db(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT new_status FROM transitions WHERE strategy_id=? AND strategy_version=? "
                "ORDER BY id DESC LIMIT 1", (strategy_id, version),
            ).fetchone()
            old = row[0] if row else "DRAFT"
            if new_status not in _ALLOWED.get(old, set()):
                raise ValueError(f"invalid lifecycle transition {old} -> {new_status}")
            db.execute(
                "INSERT INTO transitions (strategy_id,strategy_version,old_status,new_status,actor,reason,evidence_id,changed_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (strategy_id, version, old, new_status, actor, reason, evidence_id,
                 datetime.now(timezone.utc).isoformat()),
            )
