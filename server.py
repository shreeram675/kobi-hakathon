"""FastAPI REST backend for the Kobie Next.js frontend.

Endpoints:
  POST /api/run               → start a pipeline run (background thread)
  GET  /api/run               → list all run summaries
  GET  /api/run/{run_id}      → poll a single run (includes stage_status, status, conversation)
  POST /api/run/{run_id}/clarify  → submit a clarification answer for the input validator
  POST /api/run/{run_id}/converse → answer a grounded question
"""
from __future__ import annotations

import json
import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel as _PydanticBase

from schemas import (
    AgentState,
    BriefOutput,
    FieldReport,
    build_initial_state,
    new_id,
    now_iso,
    RunMode,
)
from graph import (
    input_validator_node,
    query_generator_node,
    retrieval_node,
    firecrawl_node,
    ingest_node,
    adjudication_node,
    narrator_node,
)
from comparison import compare_claim_sets
from converse import answer_question

app = FastAPI(title="Kobie API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    ) -> None:
        self.run_id = run_id
        self.user_input = user_input
        self.user_input_b = user_input_b
        self.mode = mode
        self.state: AgentState = build_initial_state(user_input, RunMode(mode))
        self.state["run_id"] = run_id
        self.stage_status: dict[str, str] = {s: "idle" for s in UI_STAGES}
        self.active_stage: str | None = None
        self.run_status: str = "running"
        self.conversation: list[dict[str, Any]] = []
        self.compare_b: dict[str, Any] | None = None
        self.lock = threading.Lock()
        self.clarification_event = threading.Event()


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
    with record.lock:
        result: dict[str, Any] = {k: _ser(v) for k, v in record.state.items()}
        result["stage_status"] = dict(record.stage_status)
        result["active_stage"] = record.active_stage
        result["status"] = record.run_status
        result["conversation"] = list(record.conversation)
        if record.compare_b is not None:
            result["compare_b"] = record.compare_b
    return result


def build_summary(record: RunRecord) -> dict[str, Any]:
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


# ── Core pipeline (single program) ────────────────────────────────────────────
def _run_single_pipeline(record: RunRecord) -> bool:
    """Run one program through all pipeline stages. Returns True on success."""
    state = record.state

    # 1. Input Validator — loop until resolved, rejected, or clarification timeout
    _mark(record, "input_validator", "running")
    clarification_count = 0
    while True:
        try:
            delta = input_validator_node(state)
            state = _apply(record, delta)
        except Exception:
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
        _mark(record, "query_generator", "error")
        return False

    # 3. Retrieval
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
        _mark(record, "retrieval", "error")
        return False

    # 4. Firecrawl Scraper
    _mark(record, "firecrawl_scraper", "running")
    try:
        delta = firecrawl_node(state)
        state = _apply(record, delta)
        fc = state.get("firecrawl_result")
        if fc and fc.successful_scrapes > 0:
            _mark(record, "firecrawl_scraper", "done")
        else:
            _mark(record, "firecrawl_scraper", "error")
            return False
    except Exception:
        _mark(record, "firecrawl_scraper", "error")
        return False

    # 5–7. Ingest (raw store → chunking → extraction → claims)
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
        _mark(record, "chunking", "error")
        _mark(record, "extraction", "error")
        _mark(record, "claims", "error")
        return False

    # 8. Adjudication
    _mark(record, "adjudication", "running")
    try:
        delta = adjudication_node(state)
        state = _apply(record, delta)
        _mark(record, "adjudication", "done")
    except Exception:
        _mark(record, "adjudication", "error")
        return False

    # 9. Narration → output
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
        _mark(record, "output", "error")
        return False

    return True


# ── Pipeline thread entry points ──────────────────────────────────────────────
def run_pipeline(record: RunRecord) -> None:
    """Thread entry point — handles single, compare, and converse modes."""
    if record.mode == "compare" and record.user_input_b:
        # Run program A
        success_a = _run_single_pipeline(record)

        # Run program B in parallel (separate record, not in STORE)
        record_b = RunRecord(record.run_id + "_b", record.user_input_b, "compare")
        thread_b = threading.Thread(
            target=_run_single_pipeline, args=(record_b,), daemon=True
        )
        thread_b.start()
        thread_b.join()

        if success_a and record_b.run_status != "error":
            a_state = record.state
            b_state = record_b.state
            try:
                comparison = compare_claim_sets(
                    record.run_id,
                    a_state.get("program_name") or record.user_input,
                    b_state.get("program_name") or record.user_input_b,
                    a_state.get("adjudicated_claims", []),
                    b_state.get("adjudicated_claims", []),
                )
                with record.lock:
                    record.state = {**record.state, "comparison_output": comparison}
            except Exception:
                pass

            with record.lock:
                record.compare_b = build_run_response(record_b)

        with record.lock:
            record.run_status = "done" if success_a else "error"

    else:
        success = _run_single_pipeline(record)

        if success and record.mode == "converse":
            program_name = record.state.get("program_name") or record.user_input
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


# ── Request / response models ─────────────────────────────────────────────────
class CreateRunBody(_PydanticBase):
    user_input: str
    mode: str = "single"
    user_input_b: str | None = None


class ConverseRequest(_PydanticBase):
    message: str


class ClarifyRequest(_PydanticBase):
    answer: str


# ── Routes ────────────────────────────────────────────────────────────────────
@app.post("/api/run", status_code=201)
def create_run(body: CreateRunBody) -> dict[str, str]:
    if not body.user_input.strip():
        raise HTTPException(status_code=400, detail="user_input is required")

    mode = body.mode if body.mode in ("single", "compare", "converse") else "single"
    run_id = new_id("run")

    record = RunRecord(run_id, body.user_input.strip(), mode, body.user_input_b)
    with STORE_LOCK:
        STORE[run_id] = record

    threading.Thread(target=run_pipeline, args=(record,), daemon=True).start()
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
        raise HTTPException(status_code=404, detail="run not found")
    return build_run_response(record)


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
    with STORE_LOCK:
        record = STORE.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    with record.lock:
        final_brief: BriefOutput | None = record.state.get("final_brief")
        field_report: FieldReport | None = record.state.get("field_report")

    if final_brief is None:
        raise HTTPException(status_code=400, detail="Pipeline has not completed — no brief available yet.")

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
