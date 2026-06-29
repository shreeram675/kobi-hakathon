"""FastAPI REST backend for the Kobie Next.js frontend.

Endpoints:
  POST /api/run                      → start a pipeline run (background thread)
  POST /api/run?mock=true            → skip to claims stage with pre-built mock data
  GET  /api/run                      → list all in-memory run summaries
  GET  /api/run/history              → list DB-persisted runs (survives restarts)
  GET  /api/run/{run_id}             → poll a single run (stage_status, status, conversation)
  POST /api/run/{run_id}/clarify     → submit a clarification answer for the input validator
  POST /api/run/{run_id}/converse    → answer a grounded question
  GET  /api/cache/check?q=<query>    → check if a program has a stored analysis
  GET  /api/cache/check-multi?programs=… → batch cache check for compare mode
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("kobie")

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel as _PydanticBase

from core import db as _db

from core.schemas import (
    Claim,
    AgentState,
    BriefOutput,
    FieldReport,
    FieldReportEntry,
    FirecrawlScrapeOutput,
    build_initial_state,
    new_id,
    now_iso,
    RunMode,
)
from pipeline.graph import (
    input_validator_node,
    query_generator_node,
    retrieval_node,
    firecrawl_node,
    ingest_node,
    adjudication_node,
    narrator_node,
)
from pipeline.stages.comparison import compare_claim_sets
from pipeline.stages.comparison_brief import generate_comparison_brief
from pipeline.stages.converse import answer_comparison_question, answer_question
from core import cost_tracker

app = FastAPI(title="Kobie API")

# ── Persistent DB (cache + history) ───────────────────────────────────────────
_db_conn: sqlite3.Connection = _db.connect()
_db.migrate(_db_conn)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000",
                   "http://localhost:3001", "http://127.0.0.1:3001"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request / response models ─────────────────────────────────────────────────
# Defined here (before any routes) so FastAPI can resolve them for OpenAPI schema generation.

class CreateRunBody(_PydanticBase):
    user_input: str
    mode: str = "single"
    user_input_b: str | None = None
    programs: list[str] | None = None
    mock: bool = False
    force_fresh: bool = False


class ConverseRequest(_PydanticBase):
    message: str


class ClarifyRequest(_PydanticBase):
    answer: str


# UI stage IDs matching frontend schema.ts PIPELINE_STAGES
UI_STAGES = [
    "input_validator",
    "query_generator",
    "retrieval",
    "firecrawl_scraper",
    "chunking",
    "extraction",
    "claims",
    "adjudication",
    "output",
]


# ── Run record ─────────────────────────────────────────────────────────────────
class RunRecord:
    def __init__(
        self,
        run_id: str,
        user_input: str,
        mode: str,
        user_input_b: str | None = None,
        programs_list: list[str] | None = None,
        force_fresh: bool = False,
    ) -> None:
        self.run_id = run_id
        self.user_input = user_input
        self.user_input_b = user_input_b
        self.mode = mode
        self.force_fresh = force_fresh
        self.cached_response: dict[str, Any] | None = None
        self.state: AgentState = build_initial_state(user_input, RunMode(mode))
        self.state["run_id"] = run_id
        self.cost_ledger = cost_tracker.create_ledger(run_id)
        self.stage_status: dict[str, str] = {s: "idle" for s in UI_STAGES}
        self.active_stage: str | None = None
        self.run_status: str = "running"
        self.conversation: list[dict[str, Any]] = []
        self.compare_b: dict[str, Any] | None = None
        self.comparison_conversation: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.clarification_event = threading.Event()
        self.stop_event = threading.Event()

        # Multi-program comparison support
        if mode == "compare":
            if programs_list and len(programs_list) >= 2:
                self.programs: list[str] = programs_list
            elif user_input_b:
                self.programs = [user_input, user_input_b]
            else:
                self.programs = [user_input]
        else:
            self.programs = [user_input]

        self.current_program_index: int = 0
        self.program_statuses: list[str] = ["pending"] * len(self.programs)
        self.program_states: list[dict[str, Any] | None] = [None] * len(self.programs)
        self.program_stage_statuses: list[dict[str, str]] = [
            {s: "idle" for s in UI_STAGES} for _ in self.programs
        ]


STORE: dict[str, RunRecord] = {}
STORE_LOCK = threading.Lock()


# ── Serialization ─────────────────────────────────────────────────────────────
def _ser(v: Any) -> Any:
    if hasattr(v, "model_dump"):
        return v.model_dump()
    if isinstance(v, list):
        return [_ser(i) for i in v]
    if isinstance(v, dict):
        return {k: _ser(vv) for k, vv in v.items()}
    return v


def build_run_response(record: RunRecord) -> dict[str, Any]:
    if record.cached_response is not None:
        return dict(record.cached_response)
    with record.lock:
        result: dict[str, Any] = {k: _ser(v) for k, v in record.state.items()}
        # Always expose the run's original mode, not the per-program sub-state mode
        # (_reset_record_for_program sets each sub-state to "single" internally)
        result["mode"] = record.mode
        result["stage_status"] = dict(record.stage_status)
        result["active_stage"] = record.active_stage
        result["status"] = record.run_status
        result["conversation"] = list(record.conversation)
        result["cost_report"] = record.cost_ledger.to_dict()
        result["comparison_conversation"] = list(record.comparison_conversation)
        if record.compare_b is not None:
            result["compare_b"] = record.compare_b
        if record.mode == "compare":
            result["comparison_run"] = {
                "programs": list(record.programs),
                "current_program_index": record.current_program_index,
                "total_programs": len(record.programs),
                "program_statuses": list(record.program_statuses),
                "program_states": list(record.program_states),
                "program_stage_statuses": list(record.program_stage_statuses),
            }
    return result


def build_summary(record: RunRecord) -> dict[str, Any]:
    if record.cached_response is not None:
        cr = record.cached_response
        return {
            "run_id": record.run_id,
            "user_input": record.user_input,
            "mode": record.mode,
            "data_quality": cr.get("data_quality", 0.0),
            "status": "done",
            "created_at": cr.get("created_at", ""),
        }
    with record.lock:
        return {
            "run_id": record.run_id,
            "user_input": record.user_input,
            "mode": record.mode,
            "data_quality": record.state.get("data_quality", 0.0),
            "status": record.run_status,
            "created_at": record.state.get("created_at", ""),
        }


# ── Stage helpers ─────────────────────────────────────────────────────────────
def _mark(record: RunRecord, stage: str, status: str) -> None:
    with record.lock:
        record.stage_status[stage] = status
        if status == "running":
            record.active_stage = stage
        elif status in ("done", "error") and record.active_stage == stage:
            record.active_stage = None


def _apply(record: RunRecord, delta: dict) -> AgentState:
    with record.lock:
        record.state = {**record.state, **delta}
        return record.state


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _snapshot_meta(snapshot: dict) -> dict[str, Any]:
    """Convert a DB snapshot row to a CacheCheckResult-shaped dict."""
    created_at = snapshot["created_at"]
    try:
        dt = datetime.fromisoformat(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - dt).days
        run_date = dt.strftime("%Y-%m-%d")
        run_datetime_str = dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        age_days = 0
        run_date = created_at[:10]
        run_datetime_str = created_at
    return {
        "found": True,
        "program_name": snapshot.get("program_name"),
        "brand": snapshot.get("brand"),
        "country_or_region": snapshot.get("country_or_region"),
        "run_date": run_date,
        "run_datetime": run_datetime_str,
        "run_timestamp": created_at,
        "age_days": age_days,
    }


def _save_program_snapshot_to_db(program_name: str, brand: str | None,
                                  country_or_region: str | None,
                                  program_state: dict[str, Any]) -> None:
    """Persist a completed single-program state dict to the DB snapshot cache."""
    try:
        _db.save_program_snapshot(
            _db_conn,
            program_name,
            brand,
            country_or_region,
            json.dumps(program_state, default=str),
            now_iso(),
        )
        logger.info("Saved snapshot for %s", program_name)
    except Exception:
        logger.exception("Failed to save snapshot for %s", program_name)


def _persist_run_summary(record: RunRecord) -> None:
    """Persist the run summary row used by the history list."""
    with record.lock:
        run_status = record.run_status
        if record.mode == "compare":
            completed_states = [ps for ps in record.program_states if ps]
            if completed_states:
                qualities = [float(ps.get("data_quality", 0.0) or 0.0) for ps in completed_states]
                data_quality = sum(qualities) / len(qualities)
            else:
                data_quality = float(record.state.get("data_quality", 0.0) or 0.0)
            program_name = " vs ".join([p for p in record.programs if p]) or record.user_input
        else:
            data_quality = float(record.state.get("data_quality", 0.0) or 0.0)
            program_name = record.state.get("program_name") or record.user_input

        summary_state = {
            "run_id": record.run_id,
            "mode": record.mode,
            "user_input": record.user_input,
            "program_name": program_name,
            "domain": record.state.get("domain"),
            "data_quality": data_quality,
            "created_at": record.state.get("created_at"),
        }

    # build_run_response also acquires record.lock — must be called outside the block above
    payload = None
    if run_status != "running":
        try:
            payload = json.dumps(build_run_response(record), default=str)
        except Exception:
            payload = None

    _db.upsert_run(_db_conn, summary_state, status=run_status, run_state_json=payload)


def _make_program_state_snapshot(record: RunRecord) -> dict[str, Any]:
    """Serialize record.state into the canonical program-state snapshot format."""
    with record.lock:
        snap = {k: _ser(v) for k, v in record.state.items()}
    snap["stage_status"] = {s: "done" for s in UI_STAGES}
    snap["active_stage"] = None
    snap["status"] = "done"
    snap["cost_report"] = record.cost_ledger.to_dict()
    return snap


def _restore_single_from_cache(record: RunRecord, snapshot: dict) -> None:
    """Populate record so it looks like a completed single run (no pipeline thread needed)."""
    program_state = json.loads(snapshot["program_state_json"])
    program_name = program_state.get("program_name") or record.user_input
    cached: dict[str, Any] = dict(program_state)
    cached["run_id"] = record.run_id
    cached["user_input"] = record.user_input
    cached["mode"] = "single"
    cached["active_stage"] = None
    cached["status"] = "done"
    cached["conversation"] = [
        {
            "role": "assistant",
            "message": (
                f"I've analysed {program_name}. Ask me anything about its earn "
                "rates, tiers, partners, or member sentiment — I'll answer only "
                "from the extracted claims."
            ),
            "created_at": now_iso(),
        }
    ]
    cached["comparison_conversation"] = []
    with record.lock:
        record.cached_response = cached
        record.run_status = "done"


def _snapshot_run_response(snapshot: dict) -> dict[str, Any]:
    """Return a completed run response directly from a DB snapshot."""
    program_state = json.loads(snapshot["program_state_json"])
    program_name = program_state.get("program_name") or snapshot.get("program_name") or ""
    response: dict[str, Any] = dict(program_state)
    response["mode"] = "single"
    response["user_input"] = response.get("user_input") or program_name
    response["program_name"] = response.get("program_name") or program_name
    response["active_stage"] = None
    response["status"] = "done"
    response["stage_status"] = response.get("stage_status") or {s: "done" for s in UI_STAGES}
    response["conversation"] = []
    response["comparison_conversation"] = []
    return response


def _run_response_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    payload = row.get("run_state_json")
    if not payload:
        return None
    try:
        return json.loads(payload)
    except Exception:
        return None


def _comparison_brief_stub(run_id: str, programs: list[str], created_at: str) -> dict[str, Any]:
    """Lightweight fallback brief for archived compare runs that predate persisted briefs."""
    readable = " vs ".join(programs) if programs else "the programs"
    return {
        "brief_id": f"{run_id}_reconstructed",
        "run_id": run_id,
        "programs": programs,
        "overall_winner": None,
        "executive_summary": (
            f"This archived comparison of {readable} was reconstructed from saved program "
            "snapshots. The detailed narrative brief was not persisted for this older run, "
            "but the side-by-side analysis data is still available."
        ),
        "category_verdicts": [],
        "key_differentiators": [],
        "personas": [
            {
                "program": program,
                "best_for": "Reviewing the reconstructed comparison evidence.",
            }
            for program in programs
        ],
        "strategic_profiles": [],
        "differentiation_themes": [],
        "generated_at": created_at,
    }


def _compare_run_response_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild a compare-mode response from persisted program snapshots when needed."""
    payload = _run_response_from_row(row)
    if payload is not None:
        return payload

    program_name = (row.get("program_name") or "").strip()
    programs = [part.strip() for part in re.split(r"\s+vs\s+", program_name) if part.strip()]
    if not programs:
        programs = [row.get("user_input") or row["run_id"]]

    snapshots: list[dict[str, Any]] = []
    for snapshot in _db.list_program_snapshots_by_run_id(_db_conn, row["run_id"]):
        try:
            state = json.loads(snapshot["program_state_json"])
        except Exception:
            continue
        snapshots.append({"snapshot": snapshot, "state": state})

    snapshot_programs = [snap["state"].get("program_name") or snap["snapshot"].get("program_name") for snap in snapshots]
    snapshot_programs = [str(name).strip() for name in snapshot_programs if str(name).strip()]
    if snapshot_programs:
        programs = snapshot_programs

    if snapshots and len(programs) < 2:
        programs = [
            snapshots[i]["state"].get("program_name") or snapshots[i]["snapshot"].get("program_name") or f"Program {i + 1}"
            for i in range(len(snapshots))
        ]

    created_at = row.get("updated_at") or row.get("created_at") or now_iso()
    status = row.get("status") or "done"

    if len(snapshots) < 2:
        base_state = build_initial_state(row.get("user_input") or programs[0], RunMode("compare"))
        response: dict[str, Any] = {k: _ser(v) for k, v in base_state.items()}
        response["run_id"] = row["run_id"]
        response["mode"] = "compare"
        response["user_input"] = row.get("user_input") or programs[0]
        response["program_name"] = programs[0]
        response["compare_b"] = None
        response["comparison_run"] = {
            "programs": programs,
            "current_program_index": 0,
            "total_programs": len(programs),
            "program_statuses": ["done" for _ in programs],
            "program_states": [None for _ in programs],
            "program_stage_statuses": [{s: "done" for s in UI_STAGES} for _ in programs],
        }
        response["comparison_output"] = None
        response["comparison_brief"] = _comparison_brief_stub(row["run_id"], programs, created_at)
        response["conversation"] = []
        response["comparison_conversation"] = []
        response["active_stage"] = None
        response["status"] = status
        response["stage_status"] = {s: "done" for s in UI_STAGES}
        response["created_at"] = created_at
        response["updated_at"] = created_at
        response["errors"] = []
        return response

    primary_state = dict(snapshots[0]["state"])
    secondary_state = dict(snapshots[1]["state"])

    comparison_run = {
        "programs": programs,
        "current_program_index": 0,
        "total_programs": len(programs),
        "program_statuses": ["done" for _ in programs],
        "program_states": [snap["state"] for snap in snapshots] + [None] * max(0, len(programs) - len(snapshots)),
        "program_stage_statuses": [
            snap["state"].get("stage_status") or {s: "done" for s in UI_STAGES}
            for snap in snapshots
        ] + [{s: "done" for s in UI_STAGES}] * max(0, len(programs) - len(snapshots)),
    }

    compare_claims_a = [
        Claim.model_validate(claim)
        for claim in (primary_state.get("adjudicated_claims") or [])
    ]
    compare_claims_b = [
        Claim.model_validate(claim)
        for claim in (secondary_state.get("adjudicated_claims") or [])
    ]

    comparison_output = None
    try:
        comparison_output = compare_claim_sets(
            row["run_id"],
            programs[0],
            programs[1],
            compare_claims_a,
            compare_claims_b,
        ).model_dump()
    except Exception:
        comparison_output = None

    response: dict[str, Any] = dict(primary_state)
    response["run_id"] = row["run_id"]
    response["mode"] = "compare"
    response["user_input"] = row.get("user_input") or response.get("user_input") or programs[0]
    response["program_name"] = programs[0]
    response["compare_b"] = secondary_state
    response["comparison_run"] = comparison_run
    response["comparison_output"] = comparison_output
    response["comparison_brief"] = _comparison_brief_stub(row["run_id"], programs, created_at)
    response["conversation"] = []
    response["comparison_conversation"] = []
    response["active_stage"] = None
    response["status"] = status
    response["stage_status"] = response.get("stage_status") or {s: "done" for s in UI_STAGES}
    response["created_at"] = row.get("created_at") or response.get("created_at") or created_at
    response["updated_at"] = row.get("updated_at") or response.get("updated_at") or created_at
    return response


