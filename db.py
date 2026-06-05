"""SQLite persistence for Kobie runs and evidence records."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from schemas import Claim, ProgramIdentity, now_iso


DEFAULT_DB_PATH = Path("kobie.sqlite3")
_WRITE_LOCK = threading.Lock()


DDL = (
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        user_input TEXT NOT NULL,
        program_name TEXT,
        domain TEXT,
        status TEXT NOT NULL,
        data_quality REAL NOT NULL DEFAULT 0,
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
)


def connect(path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    with _WRITE_LOCK:
        for statement in DDL:
            conn.execute(statement)
        conn.commit()


def upsert_run(conn: sqlite3.Connection, state: dict[str, Any], status: str = "initialized") -> None:
    with _WRITE_LOCK:
        conn.execute(
            """
            INSERT INTO runs (run_id, mode, user_input, program_name, domain, status, data_quality, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                program_name=excluded.program_name,
                domain=excluded.domain,
                status=excluded.status,
                data_quality=excluded.data_quality,
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
                state["created_at"],
                now_iso(),
            ),
        )
        conn.commit()


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
