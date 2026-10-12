"""Immutable, point-in-time document versions for research.

Only caller-supplied, lawfully obtained text is accepted. Fetching remote URLs
is deliberately outside this module so each source can enforce its own terms.
The conservative availability time is the later of publication and ingestion:
a document fetched today cannot silently enter a historical backtest yesterday.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping


def _utc(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: str | datetime) -> str:
    return _utc(value).isoformat()


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    document_id: str
    source_url: str
    stock_ids: tuple[str, ...]
    document_type: str
    language: str
    published_at: str
    retrieved_at: str
    available_at: str
    sha256: str
    text_path: str
    revision: int


@dataclass(frozen=True)
class ExtractedEvent:
    source_id: str
    document_id: str
    document_sha256: str
    event_type: str
    direction: str
    magnitude: str | None
    entities: tuple[str, ...]
    confidence: float
    evidence_quote: str
    model_version: str
    available_at: str


class DocumentStore:
    """Small single-user SQLite index with immutable content-addressed text."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "documents.sqlite3"
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS documents (
                source_id TEXT NOT NULL, document_id TEXT NOT NULL,
                source_url TEXT NOT NULL, stock_ids TEXT NOT NULL,
                document_type TEXT NOT NULL, language TEXT NOT NULL,
                published_at TEXT NOT NULL, retrieved_at TEXT NOT NULL,
                available_at TEXT NOT NULL, sha256 TEXT NOT NULL,
                text_path TEXT NOT NULL, revision INTEGER NOT NULL,
                PRIMARY KEY (source_id, document_id, sha256)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                source_id TEXT NOT NULL, document_id TEXT NOT NULL,
                document_sha256 TEXT NOT NULL, model_version TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (source_id, document_id, document_sha256, model_version)
            )""")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _document(row: sqlite3.Row) -> SourceDocument:
        return SourceDocument(**{**dict(row), "stock_ids": tuple(json.loads(row["stock_ids"]))})

    def add_document(
        self, *, source_id: str, document_id: str, source_url: str,
        stock_ids: tuple[str, ...] | list[str], document_type: str,
        language: str, published_at: str | datetime,
        text: str, retrieved_at: str | datetime | None = None,
    ) -> SourceDocument:
        if not source_id or not document_id or not source_url or not text.strip():
            raise ValueError("source, document, URL and text are required")
        publication = _stamp(published_at)
        retrieved = _stamp(retrieved_at or datetime.now(timezone.utc))
        available = max(publication, retrieved)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        relative_path = f"text/{digest[:2]}/{digest}.txt"
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            fd, temporary = tempfile.mkstemp(prefix=".document-", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(text)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

        with self._db() as db:
            existing = db.execute(
                "SELECT * FROM documents WHERE source_id=? AND document_id=? AND sha256=?",
                (source_id, document_id, digest),
            ).fetchone()
            if existing:
                return self._document(existing)
            revision = db.execute(
                "SELECT COALESCE(MAX(revision),0)+1 FROM documents WHERE source_id=? AND document_id=?",
                (source_id, document_id),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (source_id, document_id, source_url, json.dumps(list(stock_ids)),
                 document_type, language, publication, retrieved, available,
                 digest, relative_path, revision),
            )
            row = db.execute(
                "SELECT * FROM documents WHERE source_id=? AND document_id=? AND sha256=?",
                (source_id, document_id, digest),
            ).fetchone()
            return self._document(row)

    def get_text(self, document: SourceDocument) -> str:
        # A caller-created SourceDocument cannot supply an arbitrary path or
        # backdated availability to the event extractor.
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM documents WHERE source_id=? AND document_id=? AND sha256=?",
                (document.source_id, document.document_id, document.sha256),
            ).fetchone()
        if row is None or self._document(row) != document:
            raise ValueError("document metadata is not a stored immutable version")
        expected_path = f"text/{document.sha256[:2]}/{document.sha256}.txt"
        if document.text_path != expected_path:
            raise ValueError("document text path does not match its content hash")
        path = self.root / expected_path
        if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("document text must remain inside its storage directory")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != document.sha256:
            raise ValueError("document content no longer matches its stored hash")
        return raw.decode("utf-8")

    def as_of(self, when: str | datetime, stock_id: str | None = None,
              *, all_versions: bool = False) -> list[SourceDocument]:
        """Return the latest version visible at a timezone-aware instant.

        ``all_versions=True`` exposes the complete historical audit trail.
        Earlier versions remain visible until the revised text was retrieved.
        """
        cutoff = _stamp(when)
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM documents WHERE available_at<=? ORDER BY available_at, source_id, document_id, revision",
                (cutoff,),
            ).fetchall()
        documents = [self._document(row) for row in rows]
        if not all_versions:
            latest: dict[tuple[str, str], SourceDocument] = {}
            for document in documents:
                key = (document.source_id, document.document_id)
                previous = latest.get(key)
                if previous is None or (document.available_at, document.revision) > (previous.available_at, previous.revision):
                    latest[key] = document
            documents = list(latest.values())
        return [doc for doc in documents if stock_id in doc.stock_ids] if stock_id else documents

    def extract(
        self, document: SourceDocument,
        extractor: Callable[[str], Mapping[str, object]],
        model_version: str,
    ) -> ExtractedEvent:
        """Validate externally extracted facts against the preserved source.

        An LLM may implement ``extractor``, but it cannot write unsupported
        evidence or use its extraction time to backdate information.
        """
        if not model_version:
            raise ValueError("model_version is required")
        body = self.get_text(document)
        with self._db() as db:
            row = db.execute(
                "SELECT payload FROM events WHERE source_id=? AND document_id=? AND document_sha256=? AND model_version=?",
                (document.source_id, document.document_id, document.sha256, model_version),
            ).fetchone()
            if row:
                return ExtractedEvent(**{**json.loads(row[0]), "entities": tuple(json.loads(row[0])["entities"])})

        value = extractor(body)
        quote = value.get("evidence_quote")
        if not isinstance(quote, str) or not quote or quote not in body:
            raise ValueError("evidence_quote must occur verbatim in the source")
        confidence = float(value.get("confidence", 0.0))
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        event = ExtractedEvent(
            source_id=document.source_id, document_id=document.document_id,
            document_sha256=document.sha256,
            event_type=str(value.get("event_type") or "unknown"),
            direction=str(value.get("direction") or "unknown"),
            magnitude=str(value["magnitude"]) if value.get("magnitude") is not None else None,
            entities=tuple(str(item) for item in value.get("entities", ())),
            confidence=confidence, evidence_quote=quote, model_version=model_version,
            available_at=max(document.available_at, _stamp(datetime.now(timezone.utc))),
        )
        with self._db() as db:
            db.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)",
                (document.source_id, document.document_id, document.sha256,
                 model_version, json.dumps(event.__dict__, ensure_ascii=False)),
            )
            persisted = db.execute(
                "SELECT payload FROM events WHERE source_id=? AND document_id=? AND document_sha256=? AND model_version=?",
                (document.source_id, document.document_id, document.sha256, model_version),
            ).fetchone()
        payload = json.loads(persisted[0])
        return ExtractedEvent(**{**payload, "entities": tuple(payload["entities"])})