def _restore_compare_program_from_cache(
    record: RunRecord,
    index: int,
    prog: str,
    snapshot: dict,
    all_claims: list,
    all_names: list,
    all_field_reports: list,
) -> None:
    """Restore one program in a compare run from a DB snapshot."""
    program_state = json.loads(snapshot["program_state_json"])
    program_name = program_state.get("program_name") or prog
    all_names[index] = program_name
    all_claims[index] = program_state.get("adjudicated_claims", [])
    all_field_reports[index] = program_state.get("field_report")
    with record.lock:
        record.program_states[index] = program_state
        record.program_statuses[index] = "done"
        record.program_stage_statuses[index] = program_state.get(
            "stage_status", {s: "done" for s in UI_STAGES}
        )
    logger.info("[%s] program[%d] %s loaded from cache", record.run_id, index, program_name)


# ── Core pipeline (single program) ────────────────────────────────────────────
def _stopped(record: RunRecord) -> bool:
    return record.stop_event.is_set()


def _run_single_pipeline(record: RunRecord) -> bool:
    """Run one program through all pipeline stages. Returns True on success."""
    cost_tracker.set_active_run_id(record.run_id)
    state = record.state

    # 1. Input Validator — loop until resolved, rejected, or clarification timeout
    if _stopped(record):
        return False
    _mark(record, "input_validator", "running")
    clarification_count = 0
    while True:
        try:
            delta = input_validator_node(state)
            state = _apply(record, delta)
        except Exception:
            logger.exception("[%s] input_validator crashed", record.run_id)
            _mark(record, "input_validator", "error")
            return False

        vr = state.get("validation_result")
        if vr and vr.status == "resolved":
            _mark(record, "input_validator", "done")
            break
        elif vr and vr.status == "needs_clarification" and clarification_count < 3:
            clarification_count += 1
            with record.lock:
                record.run_status = "clarification_needed"
            record.clarification_event.clear()
            if not record.clarification_event.wait(timeout=300):
                # User did not respond within 5 minutes
                _mark(record, "input_validator", "error")
                return False
            with record.lock:
                state = record.state
                record.run_status = "running"
        else:
            _mark(record, "input_validator", "error")
            return False

    # 2. Query Generator
    if _stopped(record):
        return False
    _mark(record, "query_generator", "running")
    try:
        delta = query_generator_node(state)
        state = _apply(record, delta)
        if state.get("query_generation_result"):
            _mark(record, "query_generator", "done")
        else:
            _mark(record, "query_generator", "error")
            return False
    except Exception:
        logger.exception("[%s] query_generator crashed", record.run_id)
        _mark(record, "query_generator", "error")
        return False

    # 3. Retrieval
    if _stopped(record):
        return False
    _mark(record, "retrieval", "running")
    try:
        delta = retrieval_node(state)
        state = _apply(record, delta)
        if state.get("retrieval_result"):
            _mark(record, "retrieval", "done")
        else:
            _mark(record, "retrieval", "error")
            return False
    except Exception:
        logger.exception("[%s] retrieval crashed", record.run_id)
        _mark(record, "retrieval", "error")
        return False

    # 4. Firecrawl Scraper
    if _stopped(record):
        return False
    _mark(record, "firecrawl_scraper", "running")
    total_scrape_urls = len(state.get("retrieved_urls", []))

    def _on_scrape_progress(completed_blocks, total):
        successful = sum(1 for b in completed_blocks if b.scrape_status == "success" and b.content)
        partial = FirecrawlScrapeOutput(
            total_urls=total,
            successful_scrapes=successful,
            failed_scrapes=len(completed_blocks) - successful,
            blocks=completed_blocks,
        )
        _apply(record, {"scraped_blocks": completed_blocks, "firecrawl_result": partial})

    try:
        delta = firecrawl_node(state, on_progress=_on_scrape_progress)
        state = _apply(record, delta)
        fc = state.get("firecrawl_result")
        if fc and fc.successful_scrapes > 0:
            _mark(record, "firecrawl_scraper", "done")
        else:
            _mark(record, "firecrawl_scraper", "error")
            return False
    except Exception:
        logger.exception("[%s] firecrawl_scraper crashed", record.run_id)
        _mark(record, "firecrawl_scraper", "error")
        return False

    # 5–7. Ingest (raw store → chunking → extraction → claims)
    if _stopped(record):
        return False
    _mark(record, "chunking", "running")
    try:
        delta = ingest_node(state)
        state = _apply(record, delta)
        chunks = state.get("semantic_chunks", [])
        packets = state.get("normalized_packets", [])
        fr = state.get("field_report")

        if chunks:
            _mark(record, "chunking", "done")
        else:
            _mark(record, "chunking", "error")
            _mark(record, "extraction", "error")
            _mark(record, "claims", "error")
            return False

        if packets:
            _mark(record, "extraction", "done")
        else:
            _mark(record, "extraction", "error")
            _mark(record, "claims", "error")
            return False

        if fr:
            _mark(record, "claims", "done")
        else:
            _mark(record, "claims", "error")
            return False
    except Exception:
        logger.exception("[%s] ingest/chunking crashed", record.run_id)
        _mark(record, "chunking", "error")
        _mark(record, "extraction", "error")
        _mark(record, "claims", "error")
        return False

    # 8. Adjudication
    if _stopped(record):
        return False
    _mark(record, "adjudication", "running")
    try:
        delta = adjudication_node(state)
        state = _apply(record, delta)
        _mark(record, "adjudication", "done")
    except Exception:
        logger.exception("[%s] adjudication crashed", record.run_id)
        _mark(record, "adjudication", "error")
        return False

    # 9. Narration → output
    if _stopped(record):
        return False
    _mark(record, "output", "running")
    try:
        delta = narrator_node(state)
        state = _apply(record, delta)
        if state.get("final_brief"):
            _mark(record, "output", "done")
        else:
            _mark(record, "output", "error")
            return False
    except Exception:
        logger.exception("[%s] output/narrator crashed", record.run_id)
        _mark(record, "output", "error")
        return False

    return True


