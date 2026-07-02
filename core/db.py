"""SQLite persistence for Kobie runs and evidence records."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from core.schemas import Claim, NormalizedObjectPacket, ProgramIdentity, RawDocument, now_iso


DEFAULT_DB_PATH = Path("kobie.sqlite3")
_WRITE_LOCK = threading.Lock()


DDL = (
    """
    CREATE TABLE IF NOT EXISTS run_snapshots (
        program_name_normalized TEXT PRIMARY KEY,
        program_name TEXT NOT NULL,
        brand TEXT,
        country_or_region TEXT,
        program_state_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        user_input TEXT NOT NULL,
        program_name TEXT,
        domain TEXT,
        status TEXT NOT NULL,
        data_quality REAL NOT NULL DEFAULT 0,
        run_state_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS program_identities (
        identity_id TEXT PRIMARY KEY,
        raw_input TEXT NOT NULL,
        program_name TEXT NOT NULL,
        brand TEXT NOT NULL,
        domain TEXT NOT NULL,
        country_or_region TEXT,
        confidence REAL NOT NULL,
        status TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sources (
        source_id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        canonical_url TEXT,
        domain TEXT,
        source_type TEXT,
        authority_score REAL,
        fetched_at TEXT,
        content_date TEXT,
        http_status INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pages (
        page_id TEXT PRIMARY KEY,
        source_id TEXT,
        content_hash TEXT,
        title TEXT,
        cleaned_text TEXT NOT NULL,
        token_count INTEGER NOT NULL,
        sanitizer_flags TEXT,
        FOREIGN KEY(source_id) REFERENCES sources(source_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        page_id TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        text TEXT NOT NULL,
        token_count INTEGER NOT NULL,
        embedding_hash TEXT,
        FOREIGN KEY(page_id) REFERENCES pages(page_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS claims (
        claim_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        field_path TEXT NOT NULL,
        value_json TEXT,
        status TEXT NOT NULL,
        source_url TEXT,
        access_date TEXT,
        quote TEXT,
        confidence REAL NOT NULL,
        volatility TEXT NOT NULL,
        FOREIGN KEY(run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conflicts (
        conflict_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        field_path TEXT NOT NULL,
        claim_ids_json TEXT NOT NULL,
        score_gap REAL NOT NULL,
        resolution_status TEXT NOT NULL,
        judge_reason TEXT NOT NULL,
        FOREIGN KEY(run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS briefs (
        brief_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        brief_json TEXT NOT NULL,
        brief_html TEXT,
        word_count INTEGER NOT NULL,
        entailment_passed INTEGER NOT NULL,
        unsupported_sentences_json TEXT NOT NULL,
        FOREIGN KEY(run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversations (
        message_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        role TEXT NOT NULL,
        question TEXT,
        answer_json TEXT,
        cited_claim_ids_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_documents (
        url_hash TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        content TEXT NOT NULL,
        word_count INTEGER NOT NULL,
        query_id TEXT,
        entity_name TEXT,
        domain TEXT,
        retrieved_at TEXT NOT NULL,
        source_authority REAL,
        metadata_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS normalized_packets (
        identity_hash TEXT NOT NULL,
        object_type TEXT NOT NULL,
        source_url TEXT NOT NULL,
        chunk_id TEXT NOT NULL,
        packet_json TEXT NOT NULL,
        normalized_at TEXT NOT NULL,
        PRIMARY KEY(identity_hash, source_url, chunk_id)
    )
    """,
)


def connect(path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def checkpoint(conn: sqlite3.Connection) -> None:
    """Merge the WAL into the main DB file so data survives loss of -wal/-shm."""
    with _WRITE_LOCK:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def migrate(conn: sqlite3.Connection) -> None:
    with _WRITE_LOCK:
        # Migrate run_snapshots if it exists with the old schema (keyed by run_id, not program_name_normalized)
        snapshot_cols = {row[1] for row in conn.execute("PRAGMA table_info(run_snapshots)").fetchall()}
        if snapshot_cols and "program_name_normalized" not in snapshot_cols:
            conn.execute("ALTER TABLE run_snapshots RENAME TO run_snapshots_v1")

        for statement in DDL:
            conn.execute(statement)

        existing_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        if "run_state_json" not in existing_cols:
            conn.execute("ALTER TABLE runs ADD COLUMN run_state_json TEXT")
        conn.commit()


def upsert_run(
    conn: sqlite3.Connection,
    state: dict[str, Any],
    status: str = "initialized",
    run_state_json: str | None = None,
) -> None:
    with _WRITE_LOCK:
        conn.execute(
            """
            INSERT INTO runs (run_id, mode, user_input, program_name, domain, status, data_quality, run_state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                program_name=excluded.program_name,
                domain=excluded.domain,
                status=excluded.status,
                data_quality=excluded.data_quality,
                run_state_json=excluded.run_state_json,
                updated_at=excluded.updated_at
            """,
            (
                state["run_id"],
                state["mode"],
                state["user_input"],
                state.get("program_name"),
                str(state.get("domain")) if state.get("domain") else None,
                status,
                state.get("data_quality", 0.0),
                run_state_json,
                state["created_at"],
                now_iso(),
            ),
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")


def list_runs(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    """Return persisted run summaries ordered by most recent first."""
    rows = conn.execute(
        f"SELECT run_id, mode, user_input, program_name, status, data_quality, run_state_json, created_at, updated_at "
        f"FROM runs ORDER BY created_at DESC LIMIT {int(limit)}"
    ).fetchall()
    return [dict(r) for r in rows]


def find_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    """Return a persisted run row by id, including any serialized state payload."""
    row = conn.execute(
        "SELECT run_id, mode, user_input, program_name, status, data_quality, run_state_json, created_at, updated_at "
        "FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return dict(row) if row else None


def upsert_identity(conn: sqlite3.Connection, identity: ProgramIdentity) -> None:
    data = identity.model_dump()
    with _WRITE_LOCK:
        conn.execute(
            """
            INSERT INTO program_identities
                (identity_id, raw_input, program_name, brand, domain, country_or_region, confidence, status)
            VALUES
                (:identity_id, :raw_input, :program_name, :brand, :domain, :country_or_region, :confidence, :status)
            ON CONFLICT(identity_id) DO UPDATE SET
                raw_input=excluded.raw_input,
                program_name=excluded.program_name,
                brand=excluded.brand,
                domain=excluded.domain,
                country_or_region=excluded.country_or_region,
                confidence=excluded.confidence,
                status=excluded.status
            """,
            data,
        )
        conn.commit()


def insert_claims(conn: sqlite3.Connection, claims: list[Claim]) -> None:
    rows = [
        {
            **claim.model_dump(),
            "value_json": json.dumps(claim.value_json, ensure_ascii=True),
        }
        for claim in claims
    ]
    with _WRITE_LOCK:
        conn.executemany(
            """
            INSERT INTO claims
                (claim_id, run_id, field_path, value_json, status, source_url, access_date, quote, confidence, volatility)
            VALUES
                (:claim_id, :run_id, :field_path, :value_json, :status, :source_url, :access_date, :quote, :confidence, :volatility)
            ON CONFLICT(claim_id) DO NOTHING
            """,
            rows,
        )
        conn.commit()


def upsert_raw_documents(conn: sqlite3.Connection, documents: list[RawDocument]) -> None:
    """Persist raw Firecrawl documents idempotently by URL hash."""

    rows = [
        {
            **document.model_dump(),
            "metadata_json": json.dumps(document.metadata, ensure_ascii=True),
        }
        for document in documents
    ]
    with _WRITE_LOCK:
        conn.executemany(
            """
            INSERT INTO raw_documents
                (url_hash, url, content, word_count, query_id, entity_name, domain, retrieved_at, source_authority, metadata_json)
            VALUES
                (:url_hash, :url, :content, :word_count, :query_id, :entity_name, :domain, :retrieved_at, :source_authority, :metadata_json)
            ON CONFLICT(url_hash) DO UPDATE SET
                url=excluded.url,
                content=excluded.content,
                word_count=excluded.word_count,
                query_id=excluded.query_id,
                entity_name=excluded.entity_name,
                domain=excluded.domain,
                retrieved_at=excluded.retrieved_at,
                source_authority=excluded.source_authority,
                metadata_json=excluded.metadata_json
            """,
            rows,
        )
        conn.commit()


def save_program_snapshot(
    conn: sqlite3.Connection,
    program_name: str,
    brand: str | None,
    country_or_region: str | None,
    program_state_json: str,
    created_at: str | None = None,
) -> None:
    """Upsert a completed program-analysis snapshot keyed by normalised program name."""
    if created_at is None:
        created_at = now_iso()
    normalized = program_name.lower().strip()
    with _WRITE_LOCK:
        conn.execute(
            """
            INSERT INTO run_snapshots
                (program_name_normalized, program_name, brand, country_or_region, program_state_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(program_name_normalized) DO UPDATE SET
                program_name=excluded.program_name,
                brand=excluded.brand,
                country_or_region=excluded.country_or_region,
                program_state_json=excluded.program_state_json,
                created_at=excluded.created_at
            """,
            (normalized, program_name, brand, country_or_region, program_state_json, created_at),
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")


def find_program_snapshot(conn: sqlite3.Connection, query: str) -> dict | None:
    """Return the most-recent snapshot row for a program query, or None.

    Matching order: exact normalised name → stored name contains query → query words all appear in stored name.
    """
    normalized = query.lower().strip()

    row = conn.execute(
        "SELECT * FROM run_snapshots WHERE program_name_normalized = ?",
        (normalized,),
    ).fetchone()
    if row:
        return dict(row)

    row = conn.execute(
        "SELECT * FROM run_snapshots WHERE program_name_normalized LIKE ? ORDER BY created_at DESC LIMIT 1",
        (f"%{normalized}%",),
    ).fetchone()
    if row:
        return dict(row)

    words = [w for w in normalized.split() if len(w) > 2]
    if words:
        like_clause = " AND ".join("program_name_normalized LIKE ?" for _ in words)
        row = conn.execute(
            f"SELECT * FROM run_snapshots WHERE {like_clause} ORDER BY created_at DESC LIMIT 1",
            [f"%{w}%" for w in words],
        ).fetchone()
        if row:
            return dict(row)

    return None


def list_program_snapshots(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    """Return all stored snapshots ordered by most recent first."""
    rows = conn.execute(
        "SELECT program_name, brand, country_or_region, program_state_json, created_at "
        "FROM run_snapshots ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def find_program_snapshot_by_run_id(conn: sqlite3.Connection, run_id: str) -> dict | None:
    """Return a stored program snapshot containing the requested run id."""
    rows = conn.execute(
        "SELECT * FROM run_snapshots WHERE program_state_json LIKE ? ORDER BY created_at DESC",
        (f'%"run_id": "{run_id}"%',),
    ).fetchall()
    for row in rows:
        data = dict(row)
        try:
            state = json.loads(data["program_state_json"])
        except Exception:
            continue
        if state.get("run_id") == run_id:
            return data
    return None


def delete_run(conn: sqlite3.Connection, run_id: str) -> bool:
    """Delete a run and its associated claims, conflicts, briefs, and conversations. Returns True if deleted."""
    with _WRITE_LOCK:
        conn.execute("DELETE FROM claims WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM conflicts WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM briefs WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM conversations WHERE run_id = ?", (run_id,))
        cursor = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()
    return cursor.rowcount > 0


def delete_run_snapshot(conn: sqlite3.Connection, program_name_normalized: str) -> bool:
    """Delete a run_snapshot by normalized program name. Returns True if deleted."""
    with _WRITE_LOCK:
        cursor = conn.execute(
            "DELETE FROM run_snapshots WHERE program_name_normalized = ?",
            (program_name_normalized,),
        )
        conn.commit()
    return cursor.rowcount > 0


def list_program_snapshots_by_run_id(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    """Return all stored snapshots whose serialized state references the given run id."""
    rows = conn.execute(
        "SELECT * FROM run_snapshots WHERE program_state_json LIKE ? ORDER BY created_at ASC",
        (f'%"run_id": "{run_id}"%',),
    ).fetchall()
    result: list[dict] = []
    for row in rows:
        data = dict(row)
        try:
            state = json.loads(data["program_state_json"])
        except Exception:
            continue
        if state.get("run_id") == run_id:
            result.append(data)
    return result


def upsert_normalized_packets(conn: sqlite3.Connection, packets: list[NormalizedObjectPacket]) -> None:
    """Persist normalized extraction packets idempotently."""

    rows = [
        {
            "identity_hash": packet.identity_hash,
            "object_type": packet.object_type,
            "source_url": packet.source_url,
            "chunk_id": packet.chunk_id,
            "packet_json": packet.model_dump_json(),
            "normalized_at": packet.normalized_at,
        }
        for packet in packets
    ]
    with _WRITE_LOCK:
        conn.executemany(
            """
            INSERT INTO normalized_packets
                (identity_hash, object_type, source_url, chunk_id, packet_json, normalized_at)
            VALUES
                (:identity_hash, :object_type, :source_url, :chunk_id, :packet_json, :normalized_at)
            ON CONFLICT(identity_hash, source_url, chunk_id) DO UPDATE SET
                object_type=excluded.object_type,
                packet_json=excluded.packet_json,
                normalized_at=excluded.normalized_at
            """,
            rows,
        )
        conn.commit()