# ── Pipeline thread entry points ──────────────────────────────────────────────
def _reset_record_for_program(record: RunRecord, prog: str, index: int) -> None:
    """Reset the shared record state to run a fresh program through the pipeline."""
    with record.lock:
        record.current_program_index = index
        record.program_statuses[index] = "running"
        fresh = build_initial_state(prog, RunMode("single"))
        fresh["run_id"] = record.run_id
        record.state = fresh
        record.stage_status = {s: "idle" for s in UI_STAGES}
        record.active_stage = None


def _save_program_result(record: RunRecord, index: int, success: bool,
                         all_claims: list, all_names: list) -> None:
    """Serialize and store the completed program state."""
    with record.lock:
        all_claims[index] = list(record.state.get("adjudicated_claims", []))
        all_names[index] = record.state.get("program_name") or record.programs[index]
        record.program_stage_statuses[index] = dict(record.stage_status)
        serialized: dict[str, Any] = {k: _ser(v) for k, v in record.state.items()}
        serialized["stage_status"] = dict(record.stage_status)
        serialized["active_stage"] = None
        serialized["status"] = "done" if success else "error"
        serialized["cost_report"] = record.cost_ledger.to_dict()
        record.program_states[index] = serialized
        record.program_statuses[index] = "done" if success else "error"


def run_pipeline(record: RunRecord) -> None:
    """Thread entry point — handles single, compare, and converse modes."""
    if record.mode == "compare" and len(record.programs) >= 2:
        all_claims: list[list] = [[] for _ in record.programs]
        all_names: list[str] = list(record.programs)
        all_field_reports: list[Any] = [None] * len(record.programs)
        any_success = False

        for i, prog in enumerate(record.programs):
            if _stopped(record):
                with record.lock:
                    for j in range(i, len(record.programs)):
                        if record.program_statuses[j] == "pending":
                            record.program_statuses[j] = "error"
                break

            # Per-program cache check for compare mode
            if not record.force_fresh:
                snapshot = _db.find_program_snapshot(_db_conn, prog)
                if snapshot:
                    _restore_compare_program_from_cache(
                        record, i, prog, snapshot, all_claims, all_names, all_field_reports
                    )
                    any_success = True
                    continue

            _reset_record_for_program(record, prog, i)
            cost_tracker.set_active_run_id(record.run_id)
            success = _run_single_pipeline(record)
            with record.lock:
                all_field_reports[i] = record.state.get("field_report")
            _save_program_result(record, i, success, all_claims, all_names)
            if success:
                any_success = True
                # Save freshly-run program to cache
                prog_state = record.program_states[i]
                if prog_state:
                    _save_program_snapshot_to_db(
                        all_names[i],
                        prog_state.get("brand"),
                        prog_state.get("country_or_region"),
                        prog_state,
                    )

        done_indices = [i for i, s in enumerate(record.program_statuses) if s == "done"]
        if len(done_indices) >= 2:
            with record.lock:
                record.compare_b = record.program_states[done_indices[1]]
                state_a = record.program_states[done_indices[0]]
                if state_a is not None:
                    record.state = dict(state_a)

            # Generate LLM comparison brief from all completed field reports
            try:
                from core.schemas import FieldReport as _FieldReport
                brief_names = [all_names[i] for i in done_indices]
                brief_reports = []
                for i in done_indices:
                    fr = all_field_reports[i]
                    if isinstance(fr, _FieldReport):
                        brief_reports.append(fr)
                    elif isinstance(fr, dict):
                        brief_reports.append(_FieldReport.model_validate(fr))
                if len(brief_reports) >= 2:
                    brief = generate_comparison_brief(record.run_id, brief_names, brief_reports)
                    with record.lock:
                        record.state = {**record.state, "comparison_brief": brief}
            except Exception:
                logger.exception("[%s] comparison brief generation failed", record.run_id)

            # Seed comparison conversation welcome message
            done_names = [all_names[i] for i in done_indices]
            with record.lock:
                record.comparison_conversation = [
                    {
                        "role": "assistant",
                        "message": (
                            f"I've completed the comparison of {' vs '.join(done_names)}. "
                            "Ask me about differences, category winners, key metrics, or any "
                            "specific aspect of the comparison — I'll answer only from the "
                            "extracted and compared data."
                        ),
                        "created_at": now_iso(),
                    }
                ]

        with record.lock:
            # Mark any stage still showing "running" as failed
            for s in list(record.stage_status.keys()):
                if record.stage_status[s] == "running":
                    record.stage_status[s] = "error"
            record.active_stage = None
            if not _stopped(record):
                record.run_status = "done" if any_success else "error"
            # else: run_status is already "cancelled" — preserve it
        _persist_run_summary(record)

    else:
        success = _run_single_pipeline(record)

        if _stopped(record):
            with record.lock:
                for s in list(record.stage_status.keys()):
                    if record.stage_status[s] == "running":
                        record.stage_status[s] = "error"
                record.active_stage = None
            return  # run_status already "cancelled"

        if success:
            program_name = record.state.get("program_name") or record.user_input
            # Save completed analysis to cache
            snap = _make_program_state_snapshot(record)
            _save_program_snapshot_to_db(
                program_name,
                record.state.get("brand"),
                record.state.get("country_or_region"),
                snap,
            )
            with record.lock:
                record.conversation = [
                    {
                        "role": "assistant",
                        "message": (
                            f"I've analysed {program_name}. Ask me anything about its earn "
                            "rates, tiers, partners, or member sentiment — I'll answer only "
                            "from the extracted claims."
                        ),
                        "created_at": now_iso(),
                    }
                ]

        with record.lock:
            record.run_status = "done" if success else "error"
        _persist_run_summary(record)


# ── DB-fallback converse helpers ──────────────────────────────────────────────

def _single_converse_from_db(run_id: str, message: str) -> dict[str, Any]:
    """Stateless single-program converse for historical runs not held in STORE."""
    from core.schemas import BriefOutput as _BO, FieldReport as _FR

    payload: dict[str, Any] | None = None
    row = _db.find_run(_db_conn, run_id)
    if row is not None:
        payload = _run_response_from_row(row)
    if payload is None:
        snapshot = _db.find_program_snapshot_by_run_id(_db_conn, run_id)
        if snapshot:
            payload = _snapshot_run_response(snapshot)
    if payload is None:
        raise HTTPException(status_code=404, detail="run not found")

    final_brief_raw = payload.get("final_brief")
    if not final_brief_raw:
        raise HTTPException(status_code=400, detail="Pipeline has not completed — no brief available.")
    try:
        final_brief = _BO.model_validate(final_brief_raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not parse brief data for this run.")

    field_report: FieldReport | None = None
    fr_raw = payload.get("field_report")
    if isinstance(fr_raw, dict):
        try:
            field_report = FieldReport.model_validate(fr_raw)
        except Exception:
            pass

    cost_tracker.set_active_run_id(run_id)
    try:
        answer = answer_question(message, final_brief, field_report)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return answer.model_dump()


def _compare_converse_from_db(run_id: str, message: str) -> dict[str, Any]:
    """Stateless comparison converse for historical runs not held in STORE."""
    from core.schemas import ComparisonBrief as _CB, FieldReport as _FR

    row = _db.find_run(_db_conn, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    payload = _run_response_from_row(row)
    if payload is None:
        raise HTTPException(status_code=400, detail="Run state not persisted — cannot answer questions about this run.")

    comparison_brief_raw = payload.get("comparison_brief")
    # Treat stub briefs (empty category_verdicts) same as missing — generate a real one
    is_stub = not comparison_brief_raw or not (
        isinstance(comparison_brief_raw.get("category_verdicts"), list)
        and len(comparison_brief_raw["category_verdicts"]) > 0
    )
    if is_stub:
        logger.info("[%s] no comparison brief in DB for converse — generating on demand", run_id)
        comp_run = payload.get("comparison_run") or {}
        prog_states_raw: list = comp_run.get("program_states") or []
        prog_names_raw: list[str] = comp_run.get("programs") or []
        from core.schemas import FieldReport as _FR2
        brief_reports_tmp: list = []
        brief_names_tmp: list[str] = []
        for i, ps in enumerate(prog_states_raw):
            if not isinstance(ps, dict):
                continue
            name = prog_names_raw[i] if i < len(prog_names_raw) else f"Program {i + 1}"
            fr_raw = ps.get("field_report")
            if isinstance(fr_raw, dict):
                try:
                    brief_reports_tmp.append(_FR2.model_validate(fr_raw))
                    brief_names_tmp.append(name)
                except Exception:
                    pass
        if len(brief_reports_tmp) >= 2:
            try:
                generated = generate_comparison_brief(run_id, brief_names_tmp, brief_reports_tmp)
                comparison_brief_raw = _ser(generated)
            except Exception:
                logger.exception("[%s] on-demand brief generation failed during converse", run_id)
        still_stub = not comparison_brief_raw or not (
            isinstance(comparison_brief_raw.get("category_verdicts"), list)
            and len(comparison_brief_raw["category_verdicts"]) > 0
        )
        if still_stub:
            raise HTTPException(
                status_code=400,
                detail="No comparison brief available — open the comparison page to generate one first.",
            )
    try:
        comparison_brief = _CB.model_validate(comparison_brief_raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not parse comparison brief for this run.")

    comp_run = payload.get("comparison_run") or {}
    prog_states: list[dict | None] = comp_run.get("program_states") or []
    prog_names: list[str] = comp_run.get("programs") or []

    program_reports: list[tuple[str, FieldReport | None]] = []
    for i, ps in enumerate(prog_states):
        name = prog_names[i] if i < len(prog_names) else f"Program {i + 1}"
        fr: FieldReport | None = None
        if isinstance(ps, dict):
            fr_raw = ps.get("field_report")
            if isinstance(fr_raw, dict):
                try:
                    fr = _FR.model_validate(fr_raw)
                except Exception:
                    pass
        program_reports.append((name, fr))

    cost_tracker.set_active_run_id(run_id)
    try:
        answer = answer_comparison_question(message, comparison_brief, program_reports)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return answer.model_dump()


# ── Compare converse endpoint ─────────────────────────────────────────────────

@app.post("/api/run/{run_id}/compare/converse")
def compare_converse(run_id: str, body: ConverseRequest) -> dict[str, Any]:
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    with STORE_LOCK:
        record = STORE.get(run_id)
    if record is None:
        return _compare_converse_from_db(run_id, body.message.strip())
    if record.mode != "compare":
        raise HTTPException(status_code=400, detail="not a comparison run")

    with record.lock:
        comparison_brief = record.state.get("comparison_brief")
        program_states_snapshot = list(record.program_states)
        program_names_snapshot = list(record.programs)

    if comparison_brief is None:
        raise HTTPException(
            status_code=400,
            detail="Comparison brief not yet available — please wait for the run to complete.",
        )

    # Normalise comparison_brief (may be a Pydantic object or a serialised dict)
    from core.schemas import ComparisonBrief as _CB, FieldReport as _FR
    if isinstance(comparison_brief, dict):
        comparison_brief = _CB.model_validate(comparison_brief)

    # Build per-program (name, FieldReport | None) tuples
    program_reports: list[tuple[str, FieldReport | None]] = []
    for i, ps in enumerate(program_states_snapshot):
        name = program_names_snapshot[i] if i < len(program_names_snapshot) else f"Program {i + 1}"
        if ps is not None:
            fr = ps.get("field_report")
            if isinstance(fr, dict):
                fr = _FR.model_validate(fr)
            elif not isinstance(fr, FieldReport):
                fr = None
            program_reports.append((name, fr))
        else:
            program_reports.append((name, None))

    cost_tracker.set_active_run_id(run_id)
    try:
        answer = answer_comparison_question(body.message.strip(), comparison_brief, program_reports)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    created_at = now_iso()
    with record.lock:
        record.comparison_conversation.append(
            {"role": "user", "message": body.message.strip(), "created_at": created_at}
        )
        record.comparison_conversation.append(
            {
                "role": "assistant",
                "message": answer.answer,
                "answer": answer.model_dump(),
                "created_at": created_at,
            }
        )

    return answer.model_dump()


# ── Mock field-report data ────────────────────────────────────────────────────
_MOCK_PROFILES: dict[str, dict[str, Any]] = {
    "delta skymiles": {
        "program_name": "Delta SkyMiles",
        "brand": "Delta Air Lines",
        "fields": {
            "program_basics.program_name": ("Delta SkyMiles", "extracted", 0.99, 4),
            "program_basics.brand": ("Delta Air Lines", "extracted", 0.99, 4),
            "program_basics.industry": ("Airline", "extracted", 0.98, 3),
            "program_basics.program_type": ("Frequent Flyer", "extracted", 0.97, 3),
            "program_basics.geography": ("Global", "extracted", 0.95, 3),
            "program_basics.membership_count": ("Over 100 million members", "extracted", 0.82, 2),
            "earn_mechanics.base_earn_rate": ("5 miles per $1 on Delta flights", "extracted", 0.93, 3),
            "earn_mechanics.bonus_categories": ("First class earns 8 miles/$ ; Medallion bonus up to 11x", "extracted", 0.88, 2),
            "earn_mechanics.non_transactional_earn": ("Miles earned via Amex credit cards, hotel stays, car rentals", "extracted", 0.85, 2),
            "burn_mechanics.redemption_options": ("Award flights, upgrades, seat upgrades, partner hotels, gift cards", "extracted", 0.92, 3),
            "burn_mechanics.redemption_thresholds": ("No fixed redemption chart — dynamic pricing; flights start ~5,000 miles", "ambiguous", 0.68, 2),
            "burn_mechanics.point_value_cpp": ("~1.1–1.3 cents per mile on average", "extracted", 0.74, 2),
            "burn_mechanics.expiry_policy": ("Miles expire after 24 months of account inactivity", "extracted", 0.91, 3),
            "tier_system.tier_names": ("Silver Medallion, Gold Medallion, Platinum Medallion, Diamond Medallion", "extracted", 0.97, 4),
            "tier_system.qualification_criteria": ("Medallion Qualifying Dollars (MQDs) + Medallion Qualifying Miles (MQMs) or segments", "extracted", 0.90, 3),
            "tier_system.tier_benefits": ("Priority boarding, complimentary upgrades, lounge access (Diamond), bonus miles", "extracted", 0.88, 3),
            "tier_system.qualification_period": ("January 1 – December 31 calendar year", "extracted", 0.95, 3),
            "partnerships.partner_names": ("American Express, Lyft, Starbucks, Airbnb, Hertz, Hilton, Marriott", "extracted", 0.87, 3),
            "partnerships.partnership_type": ("Credit card (Amex), hotel, rideshare, car rental, retail", "extracted", 0.85, 2),
            "partnerships.details": ("Amex Delta cards earn 2–3x miles on Delta purchases; Starbucks earns 1 mile per $1", "extracted", 0.80, 2),
            "digital_experience.mobile_app_available": ("Yes — Fly Delta app on iOS and Android", "extracted", 0.99, 4),
            "digital_experience.app_ratings": ("4.8 / 5 App Store ; 4.5 / 5 Play Store", "extracted", 0.88, 3),
            "digital_experience.personalization_features": ("Personalized upgrade offers, trip recommendations, real-time flight updates", "extracted", 0.78, 2),
            "digital_experience.gamification_features": ("SkyMiles Shopping portal with bonus earn events; limited-time promotions", "extracted", 0.72, 2),
            "member_sentiment.ratings": ("Generally positive — praised for upgrade availability at top tiers", "extracted", 0.76, 2),
            "member_sentiment.common_praise": ("Strong domestic network, reliable Amex partnership, easy miles earning", "extracted", 0.80, 3),
            "member_sentiment.common_complaints": ("Dynamic award pricing seen as unpredictable; miles devalued over time", "extracted", 0.83, 3),
            "member_sentiment.sources_checked": ("FlyerTalk, Reddit r/delta, Trustpilot, App Store reviews", "extracted", 0.90, 3),
            "competitive_position.key_differentiators": ("Largest domestic US network, strong Amex co-brand, high app satisfaction", "extracted", 0.85, 2),
            "competitive_position.weaknesses": ("No fixed award chart; miles value eroded by dynamic pricing", "extracted", 0.82, 2),
            "competitive_position.closest_competitors": ("United MileagePlus, American AAdvantage, Southwest Rapid Rewards", "extracted", 0.90, 3),
        },
    },
    "marriott bonvoy": {
        "program_name": "Marriott Bonvoy",
        "brand": "Marriott International",
        "fields": {
            "program_basics.program_name": ("Marriott Bonvoy", "extracted", 0.99, 5),
            "program_basics.brand": ("Marriott International", "extracted", 0.99, 5),
            "program_basics.industry": ("Hotel", "extracted", 0.98, 4),
            "program_basics.program_type": ("Hotel Loyalty", "extracted", 0.97, 4),
            "program_basics.geography": ("Global — 140+ countries", "extracted", 0.96, 4),
            "program_basics.membership_count": ("Over 196 million members", "extracted", 0.88, 3),
            "earn_mechanics.base_earn_rate": ("10 points per $1 at Marriott hotels", "extracted", 0.95, 4),
            "earn_mechanics.bonus_categories": ("Elite status earns 25–75% bonus; co-brand card earns 6x at hotels", "extracted", 0.90, 3),
            "earn_mechanics.non_transactional_earn": ("Points via Chase/Amex Bonvoy cards, dining, car rentals, retail partners", "extracted", 0.84, 3),
            "burn_mechanics.redemption_options": ("Free nights, room upgrades, airline miles transfer (39 partners), experiences", "extracted", 0.93, 4),
            "burn_mechanics.redemption_thresholds": ("Category 1 hotels from 7,500 pts/night; Category 8 up to 100,000 pts/night", "extracted", 0.89, 3),
            "burn_mechanics.point_value_cpp": ("~0.7–0.9 cents per point", "extracted", 0.77, 2),
            "burn_mechanics.expiry_policy": ("Points expire after 24 months of inactivity", "extracted", 0.92, 3),
            "tier_system.tier_names": ("Member, Silver Elite, Gold Elite, Platinum Elite, Titanium Elite, Ambassador Elite", "extracted", 0.97, 5),
            "tier_system.qualification_criteria": ("Nights stayed per calendar year: Silver 10, Gold 25, Platinum 50, Titanium 75, Ambassador 100", "extracted", 0.95, 4),
            "tier_system.tier_benefits": ("Room upgrades, lounge access (Platinum+), Welcome Gift, late checkout, dedicated Ambassador service", "extracted", 0.90, 4),
            "tier_system.qualification_period": ("January 1 – December 31", "extracted", 0.97, 4),
            "partnerships.partner_names": ("Chase, American Express, United, Delta, Air Canada, Hertz, Uber", "extracted", 0.88, 3),
            "partnerships.partnership_type": ("Credit card, airline transfer, car rental, rideshare", "extracted", 0.86, 3),
            "partnerships.details": ("Transfer to 39 airlines at 3:1 ratio with 5,000-pt bonus on 60,000+ transfer", "extracted", 0.82, 3),
            "digital_experience.mobile_app_available": ("Yes — Marriott Bonvoy app on iOS and Android", "extracted", 0.99, 5),
            "digital_experience.app_ratings": ("4.8 / 5 App Store ; 4.2 / 5 Play Store", "extracted", 0.85, 3),
            "digital_experience.personalization_features": ("Mobile check-in/out, digital key, room preference selection", "extracted", 0.85, 3),
            "digital_experience.gamification_features": ("Marriott Bonvoy Moments (experiences auction), limited earning promotions", "extracted", 0.74, 2),
            "member_sentiment.ratings": ("Mixed — elites satisfied, general members critical of award inflation", "ambiguous", 0.70, 2),
            "member_sentiment.common_praise": ("Vast property portfolio, airline transfer flexibility, strong elite benefits", "extracted", 0.82, 3),
            "member_sentiment.common_complaints": ("Point devaluation after merger, inconsistent elite recognition at properties", "extracted", 0.85, 3),
            "member_sentiment.sources_checked": ("FlyerTalk, Reddit r/marriott, Trustpilot, App Store", "extracted", 0.90, 3),
            "competitive_position.key_differentiators": ("Largest hotel portfolio globally, airline transfer to 39 carriers", "extracted", 0.88, 3),
            "competitive_position.weaknesses": ("Post-merger inconsistency; ~0.7 cpp point value trails Hyatt World of Hyatt", "extracted", 0.80, 2),
            "competitive_position.closest_competitors": ("Hilton Honors, World of Hyatt, IHG One Rewards", "extracted", 0.91, 4),
        },
    },
    "hilton honors": {
        "program_name": "Hilton Honors",
        "brand": "Hilton Worldwide",
        "fields": {
            "program_basics.program_name": ("Hilton Honors", "extracted", 0.99, 5),
            "program_basics.brand": ("Hilton Worldwide", "extracted", 0.99, 4),
            "program_basics.industry": ("Hotel", "extracted", 0.98, 4),
            "program_basics.program_type": ("Hotel Loyalty", "extracted", 0.97, 4),
            "program_basics.geography": ("Global — 122+ countries", "extracted", 0.95, 4),
            "program_basics.membership_count": ("Over 180 million members", "extracted", 0.86, 3),
            "earn_mechanics.base_earn_rate": ("10 points per $1 at Hilton hotels", "extracted", 0.95, 4),
            "earn_mechanics.bonus_categories": ("Elite bonus 25–100%; Amex Hilton Surpass earns 12x at Hilton", "extracted", 0.88, 3),
            "earn_mechanics.non_transactional_earn": ("Amex co-brand cards, dining via Hilton Honors Dining, partner earn", "extracted", 0.82, 3),
            "burn_mechanics.redemption_options": ("Free nights (Points & Money available), room upgrades, Amazon, charity", "extracted", 0.90, 3),
            "burn_mechanics.redemption_thresholds": ("Standard rewards start ~5,000 pts; premium properties up to 150,000 pts/night", "extracted", 0.85, 3),
            "burn_mechanics.point_value_cpp": ("~0.5–0.6 cents per point — lower than Marriott", "extracted", 0.75, 2),
            "burn_mechanics.expiry_policy": ("Points expire after 12 months of inactivity", "extracted", 0.91, 3),
            "tier_system.tier_names": ("Member, Silver, Gold, Diamond", "extracted", 0.97, 5),
            "tier_system.qualification_criteria": ("Nights: Silver 10, Gold 40, Diamond 60 per year", "extracted", 0.94, 4),
            "tier_system.tier_benefits": ("Executive Lounge (Diamond), complimentary breakfast (Diamond), room upgrades, 100% bonus points", "extracted", 0.89, 4),
            "tier_system.qualification_period": ("January 1 – December 31", "extracted", 0.97, 4),
            "partnerships.partner_names": ("American Express, Amazon, Lyft, CarRentals.com, Ticketmaster", "extracted", 0.85, 3),
            "partnerships.partnership_type": ("Credit card, retail, rideshare, car rental, entertainment", "extracted", 0.83, 2),
            "partnerships.details": ("Amex Hilton cards offer 7–14x at Hilton; Amazon earn via Hilton portal; no airline transfer", "extracted", 0.80, 2),
            "digital_experience.mobile_app_available": ("Yes — Hilton Honors app on iOS and Android", "extracted", 0.99, 5),
            "digital_experience.app_ratings": ("4.8 / 5 App Store ; 4.6 / 5 Play Store", "extracted", 0.88, 3),
            "digital_experience.personalization_features": ("Digital key, room selection, mobile check-in/out, Connected Room (IoT control)", "extracted", 0.87, 3),
            "digital_experience.gamification_features": ("Hilton Honors Challenges, bonus point promotions, seasonal offers", "extracted", 0.76, 2),
            "member_sentiment.ratings": ("Positive — Diamond members highly satisfied with breakfast and lounge benefits", "extracted", 0.79, 3),
            "member_sentiment.common_praise": ("Consistent complimentary breakfast for Diamond, strong app experience, broad portfolio", "extracted", 0.83, 3),
            "member_sentiment.common_complaints": ("Lower point value vs competitors; no airline transfer partners", "extracted", 0.81, 3),
            "member_sentiment.sources_checked": ("FlyerTalk, Reddit r/hilton, Trustpilot, App Store", "extracted", 0.90, 3),
            "competitive_position.key_differentiators": ("Complimentary Diamond breakfast globally, strong Connected Room tech, Amex partnership", "extracted", 0.86, 3),
            "competitive_position.weaknesses": ("No airline miles transfer; ~0.5 cpp among lowest in hotel space", "extracted", 0.82, 2),
            "competitive_position.closest_competitors": ("Marriott Bonvoy, World of Hyatt, IHG One Rewards", "extracted", 0.91, 4),
        },
    },
}


from datetime import date as _date

_TODAY = str(_date.today())

# Raw conflicts injected into state["conflicts"] before adjudication_node runs.
# claim_a / claim_b must match the dict shape produced by _claim_from_group():
#   value, source_url, date, authority, corroboration, confidence
# Score gap ≤ 0.20  → real Groq debate  |  gap > 0.20 → auto-resolved
_MOCK_CONFLICTS: dict[str, list[dict[str, Any]]] = {
    "delta skymiles": [
        # ① Close gap → real debate
        {
            "field_name": "burn_mechanics.point_value_cpp",
            "volatility": "HIGH",
            "claim_a": {
                "value": "~1.3 cents per mile (based on flight redemptions)",
                "source_url": "https://thepointsguy.com/guide/monthly-valuations/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 3,
                "confidence": 0.74,
            },
            "claim_b": {
                "value": "~0.9–1.1 cents per mile (average across all redemptions)",
                "source_url": "https://nerdwallet.com/article/travel/delta-skymiles-value",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.68,
            },
        },
        # ② Close gap → real debate
        {
            "field_name": "earn_mechanics.base_earn_rate",
            "volatility": "HIGH",
            "claim_a": {
                "value": "5 miles per $1 on Delta flights (Main Cabin)",
                "source_url": "https://www.delta.com/us/en/skymiles/how-to-earn-miles",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.93,
            },
            "claim_b": {
                "value": "5–10 miles per $1 depending on fare class and Medallion status",
                "source_url": "https://thepointsguy.com/guide/delta-skymiles-earning/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.80,
            },
        },
        # ③ Wide gap → auto-resolved
        {
            "field_name": "burn_mechanics.expiry_policy",
            "volatility": "LOW",
            "claim_a": {
                "value": "Miles never expire",
                "source_url": "https://old-blog.example.com/delta-miles-expire",
                "date": "2019-01-15",
                "authority": "blog",
                "corroboration": 1,
                "confidence": 0.30,
            },
            "claim_b": {
                "value": "Miles expire after 24 months of account inactivity",
                "source_url": "https://www.delta.com/us/en/skymiles/skymiles-program-overview",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 3,
                "confidence": 0.91,
            },
        },
        # ④ Close gap → real debate
        {
            "field_name": "tier_system.tier_thresholds",
            "volatility": "HIGH",
            "claim_a": {
                "value": "Silver: $3,000 MQD; Gold: $8,000 MQD; Platinum: $12,000 MQD; Diamond: $20,000 MQD",
                "source_url": "https://www.delta.com/us/en/skymiles/medallion-program",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 3,
                "confidence": 0.88,
            },
            "claim_b": {
                "value": "Silver: $3,000 MQD; Gold: $8,000 MQD; Platinum: $15,000 MQD; Diamond: $28,000 MQD (2024 revised)",
                "source_url": "https://thepointsguy.com/news/delta-medallion-2024-changes/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.76,
            },
        },
    ],
    "marriott bonvoy": [
        # ① Close gap → real debate
        {
            "field_name": "burn_mechanics.point_value_cpp",
            "volatility": "HIGH",
            "claim_a": {
                "value": "~0.9 cents per point on free night redemptions",
                "source_url": "https://thepointsguy.com/guide/monthly-valuations/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 3,
                "confidence": 0.77,
            },
            "claim_b": {
                "value": "~0.7 cents per point (average across all redemption types)",
                "source_url": "https://nerdwallet.com/article/travel/marriott-bonvoy-points-value",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.68,
            },
        },
        # ② Close gap → real debate
        {
            "field_name": "tier_system.qualification_criteria",
            "volatility": "LOW",
            "claim_a": {
                "value": "Nights only: Silver 10, Gold 25, Platinum 50, Titanium 75, Ambassador 100",
                "source_url": "https://www.marriott.com/loyalty/member-benefits/eliteMemberBenefits.mi",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.91,
            },
            "claim_b": {
                "value": "Nights or revenue: Silver 10 nights or $3,000; Gold 25 nights or $10,000 spend",
                "source_url": "https://thepointsguy.com/guide/marriott-bonvoy-status/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.78,
            },
        },
        # ③ Wide gap → auto-resolved
        {
            "field_name": "burn_mechanics.expiry_policy",
            "volatility": "LOW",
            "claim_a": {
                "value": "Points expire after 12 months of inactivity",
                "source_url": "https://old-travel-blog.example.com/bonvoy-expiry",
                "date": "2020-03-10",
                "authority": "blog",
                "corroboration": 1,
                "confidence": 0.35,
            },
            "claim_b": {
                "value": "Points expire after 24 months of account inactivity",
                "source_url": "https://www.marriott.com/loyalty/terms/default.mi",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.95,
            },
        },
        # ④ Close gap → real debate
        {
            "field_name": "partnerships.transfer_ratios",
            "volatility": "LOW",
            "claim_a": {
                "value": "3:1 Marriott points to airline miles (e.g. 3,000 pts = 1,000 miles)",
                "source_url": "https://www.marriott.com/loyalty/redeem/travel/air.mi",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.89,
            },
            "claim_b": {
                "value": "3:1 ratio with a 5,000-mile bonus per 60,000-point transfer block",
                "source_url": "https://thepointsguy.com/guide/transfer-marriott-to-airlines/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 3,
                "confidence": 0.82,
            },
        },
    ],
    "hilton honors": [
        # ① Close gap → real debate
        {
            "field_name": "burn_mechanics.point_value_cpp",
            "volatility": "HIGH",
            "claim_a": {
                "value": "~0.6 cents per point for standard room redemptions",
                "source_url": "https://thepointsguy.com/guide/monthly-valuations/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 3,
                "confidence": 0.72,
            },
            "claim_b": {
                "value": "~0.5 cents per point on average across all redemption types",
                "source_url": "https://nerdwallet.com/article/travel/hilton-honors-points-value",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.65,
            },
        },
        # ② Close gap → real debate
        {
            "field_name": "tier_system.tier_benefits",
            "volatility": "LOW",
            "claim_a": {
                "value": "Diamond: complimentary breakfast, executive lounge, 100% bonus points, suite upgrades",
                "source_url": "https://www.hilton.com/en/hilton-honors/member-benefits/",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.90,
            },
            "claim_b": {
                "value": "Diamond: breakfast at select properties only; lounge access not guaranteed at all brands",
                "source_url": "https://thepointsguy.com/guide/hilton-diamond-benefits/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 3,
                "confidence": 0.78,
            },
        },
        # ③ Wide gap → auto-resolved
        {
            "field_name": "burn_mechanics.expiry_policy",
            "volatility": "LOW",
            "claim_a": {
                "value": "Points expire after 24 months of inactivity",
                "source_url": "https://old-hilton-blog.example.com/expiry",
                "date": "2018-06-01",
                "authority": "blog",
                "corroboration": 1,
                "confidence": 0.28,
            },
            "claim_b": {
                "value": "Points expire after 12 months of account inactivity",
                "source_url": "https://www.hilton.com/en/hilton-honors/terms-conditions/",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.94,
            },
        },
        # ④ Close gap → real debate
        {
            "field_name": "earn_mechanics.base_earn_rate",
            "volatility": "HIGH",
            "claim_a": {
                "value": "10 points per $1 spent at Hilton portfolio properties",
                "source_url": "https://www.hilton.com/en/hilton-honors/earn-points/",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 5,
                "confidence": 0.95,
            },
            "claim_b": {
                "value": "10 base points per $1 plus 5x bonus points = 15 points per $1 effective rate",
                "source_url": "https://thepointsguy.com/guide/hilton-honors-earn/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.80,
            },
        },
    ],
}


def _fuzzy_match_profile(user_input: str) -> str | None:
    """Match user input to a known mock profile key."""
    needle = user_input.lower().strip()
    for key in _MOCK_PROFILES:
        if key in needle or any(word in needle for word in key.split()):
            return key
    return None


def _build_mock_field_report(profile_key: str) -> FieldReport:
    profile = _MOCK_PROFILES[profile_key]
    entries: list[FieldReportEntry] = []
    extracted = ambiguous = not_found = 0
    for field_path, (value, status, confidence, corroboration) in profile["fields"].items():
        category = field_path.split(".")[0]
        entry = FieldReportEntry(
            field_path=field_path,
            category=category,
            status=status,
            value=value,
            confidence=confidence,
            corroboration_count=corroboration,
            source_urls=[f"https://mock-source.example/{profile_key.replace(' ', '-')}/{field_path}"],
            source_snippet=f"Mock source for {field_path}: {value}",
        )
        entries.append(entry)
        if status == "extracted":
            extracted += 1
        elif status == "ambiguous":
            ambiguous += 1
        else:
            not_found += 1

    return FieldReport(
        entity_name=profile["program_name"],
        entries=entries,
        extracted_count=extracted,
        ambiguous_count=ambiguous,
        not_found_count=not_found,
        flagged_count=0,
    )


def _run_mock_single(record: RunRecord, prog: str) -> None:
    """Run the mock pipeline for one program (record already reset for this prog)."""
    cost_tracker.set_active_run_id(record.run_id)
    program_key = _fuzzy_match_profile(prog) or "delta skymiles"
    profile = _MOCK_PROFILES[program_key]

    for stage in ["input_validator", "query_generator", "retrieval", "firecrawl_scraper", "chunking", "extraction"]:
        _mark(record, stage, "done")

    _mark(record, "claims", "running")
    field_report = _build_mock_field_report(program_key)
    raw_conflicts = _MOCK_CONFLICTS.get(program_key, [])
    _apply(record, {
        "program_name": profile["program_name"],
        "brand": profile["brand"],
        "field_report": field_report,
        "conflicts": raw_conflicts,
        "adjudicated": [],
    })
    _mark(record, "claims", "done")

    state = record.state

    _mark(record, "adjudication", "running")
    try:
        delta = adjudication_node(state)
        state = _apply(record, delta)
        _mark(record, "adjudication", "done")
    except Exception as exc:
        _apply(record, {"errors": [*state.get("errors", []), {"stage": "adjudication", "message": str(exc)}]})
        _mark(record, "adjudication", "error")

    _mark(record, "output", "running")
    try:
        delta = narrator_node(state)
        _apply(record, delta)
        _mark(record, "output", "done")
    except Exception as exc:
        _apply(record, {"errors": [*state.get("errors", []), {"stage": "output", "message": str(exc)}]})
        _mark(record, "output", "error")


def _run_mock_pipeline(record: RunRecord) -> None:
    """Skip retrieval/extraction; inject mock field_report and run from claims onward."""
    if record.mode == "compare" and len(record.programs) >= 2:
        all_claims: list[list] = [[] for _ in record.programs]
        all_names: list[str] = list(record.programs)
        all_field_reports_mock: list[Any] = [None] * len(record.programs)

        for i, prog in enumerate(record.programs):
            if _stopped(record):
                break
            _reset_record_for_program(record, prog, i)
            _run_mock_single(record, prog)
            with record.lock:
                all_field_reports_mock[i] = record.state.get("field_report")
            _save_program_result(record, i, True, all_claims, all_names)
            prog_state = record.program_states[i]
            if prog_state:
                _save_program_snapshot_to_db(
                    all_names[i],
                    prog_state.get("brand"),
                    prog_state.get("country_or_region"),
                    prog_state,
                )

        done_indices = [i for i, s in enumerate(record.program_statuses) if s == "done"]
        if len(done_indices) >= 2:
            with record.lock:
                record.compare_b = record.program_states[done_indices[1]]
                state_a = record.program_states[done_indices[0]]
                if state_a is not None:
                    record.state = dict(state_a)

            try:
                from core.schemas import FieldReport as _FieldReport
                brief_names = [all_names[i] for i in done_indices]
                brief_reports = []
                for i in done_indices:
                    fr = all_field_reports_mock[i]
                    if isinstance(fr, _FieldReport):
                        brief_reports.append(fr)
                    elif isinstance(fr, dict):
                        brief_reports.append(_FieldReport.model_validate(fr))
                if len(brief_reports) >= 2:
                    brief = generate_comparison_brief(record.run_id, brief_names, brief_reports)
                    with record.lock:
                        record.state = {**record.state, "comparison_brief": brief}
            except Exception:
                logger.exception("[%s] mock comparison brief generation failed", record.run_id)

        done_indices_mock = [i for i, s in enumerate(record.program_statuses) if s == "done"]
        done_names_mock = [all_names[i] for i in done_indices_mock]
        if done_names_mock:
            with record.lock:
                record.comparison_conversation = [
                    {
                        "role": "assistant",
                        "message": (
                            f"I've completed the comparison of {' vs '.join(done_names_mock)}. "
                            "Ask me about differences, category winners, key metrics, or any "
                            "specific aspect of the comparison — I'll answer only from the "
                            "extracted and compared data."
                        ),
                        "created_at": now_iso(),
                    }
                ]
        with record.lock:
            record.run_status = "done"
        return

    # Single program mock
    _run_mock_single(record, record.user_input)
    program_name = record.state.get("program_name") or record.user_input
    snap = _make_program_state_snapshot(record)
    _save_program_snapshot_to_db(
        program_name,
        record.state.get("brand"),
        record.state.get("country_or_region"),
        snap,
    )
    with record.lock:
        record.conversation = [
            {
                "role": "assistant",
                "message": (
                    f"I've analysed {program_name}. Ask me anything about its earn "
                    "rates, tiers, partners, or member sentiment — I'll answer only "
                    "from the extracted claims."
                ),
                "created_at": now_iso(),
            }
        ]
        record.run_status = "done"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/cache/check")
def cache_check(q: str) -> dict[str, Any]:
    """Check whether a single program has a stored analysis in the DB cache."""
    snapshot = _db.find_program_snapshot(_db_conn, q.strip())
    if snapshot is None:
        return {"found": False}
    return _snapshot_meta(snapshot)


@app.get("/api/cache/check-multi")
def cache_check_multi(programs: list[str] = Query(default=[])) -> list[dict[str, Any]]:
    """Check cache for multiple programs; returns one result per program in order."""
    results: list[dict[str, Any]] = []
    for prog in programs:
        snapshot = _db.find_program_snapshot(_db_conn, prog.strip())
        if snapshot:
            item = _snapshot_meta(snapshot)
            item["program"] = prog
        else:
            item = {"found": False, "program": prog}
        results.append(item)
    return results


@app.get("/api/run/history")
def run_history() -> list[dict[str, Any]]:
    """Return persisted analyses plus live runs currently held in memory."""
    result_map: dict[str, dict[str, Any]] = {}

    def upsert(item: dict[str, Any], priority: int) -> None:
        run_id = item.get("run_id") or ""
        if not run_id:
            return
        current = result_map.get(run_id)
        if current is None or priority >= current["_priority"]:
            result_map[run_id] = {**item, "_priority": priority}

    for row in _db.list_program_snapshots(_db_conn, limit=100):
        try:
            state = json.loads(row["program_state_json"])
        except Exception:
            continue
        run_id = state.get("run_id", "")
        upsert({
            "run_id": run_id,
            "user_input": state.get("user_input") or row["program_name"],
            "mode": state.get("mode") or "single",
            "program_name": row["program_name"],
            "data_quality": state.get("data_quality", 0.0),
            "status": state.get("status") or "done",
            "created_at": row["created_at"],
            "source": "db",
        }, priority=1)

    for row in _db.list_runs(_db_conn, limit=200):
        upsert({
            "run_id": row["run_id"],
            "user_input": row["user_input"],
            "mode": row["mode"],
            "program_name": row["program_name"] or row["user_input"],
            "data_quality": row["data_quality"],
            "status": row["status"],
            "created_at": row["created_at"],
            "source": "db",
        }, priority=2)

    live_run_ids: set[str] = set()
    with STORE_LOCK:
        records = list(STORE.values())
    for record in records:
        summary = build_summary(record)
        live_run_ids.add(summary.get("run_id", ""))
        with record.lock:
            program_name = (
                " vs ".join(record.programs)
                if record.mode == "compare" and len(record.programs) >= 2
                else record.state.get("program_name")
            )
        upsert({
            **summary,
            "program_name": program_name,
            "source": "live",
        }, priority=3)

    result = [dict(item) for item in result_map.values()]
    for item in result:
        item.pop("_priority", None)
        # Runs that are "running" in the DB but not in the live in-memory store
        # are orphaned (server was restarted mid-run). Treat them as cancelled.
        if item.get("status") == "running" and item.get("run_id") not in live_run_ids:
            item["status"] = "cancelled"
    result.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    return result


@app.post("/api/run", status_code=201)
def create_run(body: CreateRunBody) -> dict[str, str]:
    if not body.user_input.strip():
        raise HTTPException(status_code=400, detail="user_input is required")

    mode = body.mode if body.mode in ("single", "compare", "converse") else "single"
    run_id = new_id("run")

    # Normalise programs list for compare mode
    programs_list: list[str] | None = None
    if mode == "compare" and body.programs:
        clean = [p.strip() for p in body.programs if p.strip()]
        if len(clean) >= 2:
            programs_list = clean

    record = RunRecord(run_id, body.user_input.strip(), mode, body.user_input_b, programs_list,
                       force_fresh=body.force_fresh)
    with STORE_LOCK:
        STORE[run_id] = record
    _persist_run_summary(record)

    # Single-mode cache short-circuit: restore immediately without starting pipeline thread
    if not body.mock and not body.force_fresh and mode == "single":
        snapshot = _db.find_program_snapshot(_db_conn, body.user_input.strip())
        if snapshot:
            _restore_single_from_cache(record, snapshot)
            _persist_run_summary(record)
            logger.info("[%s] served from cache for %r", run_id, body.user_input.strip())
            return {"run_id": run_id}

    target = _run_mock_pipeline if body.mock else run_pipeline
    threading.Thread(target=target, args=(record,), daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/run")
def list_runs() -> list[dict[str, Any]]:
    with STORE_LOCK:
        records = list(STORE.values())
    return sorted(
        [build_summary(r) for r in records],
        key=lambda s: s["created_at"],
        reverse=True,
    )


@app.get("/api/run/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with STORE_LOCK:
        record = STORE.get(run_id)
    if record is None:
        # Prefer the runs table (has correct mode + full state for new runs).
        # Fall back to run_snapshots for older single-mode runs that predate _persist_run_summary.
        row = _db.find_run(_db_conn, run_id)
        if row is not None:
            payload = _compare_run_response_from_row(row) if row.get("mode") == "compare" else _run_response_from_row(row)
            if payload is not None:
                return payload
        snapshot = _db.find_program_snapshot_by_run_id(_db_conn, run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run not found")
        return _snapshot_run_response(snapshot)
    return build_run_response(record)


def _do_delete_run(run_id: str) -> dict[str, Any]:
    with STORE_LOCK:
        STORE.pop(run_id, None)
    deleted = _db.delete_run(_db_conn, run_id)
    snapshots = _db.list_program_snapshots_by_run_id(_db_conn, run_id)
    for snap in snapshots:
        _db.delete_run_snapshot(_db_conn, snap["program_name_normalized"])
    return {"ok": True, "deleted": deleted}

@app.delete("/api/run/{run_id}", status_code=200)
def delete_run(run_id: str) -> dict[str, Any]:
    """Remove a run from the in-memory store and the persistent DB."""
    return _do_delete_run(run_id)

@app.post("/api/run/{run_id}/delete", status_code=200)
def delete_run_post(run_id: str) -> dict[str, Any]:
    """POST alias for DELETE — used by Next.js proxy which has issues with DELETE method."""
    return _do_delete_run(run_id)


@app.post("/api/run/{run_id}/clarify")
def clarify(run_id: str, body: ClarifyRequest) -> dict[str, Any]:
    with STORE_LOCK:
        record = STORE.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not body.answer.strip():
        raise HTTPException(status_code=400, detail="answer is required")

    with record.lock:
        if record.run_status != "clarification_needed":
            raise HTTPException(status_code=400, detail="run is not waiting for clarification")
        messages: list[dict[str, str]] = list(record.state.get("validation_messages") or [])
        vr = record.state.get("validation_result")
        if vr is not None:
            messages.append({"role": "assistant", "content": json.dumps(vr.model_dump())})
        messages.append({"role": "user", "content": body.answer.strip()})
        record.state["validation_messages"] = messages

    record.clarification_event.set()
    return {"ok": True}


@app.post("/api/run/{run_id}/converse")
def converse(run_id: str, body: ConverseRequest) -> dict[str, Any]:
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    with STORE_LOCK:
        record = STORE.get(run_id)
    if record is None:
        return _single_converse_from_db(run_id, body.message.strip())

    with record.lock:
        final_brief: BriefOutput | None = record.state.get("final_brief")
        field_report: FieldReport | None = record.state.get("field_report")

    if final_brief is None:
        raise HTTPException(status_code=400, detail="Pipeline has not completed — no brief available yet.")

    cost_tracker.set_active_run_id(run_id)
    try:
        answer = answer_question(body.message.strip(), final_brief, field_report)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    created_at = now_iso()
    with record.lock:
        record.conversation.append(
            {"role": "user", "message": body.message.strip(), "created_at": created_at}
        )
        record.conversation.append(
            {
                "role": "assistant",
                "message": answer.answer,
                "answer": answer.model_dump(),
                "created_at": created_at,
            }
        )

    return answer.model_dump()


@app.post("/api/run/{run_id}/generate-brief")
def trigger_generate_brief(run_id: str) -> dict[str, Any]:
    """Generate (or return cached) comparison brief for a stored compare run."""
    # If run is live in memory and brief already exists, return it
    with STORE_LOCK:
        record = STORE.get(run_id)
    if record is not None:
        with record.lock:
            existing = record.state.get("comparison_brief")
        if existing is not None:
            return _ser(existing) if hasattr(existing, "model_dump") else existing

    # Load from DB
    row = _db.find_run(_db_conn, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    if row.get("mode") != "compare":
        raise HTTPException(status_code=400, detail="not a comparison run")

    payload = _run_response_from_row(row) or _compare_run_response_from_row(row)
    if payload is None:
        raise HTTPException(status_code=400, detail="run state not available")

    # Return cached brief only if it's a real one (has populated category_verdicts).
    # Stub briefs produced by _comparison_brief_stub always have category_verdicts=[].
    existing_brief = payload.get("comparison_brief")
    if existing_brief and isinstance(existing_brief.get("category_verdicts"), list) and len(existing_brief["category_verdicts"]) > 0:
        return existing_brief

    # Extract program states and field reports
    comp_run = payload.get("comparison_run") or {}
    prog_states: list[dict | None] = comp_run.get("program_states") or []
    prog_names: list[str] = comp_run.get("programs") or []

    from core.schemas import FieldReport as _FR
    brief_reports: list = []
    brief_names: list[str] = []
    for i, ps in enumerate(prog_states):
        if not isinstance(ps, dict):
            continue
        name = prog_names[i] if i < len(prog_names) else f"Program {i + 1}"
        fr_raw = ps.get("field_report")
        if isinstance(fr_raw, dict):
            try:
                brief_reports.append(_FR.model_validate(fr_raw))
                brief_names.append(name)
            except Exception:
                pass

    if len(brief_reports) < 2:
        raise HTTPException(
            status_code=400,
            detail="Not enough program field data to generate brief. Re-run the comparison.",
        )

    cost_tracker.set_active_run_id(run_id)
    try:
        brief = generate_comparison_brief(run_id, brief_names, brief_reports)
    except Exception as exc:
        logger.exception("[%s] on-demand brief generation failed", run_id)
        raise HTTPException(status_code=500, detail=f"Brief generation failed: {exc}")

    brief_dict = _ser(brief)

    # Persist the updated state so future loads have the brief
    try:
        payload["comparison_brief"] = brief_dict
        summary_state = {
            "run_id": run_id,
            "mode": "compare",
            "user_input": payload.get("user_input", ""),
            "program_name": payload.get("program_name") or " vs ".join(brief_names),
            "domain": payload.get("domain"),
            "data_quality": payload.get("data_quality", 0),
            "created_at": payload.get("created_at"),
        }
        _db.upsert_run(
            _db_conn,
            summary_state,
            status="done",
            run_state_json=json.dumps(payload, default=str),
        )
        logger.info("[%s] brief generated and persisted for %s", run_id, " vs ".join(brief_names))
    except Exception:
        logger.exception("[%s] failed to persist generated brief", run_id)

    return brief_dict


@app.post("/api/run/{run_id}/stop")
def stop_run(run_id: str) -> dict[str, Any]:
    with STORE_LOCK:
        record = STORE.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    with record.lock:
        if record.run_status not in ("running", "clarification_needed"):
            raise HTTPException(status_code=400, detail="run is not in progress")
        record.run_status = "cancelled"
    record.stop_event.set()
    record.clarification_event.set()  # unblock any waiting clarification
    return {"ok": True}
