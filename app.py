"""Streamlit UI for Kobie's validation-first flow."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from pipeline.graph import run_validation_chat, run_validation_chat_traced
from pipeline.schema_config import all_default_field_paths
from pipeline.stages.validation import verifier_result_as_message


st.set_page_config(page_title="Kobie Phase 2", layout="wide")

st.title("Kobie Phase 2")
st.caption("Grounded loyalty-program intelligence agent")


NODE_LABELS = {
    "input_validator": "Input Validator",
    "query_generator": "Query Generator",
    "retrieval": "Tavily Retrieval",
    "firecrawl_scraper": "Firecrawl Scraper",
    "raw_store": "Raw Store",
    "chunker": "Semantic Chunker",
    "gemini_extractor": "Gemini Extraction",
    "normalizer": "Normalizer + Hashing",
    "narration": "Narration",
}

INSPECTOR_NODES = (
    "input_validator",
    "query_generator",
    "retrieval",
    "firecrawl_scraper",
    "raw_store",
    "chunker",
    "gemini_extractor",
    "normalizer",
)


def result_to_assistant_text(result) -> str:
    if result.status == "rejected":
        return f"No such loyalty program found.\n\n{result.reason or 'Try a real program, brand, or alias.'}"
    if result.status == "resolved" and result.identity:
        return (
            "Resolved.\n\n"
            f"Program name: {result.identity.program_name}\n\n"
            f"Domain: {result.identity.domain}\n\n"
            f"Confidence: {result.confidence:.2f}"
        )
    questions = "\n".join(f"{index + 1}. {question}" for index, question in enumerate(result.follow_up_questions))
    if result.possible_matches:
        matches = "\n".join(
            f"- {match.program_name} ({match.brand}, {match.domain})" for match in result.possible_matches
        )
        return f"I need one clarification before starting retrieval.\n\nPossible matches:\n{matches}\n\n{questions}"
    return f"I need one clarification before starting retrieval.\n\n{questions}"


def reset_validator_chat() -> None:
    st.session_state.validator_chat = [
        {
            "role": "assistant",
            "content": "Which loyalty program should Kobie research?",
        }
    ]
    st.session_state.validator_llm_messages = []
    st.session_state.validation_result = None
    st.session_state.last_graph_state = None


def run_workflow_with_live_status(messages: list[dict[str, str]]):
    status_box = st.status("Running LangGraph workflow", expanded=True)

    def on_event(node: str, status: str, message: str) -> None:
        label = NODE_LABELS.get(node, node)
        status_box.write(f"{label}: {status} - {message}")

    state = run_validation_chat_traced(messages, on_event=on_event)
    if state.get("normalized_packets"):
        status_box.update(label="Workflow complete", state="complete", expanded=False)
    elif state.get("firecrawl_result"):
        status_box.update(label="Workflow complete", state="complete", expanded=False)
    elif state.get("validation_result") and state["validation_result"].status == "needs_clarification":
        status_box.update(label="Waiting for clarification", state="complete", expanded=False)
    elif state.get("errors"):
        status_box.update(label="Workflow stopped", state="error", expanded=True)
    else:
        status_box.update(label="Workflow stopped", state="complete", expanded=False)
    return state


def reset_compare_side(side: str) -> None:
    st.session_state[f"compare_{side}_input"] = ""
    st.session_state[f"compare_{side}_chat"] = [
        {
            "role": "assistant",
            "content": "Which loyalty program should Kobie compare?",
        }
    ]
    st.session_state[f"compare_{side}_llm_messages"] = []
    st.session_state[f"compare_{side}_state"] = None


def run_compare_side(side: str, program_input: str) -> None:
    if not program_input.strip():
        return

    prompt = program_input.strip()
    chat_key = f"compare_{side}_chat"
    llm_key = f"compare_{side}_llm_messages"

    st.session_state[chat_key].append({"role": "user", "content": prompt})
    st.session_state[llm_key].append({"role": "user", "content": prompt})

    state = run_validation_chat(st.session_state[llm_key])
    result = state["validation_result"]
    assistant_text = result_to_assistant_text(result)

    st.session_state[f"compare_{side}_state"] = state
    st.session_state[chat_key].append({"role": "assistant", "content": assistant_text})
    st.session_state[llm_key].append(verifier_result_as_message(result))


def run_compare_sides_parallel(program_a_input: str, program_b_input: str) -> None:
    prompts = {"a": program_a_input.strip(), "b": program_b_input.strip()}
    runnable_sides = {side: prompt for side, prompt in prompts.items() if prompt}
    if not runnable_sides:
        return

    llm_messages_by_side = {}
    for side, prompt in runnable_sides.items():
        chat_key = f"compare_{side}_chat"
        llm_key = f"compare_{side}_llm_messages"
        st.session_state[chat_key].append({"role": "user", "content": prompt})
        st.session_state[llm_key].append({"role": "user", "content": prompt})
        llm_messages_by_side[side] = list(st.session_state[llm_key])

    with ThreadPoolExecutor(max_workers=2) as executor:
        states_by_side = dict(
            zip(
                llm_messages_by_side,
                executor.map(run_validation_chat, llm_messages_by_side.values()),
            )
        )

    for side, state in states_by_side.items():
        result = state["validation_result"]
        st.session_state[f"compare_{side}_state"] = state
        st.session_state[f"compare_{side}_chat"].append(
            {"role": "assistant", "content": result_to_assistant_text(result)}
        )
        st.session_state[f"compare_{side}_llm_messages"].append(verifier_result_as_message(result))


def render_flow_state(state) -> None:
    if not state:
        st.info("Enter a program name and run the workflow.")
        return

    render_pipeline_nodes(state)
    render_stage_metrics(state)

    result = state.get("validation_result")
    if result is None:
        st.warning("No validation result returned.")
        return

    if result.status == "resolved" and result.identity:
        st.success("Workflow initialized")
        st.metric("Program", result.identity.program_name)
        st.metric("Domain", result.identity.domain)
        st.metric("Confidence", f"{result.confidence:.2f}")
        render_node_results(state)
        return

    if result.status == "rejected":
        st.error("No such loyalty program found")
    else:
        st.warning("Needs clarification before retrieval")
    st.json(result.model_dump())


def render_pipeline_nodes(state) -> None:
    st.subheader("Node Status")
    statuses = build_node_statuses(state)
    for row_start in range(0, len(INSPECTOR_NODES), 4):
        cols = st.columns(4)
        for column, node in zip(cols, INSPECTOR_NODES[row_start : row_start + 4]):
            status = statuses[node]
            with column:
                with st.container(border=True):
                    st.markdown(f"{status_icon(status['state'])} **{NODE_LABELS[node]}**")
                    st.markdown(f"Status: `{status['state']}`")
                    st.caption(status["message"])


def build_node_statuses(state) -> dict[str, dict[str, str]]:
    result = state.get("validation_result")
    errors = {error.stage: error.message for error in state.get("errors", [])}

    statuses = {
        "input_validator": {"state": "Pending", "message": "Waiting for user input."},
        "query_generator": {"state": "Pending", "message": "Runs after validation resolves."},
        "retrieval": {"state": "Pending", "message": "Runs after query generation succeeds."},
        "firecrawl_scraper": {"state": "Pending", "message": "Runs after URL retrieval succeeds."},
        "raw_store": {"state": "Pending", "message": "Runs after Firecrawl returns content."},
        "chunker": {"state": "Pending", "message": "Runs after raw documents are stored."},
        "gemini_extractor": {"state": "Pending", "message": "Runs after semantic chunks are ready."},
        "normalizer": {"state": "Pending", "message": "Runs after extraction returns packets."},
    }

    if result:
        if result.status == "resolved":
            statuses["input_validator"] = {"state": "Complete", "message": "Program identity resolved."}
        elif result.status == "rejected":
            statuses["input_validator"] = {"state": "Error", "message": result.reason or "Input rejected."}
        else:
            statuses["input_validator"] = {"state": "Waiting", "message": "Needs clarification from the user."}

    if "query_generator" in errors:
        statuses["query_generator"] = {"state": "Error", "message": errors["query_generator"]}
    elif state.get("query_generation_result"):
        query_count = len(state["query_generation_result"].queries)
        statuses["query_generator"] = {"state": "Complete", "message": f"Generated {query_count} Tavily queries."}
    elif result and result.status != "resolved":
        statuses["query_generator"] = {"state": "Locked", "message": "Input validator has not resolved yet."}

    if "retrieval" in errors:
        statuses["retrieval"] = {"state": "Error", "message": errors["retrieval"]}
    elif state.get("retrieval_result"):
        retrieval = state["retrieval_result"]
        statuses["retrieval"] = {
            "state": "Complete",
            "message": f"{retrieval.unique_result_count} unique URLs from {retrieval.raw_result_count} results.",
        }
    elif not state.get("query_generation_result"):
        statuses["retrieval"] = {"state": "Locked", "message": "Query generator has not completed yet."}

    if "firecrawl_scraper" in errors:
        statuses["firecrawl_scraper"] = {"state": "Error", "message": errors["firecrawl_scraper"]}
    elif state.get("firecrawl_result"):
        firecrawl = state["firecrawl_result"]
        state_label = "Complete" if firecrawl.successful_scrapes > 0 else "Error"
        statuses["firecrawl_scraper"] = {
            "state": state_label,
            "message": f"{firecrawl.successful_scrapes} scraped, {firecrawl.failed_scrapes} failed.",
        }
    elif not state.get("retrieval_result"):
        statuses["firecrawl_scraper"] = {"state": "Locked", "message": "Tavily retrieval has not completed yet."}

    if "ingest" in errors:
        ingest_message = errors["ingest"]
    else:
        ingest_message = ""

    raw_documents = state.get("raw_documents", [])
    if raw_documents:
        statuses["raw_store"] = {"state": "Complete", "message": f"Stored {len(raw_documents)} usable raw documents."}
    elif state.get("firecrawl_result") and state["firecrawl_result"].successful_scrapes > 0:
        statuses["raw_store"] = {"state": "Waiting", "message": ingest_message or "No page over 100 words was stored."}
    elif not state.get("firecrawl_result"):
        statuses["raw_store"] = {"state": "Locked", "message": "Firecrawl has not completed yet."}

    chunks = state.get("semantic_chunks", [])
    extraction_chunks = state.get("extraction_chunks", [])
    skipped_chunks = state.get("skipped_chunks", [])
    if chunks:
        statuses["chunker"] = {
            "state": "Complete",
            "message": f"Created {len(chunks)} chunks; selected {len(extraction_chunks)} for extraction.",
        }
    elif raw_documents:
        statuses["chunker"] = {"state": "Waiting", "message": "No chunk met the minimum section size."}
    elif not raw_documents:
        statuses["chunker"] = {"state": "Locked", "message": "Raw documents are not ready."}

    extracted_packets = state.get("extracted_packets", [])
    if extracted_packets:
        statuses["gemini_extractor"] = {"state": "Complete", "message": f"Extracted {len(extracted_packets)} object packets."}
    elif extraction_chunks:
        statuses["gemini_extractor"] = {
            "state": "Waiting",
            "message": ingest_message or f"No packets from {len(extraction_chunks)} selected chunks.",
        }
    elif chunks:
        statuses["gemini_extractor"] = {
            "state": "Waiting",
            "message": ingest_message or f"Skipped {len(skipped_chunks)} low-signal chunks before Gemini.",
        }
    elif not chunks:
        statuses["gemini_extractor"] = {"state": "Locked", "message": "Semantic chunks are not ready."}

    normalized_packets = state.get("normalized_packets", [])
    if normalized_packets:
        statuses["normalizer"] = {"state": "Complete", "message": f"Normalized {len(normalized_packets)} packets."}
    elif extracted_packets:
        statuses["normalizer"] = {"state": "Waiting", "message": "No normalized packets were produced."}
    elif not extracted_packets:
        statuses["normalizer"] = {"state": "Locked", "message": "Gemini extraction has not produced packets."}

    return statuses


def status_icon(state: str) -> str:
    return {
        "Complete": "[OK]",
        "Running": "[RUN]",
        "Waiting": "[WAIT]",
        "Pending": "[PENDING]",
        "Locked": "[LOCKED]",
        "Error": "[ERROR]",
    }.get(state, "[PENDING]")


def render_stage_metrics(state) -> None:
    st.subheader("Stage Outputs")
    metrics = (
        ("Queries", len(state.get("search_queries", []))),
        ("Unique URLs", len(state.get("retrieved_urls", []))),
        ("Raw Docs", len(state.get("raw_documents", []))),
        ("Chunks", len(state.get("semantic_chunks", []))),
        ("Selected", len(state.get("extraction_chunks", []))),
        ("Packets", len(state.get("normalized_packets", []))),
    )
    cols = st.columns(len(metrics))
    for column, (label, value) in zip(cols, metrics):
        column.metric(label, value)


def render_node_results(state) -> None:
    result = state.get("validation_result")
    with st.expander("Input Validator Result", expanded=True):
        st.json(result.model_dump() if result else None)

    query_result = state.get("query_generation_result")
    with st.expander("Query Generator Result", expanded=bool(query_result)):
        if query_result:
            st.caption(query_result.query_strategy_summary)
            st.json(
                {
                    "detected_category": query_result.detected_category,
                    "resolved_corporate_parent": query_result.resolved_corporate_parent,
                    "geography": query_result.geography,
                    "priority_fields": query_result.priority_fields,
                    "estimated_web_coverage": query_result.estimated_web_coverage,
                    "field_query_map": query_result.field_query_map,
                    "queries": [query.model_dump() for query in query_result.queries],
                }
            )
        else:
            st.info("No query-generation result yet.")

    retrieval_result = state.get("retrieval_result")
    with st.expander("Tavily Retrieval Result", expanded=bool(retrieval_result)):
        if retrieval_result:
            st.caption(
                f"{retrieval_result.unique_result_count} unique URLs from "
                f"{retrieval_result.raw_result_count} Tavily results"
            )
            st.json([url.model_dump() for url in retrieval_result.urls])
        else:
            st.info("No retrieval result yet.")

    firecrawl_result = state.get("firecrawl_result")
    with st.expander("Firecrawl Scraper Result", expanded=bool(firecrawl_result)):
        if firecrawl_result:
            st.caption(
                f"{firecrawl_result.successful_scrapes} successful scrapes, "
                f"{firecrawl_result.failed_scrapes} failed scrapes"
            )
            st.json(
                [
                    {
                        "url": block.url,
                        "content_chars": len(block.content or ""),
                        "content_preview": preview_content(block.content),
                        "scrape_status": block.scrape_status,
                        "error": block.error,
                    }
                    for block in firecrawl_result.blocks
                ]
            )
        else:
            st.info("No Firecrawl scrape result yet.")

    raw_documents = state.get("raw_documents", [])
    with st.expander("Raw Document Store Result", expanded=bool(raw_documents)):
        if raw_documents:
            st.caption(f"{len(raw_documents)} raw documents persisted to SQLite")
            st.json(
                [
                    {
                        "url": document.url,
                        "url_hash": document.url_hash,
                        "word_count": document.word_count,
                        "query_id": document.query_id,
                        "entity_name": document.entity_name,
                        "domain": document.domain,
                        "retrieved_at": document.retrieved_at,
                        "source_authority": document.source_authority,
                        "metadata": document.metadata,
                        "content_preview": preview_content(document.content),
                    }
                    for document in raw_documents
                ]
            )
        else:
            st.info("No raw documents stored yet. Pages under 100 words are skipped.")

    semantic_chunks = state.get("semantic_chunks", [])
    extraction_chunk_ids = {chunk.chunk_id for chunk in state.get("extraction_chunks", [])}
    with st.expander("Semantic Chunker Result", expanded=bool(semantic_chunks)):
        if semantic_chunks:
            st.caption(
                f"{len(semantic_chunks)} chunks created; "
                f"{len(extraction_chunk_ids)} selected for Gemini extraction"
            )
            st.json(
                [
                    {
                        "chunk_id": chunk.chunk_id,
                        "selected_for_extraction": chunk.chunk_id in extraction_chunk_ids,
                        "source_url": chunk.source_url,
                        "target_field_count": len(chunk.target_fields),
                        "target_fields_preview": chunk.target_fields[:20],
                        "word_count": len(chunk.chunk_text.split()),
                        "chunk_preview": preview_content(chunk.chunk_text),
                    }
                    for chunk in semantic_chunks
                ]
            )
        else:
            st.info("No semantic chunks yet.")

    extracted_packets = state.get("extracted_packets", [])
    with st.expander("Gemini Extraction Result", expanded=bool(extracted_packets)):
        if extracted_packets:
            st.caption(f"{len(extracted_packets)} raw extracted packets before normalization")
            st.json([packet.model_dump() for packet in extracted_packets])
        else:
            st.info("No extracted packets yet. If chunks exist, Gemini found no explicit schema facts or extraction failed safely.")

    normalized_packets = state.get("normalized_packets", [])
    with st.expander("Normalized Packets Result", expanded=bool(normalized_packets)):
        if normalized_packets:
            st.caption(f"{len(normalized_packets)} normalized packets with identity hashes")
            st.json([packet.model_dump() for packet in normalized_packets])
        else:
            st.info("No normalized packets yet.")

    field_report = state.get("field_report")
    with st.expander("Field Report (values + sources)", expanded=bool(field_report)):
        if field_report:
            st.caption(
                f"{field_report.extracted_count} extracted, {field_report.ambiguous_count} ambiguous, "
                f"{field_report.not_found_count} not found of {len(field_report.entries)} fields"
            )
            st.dataframe(
                [
                    {
                        "field": entry.field_path,
                        "status": entry.status,
                        "value": "" if entry.value is None else str(entry.value),
                        "sources": ", ".join(entry.source_urls),
                        "snippet": entry.source_snippet or "",
                        "confidence": entry.confidence,
                    }
                    for entry in field_report.entries
                ],
                use_container_width=True,
            )
        else:
            st.info("No field report yet.")

    adjudicated = state.get("adjudicated", [])
    with st.expander("Conflict Adjudication Result", expanded=bool(adjudicated)):
        if adjudicated:
            st.caption(f"{len(adjudicated)} adjudication entries (auto, debate, or flagged)")
            st.dataframe(
                [
                    {
                        "field": entry.get("field_name"),
                        "resolution": entry.get("resolution"),
                        "winner": entry.get("winner"),
                        "value": entry.get("value"),
                        "source": entry.get("source_url"),
                        "confidence": entry.get("confidence"),
                        "deciding factor": entry.get("deciding_factor"),
                        "reasoning": entry.get("reasoning"),
                    }
                    for entry in adjudicated
                ],
                use_container_width=True,
            )
            debates = [entry["debate"] for entry in adjudicated if entry.get("debate")]
            if debates:
                st.caption("Debate transcripts")
                st.json(debates)
        else:
            st.info("No conflicting claims between sources.")

    with st.expander("Focused Extraction Schema", expanded=False):
        fields = all_default_field_paths()
        st.caption(f"{len(fields)} required fields from the selected report schema")
        st.json(fields)


# ── Pipeline Inspector helpers ───────────────────────────────────────────────

_INSPECTOR_CONFIG_DEFAULTS = {
    "MAX_FIRECRAWL_URLS": 12,
    "MAX_EXTRACTION_CHUNKS": 30,
    "EXTRACTION_BATCH_WORDS": 4000,
    "MIN_EXTRACTION_CHUNK_SCORE": 2,
}

_INSPECTOR_STAGES = [
    "input_validator",
    "query_generator",
    "retrieval",
    "firecrawl_scraper",
    "ingest",
    "adjudication",
    "narration",
]

_INSPECTOR_STAGE_LABELS = {
    "input_validator": "1. Input Validator",
    "query_generator": "2. Query Generator",
    "retrieval": "3. Tavily Retrieval",
    "firecrawl_scraper": "4. Firecrawl Scraper",
    "ingest": "5. Ingest  (Store → Chunk → Extract → Normalize)",
    "adjudication": "6. Conflict Adjudication",
    "narration": "7. Narration  (Program Brief)",
}


def _inspector_init() -> None:
    if "inspector_state" not in st.session_state:
        st.session_state.inspector_state = None
    if "inspector_snaps" not in st.session_state:
        st.session_state.inspector_snaps = {}
    if "inspector_edited_queries" not in st.session_state:
        st.session_state.inspector_edited_queries = None
    if "inspector_selected_urls" not in st.session_state:
        st.session_state.inspector_selected_urls = None
    if "inspector_config" not in st.session_state:
        st.session_state.inspector_config = dict(_INSPECTOR_CONFIG_DEFAULTS)
    if "_inspector_input" not in st.session_state:
        st.session_state["_inspector_input"] = ""


def _safe_json(value):
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, dict):
        return {k: _safe_json(v) for k, v in value.items()}
    return value


def _pick(state, *keys):
    return {k: _safe_json(state.get(k)) for k in keys if state.get(k) is not None}


def _apply_inspector_config() -> None:
    for key, value in st.session_state.inspector_config.items():
        os.environ[key] = str(value)


def _snap_done(node: str) -> bool:
    return node in st.session_state.get("inspector_snaps", {})


def _can_run(node: str) -> bool:
    state = st.session_state.get("inspector_state") or {}
    if node == "input_validator":
        return bool(st.session_state.get("_inspector_input", "").strip())
    if node == "query_generator":
        r = state.get("validation_result")
        return bool(r and r.status == "resolved")
    if node == "retrieval":
        return bool(state.get("query_generation_result"))
    if node == "firecrawl_scraper":
        return bool(state.get("retrieval_result"))
    if node == "ingest":
        fc = state.get("firecrawl_result")
        return bool(fc and fc.successful_scrapes > 0)
    if node == "adjudication":
        return bool(state.get("normalized_packets"))
    if node == "narration":
        fr = state.get("field_report")
        return bool(
            fr and any(
                e.value is not None and e.status in ("extracted", "flagged", "ambiguous")
                for e in fr.entries
            )
        )
    return False


def _run_inspector_stage(node: str) -> None:
    from graph import (
        adjudication_node,
        firecrawl_node,
        ingest_node,
        input_validator_node,
        query_generator_node,
        retrieval_node,
    )
    from schemas import SearchQuery, build_initial_state, new_id

    _apply_inspector_config()
    state = st.session_state.inspector_state or {}

    if node == "input_validator":
        user_input = st.session_state.get("_inspector_input", "").strip()
        fresh = build_initial_state(user_input)
        fresh["validation_messages"] = [{"role": "user", "content": user_input}]
        inp_snap: dict = {"user_input": user_input}
        delta = input_validator_node(fresh)
        new_state = {**fresh, **delta}
        out_snap: dict = _pick(new_state, "validation_result", "program_identity", "errors")

    elif node == "query_generator":
        inp_snap = _pick(state, "program_identity")
        delta = query_generator_node(state)
        new_state = {**state, **delta}
        out_snap = _pick(new_state, "query_generation_result", "search_queries", "errors")
        if new_state.get("query_generation_result"):
            st.session_state.inspector_edited_queries = list(new_state["query_generation_result"].queries)

    elif node == "retrieval":
        edited = st.session_state.get("inspector_edited_queries")
        run_state = {**state, "search_queries": edited} if edited is not None else state
        inp_snap = {
            "query_count": len(run_state.get("search_queries", [])),
            "queries": [{"query": q.query, "source_type": q.source_type} for q in run_state.get("search_queries", [])],
        }
        delta = retrieval_node(run_state)
        new_state = {**run_state, **delta}
        if new_state.get("retrieved_urls"):
            st.session_state.inspector_selected_urls = [u.canonical_url for u in new_state["retrieved_urls"]]
        out_snap = _pick(new_state, "retrieval_result", "retrieved_urls", "errors")

    elif node == "firecrawl_scraper":
        sel = st.session_state.get("inspector_selected_urls")
        all_urls = state.get("retrieved_urls", [])
        urls = [u for u in all_urls if u.canonical_url in set(sel)] if sel is not None else all_urls
        run_state = {**state, "retrieved_urls": urls}
        inp_snap = {
            "url_count": len(urls),
            "urls": [u.url for u in urls],
            "MAX_FIRECRAWL_URLS": st.session_state.inspector_config.get("MAX_FIRECRAWL_URLS"),
        }
        delta = firecrawl_node(run_state)
        new_state = {**run_state, **delta}
        out_snap = _pick(new_state, "firecrawl_result", "errors")

    elif node == "ingest":
        cfg = st.session_state.inspector_config
        inp_snap = {
            "scraped_blocks": len(state.get("scraped_blocks", [])),
            "program_name": state.get("program_name"),
            "MAX_EXTRACTION_CHUNKS": cfg.get("MAX_EXTRACTION_CHUNKS"),
            "EXTRACTION_BATCH_WORDS": cfg.get("EXTRACTION_BATCH_WORDS"),
            "MIN_EXTRACTION_CHUNK_SCORE": cfg.get("MIN_EXTRACTION_CHUNK_SCORE"),
        }
        delta = ingest_node(state)
        new_state = {**state, **delta}
        out_snap = _pick(
            new_state,
            "raw_documents", "semantic_chunks", "extraction_chunks",
            "extracted_packets", "normalized_packets", "field_report", "errors",
        )

    elif node == "adjudication":
        inp_snap = {
            "normalized_packets_count": len(state.get("normalized_packets", [])),
            "conflicts_count": len(state.get("conflicts", [])),
        }
        delta = adjudication_node(state)
        new_state = {**state, **delta}
        out_snap = _pick(new_state, "adjudicated", "conflicts", "field_report", "errors")

    elif node == "narration":
        from graph import narrator_node as _narrate

        fr = state.get("field_report")
        usable_count = (
            sum(1 for e in fr.entries if e.value is not None and e.status in ("extracted", "flagged", "ambiguous"))
            if fr else 0
        )
        inp_snap = {
            "program_name": state.get("program_name"),
            "field_report_entries": len(fr.entries) if fr else 0,
            "usable_extracted_fields": usable_count,
        }
        delta = _narrate(state)
        new_state = {**state, **delta}
        brief = new_state.get("final_brief")
        out_snap = {
            "word_count": brief.word_count if brief else 0,
            "brief_preview": (brief.brief_text[:600] + "...") if brief and len(brief.brief_text) > 600 else (brief.brief_text if brief else None),
            "errors": _safe_json(new_state.get("errors", [])),
        }

    else:
        return

    st.session_state.inspector_state = new_state
    st.session_state.inspector_snaps[node] = {"input": inp_snap, "output": out_snap}


def _inspector_stage_header(node: str) -> bool:
    done = _snap_done(node)
    runnable = _can_run(node)
    state_text = "[DONE]" if done else ("[READY]" if runnable else "[LOCKED]")
    label = _INSPECTOR_STAGE_LABELS[node]
    c1, c2 = st.columns([6, 1])
    with c1:
        st.markdown(f"#### {state_text} {label}")
    with c2:
        clicked = st.button(
            "Run",
            key=f"insp_run_{node}",
            disabled=not runnable,
            type="primary" if (runnable and not done) else "secondary",
        )
    return clicked


def _inspector_show_errors(snap: dict) -> None:
    errors = (snap.get("output") or {}).get("errors") or []
    for err in errors:
        if isinstance(err, dict) and err.get("message"):
            st.error(f"**{err.get('stage', 'error')}**: {err['message']}")


def _inspector_io_columns(snap: dict, output_renderer=None) -> None:
    c_in, c_out = st.columns(2)
    with c_in:
        with st.expander("Input", expanded=False):
            st.json(snap["input"])
    with c_out:
        with st.expander("Output", expanded=True):
            if output_renderer:
                output_renderer()
            else:
                st.json(snap["output"])


def render_inspector_tab() -> None:
    _inspector_init()

    # ── Config panel ─────────────────────────────────────────────────────────
    with st.expander("Pipeline Configuration", expanded=False):
        cfg = st.session_state.inspector_config
        c1, c2, c3, c4 = st.columns(4)
        cfg["MAX_FIRECRAWL_URLS"] = c1.number_input(
            "Max Firecrawl URLs", min_value=1, max_value=25,
            value=int(cfg["MAX_FIRECRAWL_URLS"]),
            help="Scraping URL budget cap",
        )
        cfg["MAX_EXTRACTION_CHUNKS"] = c2.number_input(
            "Max Extract Chunks", min_value=5, max_value=100,
            value=int(cfg["MAX_EXTRACTION_CHUNKS"]),
            help="Chunk count sent to Gemini",
        )
        cfg["EXTRACTION_BATCH_WORDS"] = c3.number_input(
            "Batch Words", min_value=500, max_value=10000, step=500,
            value=int(cfg["EXTRACTION_BATCH_WORDS"]),
            help="Target words per Gemini extraction call",
        )
        cfg["MIN_EXTRACTION_CHUNK_SCORE"] = c4.number_input(
            "Min Chunk Score", min_value=0, max_value=10,
            value=int(cfg["MIN_EXTRACTION_CHUNK_SCORE"]),
            help="Keyword score threshold for chunk selection",
        )

    col_run_all, col_reset, _ = st.columns([2, 2, 6])
    with col_run_all:
        if st.button("Run All Remaining Stages", type="primary"):
            for stage in _INSPECTOR_STAGES:
                if not _snap_done(stage) and _can_run(stage):
                    _run_inspector_stage(stage)
            st.rerun()
    with col_reset:
        if st.button("Reset Inspector"):
            for key in ["inspector_state", "inspector_snaps", "inspector_edited_queries",
                        "inspector_selected_urls", "_inspector_input"]:
                st.session_state.pop(key, None)
            st.rerun()

    st.divider()

    # ── Stage 1: Input Validator ─────────────────────────────────────────────
    with st.container(border=True):
        st.text_input("Program name", key="_inspector_input", placeholder="e.g. Marriott Bonvoy")
        clicked = _inspector_stage_header("input_validator")
        if clicked:
            with st.spinner("Running Input Validator..."):
                _run_inspector_stage("input_validator")
            st.rerun()
        snap = st.session_state.inspector_snaps.get("input_validator")
        if snap:
            _inspector_show_errors(snap)

            def _render_validator_out():
                vr = (st.session_state.inspector_state or {}).get("validation_result")
                if vr and vr.status == "resolved":
                    identity = vr.identity
                    st.success(
                        f"**{identity.program_name}** — {identity.domain} — "
                        f"confidence {vr.confidence:.2f}"
                    )
                elif vr and vr.status == "rejected":
                    st.error(vr.reason or "Rejected")
                elif vr:
                    st.warning("Needs clarification")
                st.json(snap["output"])

            _inspector_io_columns(snap, _render_validator_out)

    # ── Stage 2: Query Generator ─────────────────────────────────────────────
    with st.container(border=True):
        clicked = _inspector_stage_header("query_generator")
        if clicked:
            with st.spinner("Running Query Generator..."):
                _run_inspector_stage("query_generator")
            st.rerun()
        snap = st.session_state.inspector_snaps.get("query_generator")
        if snap:
            _inspector_show_errors(snap)

            def _render_qgen_out():
                qr = (st.session_state.inspector_state or {}).get("query_generation_result")
                if qr:
                    st.caption(qr.query_strategy_summary)
                    st.caption(f"Category: {qr.detected_category} | {len(qr.queries)} queries")
                st.json(snap["output"])

            _inspector_io_columns(snap, _render_qgen_out)

            # ── Query editor ──────────────────────────────────────────────
            edited_queries = st.session_state.get("inspector_edited_queries") or []
            if edited_queries:
                st.markdown("**Edit queries before Retrieval runs:**")
                import pandas as pd

                df = pd.DataFrame([
                    {
                        "query": q.query,
                        "source_type": q.source_type,
                        "intent": q.intent or "",
                        "target_fields": ", ".join(q.target_fields),
                    }
                    for q in edited_queries
                ])
                edited_df = st.data_editor(
                    df,
                    use_container_width=True,
                    num_rows="dynamic",
                    key="inspector_query_editor",
                    column_config={
                        "query": st.column_config.TextColumn("Query", width="large"),
                        "source_type": st.column_config.TextColumn("Source Type"),
                        "intent": st.column_config.TextColumn("Intent"),
                        "target_fields": st.column_config.TextColumn("Target Fields (comma-sep)"),
                    },
                )
                if st.button("Apply query edits", key="apply_query_edits"):
                    from schemas import SearchQuery, new_id

                    new_queries = []
                    for _, row in edited_df.iterrows():
                        q_text = str(row.get("query", "")).strip()
                        if not q_text:
                            continue
                        new_queries.append(SearchQuery(
                            query_id=new_id("query"),
                            query=q_text,
                            source_type=str(row.get("source_type", "official")).strip() or "official",
                            intent=str(row.get("intent", "")).strip() or None,
                            target_fields=[
                                t.strip()
                                for t in str(row.get("target_fields", "")).split(",")
                                if t.strip()
                            ],
                        ))
                    st.session_state.inspector_edited_queries = new_queries
                    st.success(f"Saved {len(new_queries)} queries — will be used when Retrieval runs.")

    # ── Stage 3: Retrieval ───────────────────────────────────────────────────
    with st.container(border=True):
        clicked = _inspector_stage_header("retrieval")
        if clicked:
            with st.spinner("Running Tavily Retrieval..."):
                _run_inspector_stage("retrieval")
            st.rerun()
        snap = st.session_state.inspector_snaps.get("retrieval")
        if snap:
            _inspector_show_errors(snap)

            def _render_retrieval_out():
                rr = (st.session_state.inspector_state or {}).get("retrieval_result")
                if rr:
                    st.caption(f"{rr.unique_result_count} unique URLs from {rr.raw_result_count} results")
                st.json(snap["output"])

            _inspector_io_columns(snap, _render_retrieval_out)

            # ── URL selector ──────────────────────────────────────────────
            all_urls = (st.session_state.inspector_state or {}).get("retrieved_urls", [])
            if all_urls:
                st.markdown("**Select URLs to pass to Firecrawl:**")
                url_options = [u.canonical_url for u in all_urls]
                url_labels = {u.canonical_url: f"[{u.source_type}] {u.url[:90]}" for u in all_urls}
                current_sel = st.session_state.get("inspector_selected_urls") or url_options
                selected = st.multiselect(
                    f"{len(all_urls)} retrieved URLs — uncheck any you want to skip",
                    options=url_options,
                    default=[u for u in current_sel if u in url_options],
                    format_func=lambda x: url_labels.get(x, x),
                    key="inspector_url_multiselect",
                )
                st.session_state.inspector_selected_urls = selected
                st.caption(f"{len(selected)} of {len(all_urls)} URLs selected")

    # ── Stage 4: Firecrawl Scraper ───────────────────────────────────────────
    with st.container(border=True):
        clicked = _inspector_stage_header("firecrawl_scraper")
        if clicked:
            with st.spinner("Running Firecrawl Scraper..."):
                _run_inspector_stage("firecrawl_scraper")
            st.rerun()
        snap = st.session_state.inspector_snaps.get("firecrawl_scraper")
        if snap:
            _inspector_show_errors(snap)

            def _render_firecrawl_out():
                fc = (st.session_state.inspector_state or {}).get("firecrawl_result")
                if fc:
                    st.caption(f"{fc.successful_scrapes} scraped, {fc.failed_scrapes} failed")
                    st.dataframe(
                        [
                            {
                                "url": b.url,
                                "chars": len(b.content or ""),
                                "status": b.scrape_status,
                                "error": b.error or "",
                            }
                            for b in fc.blocks
                        ],
                        use_container_width=True,
                    )

            _inspector_io_columns(snap, _render_firecrawl_out)

    # ── Stage 5: Ingest ──────────────────────────────────────────────────────
    with st.container(border=True):
        clicked = _inspector_stage_header("ingest")
        if clicked:
            with st.spinner("Running Ingest (this may take a while)..."):
                _run_inspector_stage("ingest")
            st.rerun()
        snap = st.session_state.inspector_snaps.get("ingest")
        if snap:
            _inspector_show_errors(snap)
            c_in, c_out = st.columns(2)
            with c_in:
                with st.expander("Input", expanded=False):
                    st.json(snap["input"])
            with c_out:
                with st.expander("Output summary", expanded=True):
                    s = st.session_state.inspector_state or {}
                    raw_docs = s.get("raw_documents", [])
                    chunks = s.get("semantic_chunks", [])
                    ext_chunks = s.get("extraction_chunks", [])
                    packets = s.get("normalized_packets", [])
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Raw Docs", len(raw_docs))
                    m2.metric("Chunks", len(chunks))
                    m3.metric("Selected", len(ext_chunks))
                    m4.metric("Packets", len(packets))

                    fr = s.get("field_report")
                    if fr:
                        st.caption(
                            f"Field report: {fr.extracted_count} extracted, "
                            f"{fr.ambiguous_count} ambiguous, {fr.not_found_count} not_found"
                        )
                        st.dataframe(
                            [
                                {
                                    "field": e.field_path,
                                    "status": e.status,
                                    "value": str(e.value) if e.value is not None else "",
                                    "sources": len(e.source_urls),
                                    "snippet": (e.source_snippet or "")[:80],
                                    "confidence": e.confidence,
                                }
                                for e in fr.entries
                            ],
                            use_container_width=True,
                        )

            with st.expander("Semantic Chunks detail", expanded=False):
                s = st.session_state.inspector_state or {}
                ext_ids = {c.chunk_id for c in s.get("extraction_chunks", [])}
                st.json([
                    {
                        "chunk_id": c.chunk_id,
                        "selected": c.chunk_id in ext_ids,
                        "words": len(c.chunk_text.split()),
                        "source_url": c.source_url,
                        "target_fields": c.target_fields[:8],
                        "preview": c.chunk_text[:300],
                    }
                    for c in s.get("semantic_chunks", [])
                ])

            with st.expander("Extracted Packets (raw)", expanded=False):
                st.json(_safe_json((st.session_state.inspector_state or {}).get("extracted_packets", [])))

            with st.expander("Normalized Packets", expanded=False):
                st.json(_safe_json((st.session_state.inspector_state or {}).get("normalized_packets", [])))

    # ── Stage 6: Adjudication ────────────────────────────────────────────────
    with st.container(border=True):
        clicked = _inspector_stage_header("adjudication")
        if clicked:
            with st.spinner("Running Conflict Adjudication..."):
                _run_inspector_stage("adjudication")
            st.rerun()
        snap = st.session_state.inspector_snaps.get("adjudication")
        if snap:
            _inspector_show_errors(snap)
            c_in, c_out = st.columns(2)
            with c_in:
                with st.expander("Input", expanded=False):
                    st.json(snap["input"])
            with c_out:
                with st.expander("Output", expanded=True):
                    s = st.session_state.inspector_state or {}
                    adj = s.get("adjudicated", [])
                    if adj:
                        st.caption(f"{len(adj)} adjudication entries")
                        st.dataframe(
                            [
                                {
                                    "field": a.get("field_name"),
                                    "resolution": a.get("resolution"),
                                    "winner": a.get("winner"),
                                    "value": a.get("value"),
                                    "confidence": a.get("confidence"),
                                    "deciding_factor": a.get("deciding_factor"),
                                    "reasoning": a.get("reasoning"),
                                }
                                for a in adj
                            ],
                            use_container_width=True,
                        )
                        debates = [a["debate"] for a in adj if a.get("debate")]
                        if debates:
                            with st.expander("Debate Transcripts", expanded=False):
                                st.json(debates)
                    else:
                        st.info("No conflicts detected between sources.")

            fr = (st.session_state.inspector_state or {}).get("field_report")
            if fr:
                with st.expander("Final Field Report (post-adjudication)", expanded=False):
                    st.caption(
                        f"{fr.extracted_count} extracted, "
                        f"{fr.ambiguous_count} ambiguous, {fr.not_found_count} not_found"
                    )
                    st.dataframe(
                        [
                            {
                                "field": e.field_path,
                                "status": e.status,
                                "value": str(e.value) if e.value is not None else "",
                                "sources": len(e.source_urls),
                                "confidence": e.confidence,
                                "corroboration": e.corroboration_count,
                            }
                            for e in fr.entries
                        ],
                        use_container_width=True,
                    )


    # ── Stage 7: Narration ───────────────────────────────────────────────────
    with st.container(border=True):
        clicked = _inspector_stage_header("narration")
        if clicked:
            with st.spinner("Generating program brief..."):
                _run_inspector_stage("narration")
            st.rerun()
        snap = st.session_state.inspector_snaps.get("narration")
        if snap:
            _inspector_show_errors(snap)
            brief = (st.session_state.inspector_state or {}).get("final_brief")
            c_in, c_out = st.columns(2)
            with c_in:
                with st.expander("Input", expanded=False):
                    st.json(snap["input"])
            with c_out:
                with st.expander("Output summary", expanded=True):
                    if brief:
                        st.metric("Word count", brief.word_count)
                        st.caption(f"Brief ID: {brief.brief_id}")
                    else:
                        st.info("No brief generated.")
            if brief:
                with st.expander("Full Program Brief", expanded=True):
                    st.markdown(brief.brief_text)


def preview_content(content: str | None, limit: int = 900) -> str | None:
    if not content:
        return None
    return content[:limit] + ("..." if len(content) > limit else "")


def render_compare_card(side: str, title: str) -> None:
    with st.container(border=True):
        st.subheader(title)
        for message in st.session_state[f"compare_{side}_chat"]:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        program_input = st.text_input(
            "Program name or clarification",
            key=f"compare_{side}_input",
            placeholder="Example: Marriott Bonvoy",
        )
        if st.button("Send to verifier", key=f"compare_{side}_send"):
            run_compare_side(side, program_input)
            st.rerun()

        st.button("Reset", key=f"compare_{side}_reset", on_click=reset_compare_side, args=(side,))

        render_flow_state(st.session_state.get(f"compare_{side}_state"))


if "validator_chat" not in st.session_state:
    reset_validator_chat()
if (
    "compare_a_state" not in st.session_state
    or "compare_a_chat" not in st.session_state
    or "compare_a_llm_messages" not in st.session_state
):
    reset_compare_side("a")
if (
    "compare_b_state" not in st.session_state
    or "compare_b_chat" not in st.session_state
    or "compare_b_llm_messages" not in st.session_state
):
    reset_compare_side("b")

tabs = st.tabs(["Input verifier", "Compare", "Converse", "Pipeline Inspector"])

with tabs[0]:
    left, right = st.columns([0.58, 0.42], gap="large")

    with left:
        st.subheader("INPUT verifier")
        for message in st.session_state.validator_chat:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        prompt = st.chat_input("Enter a brand, program, alias, or clarification")
        if prompt:
            st.session_state.validator_chat.append({"role": "user", "content": prompt})
            st.session_state.validator_llm_messages.append({"role": "user", "content": prompt})

            state = run_workflow_with_live_status(st.session_state.validator_llm_messages)
            result = state["validation_result"]
            assistant_text = result_to_assistant_text(result)

            st.session_state.validation_result = result
            st.session_state.last_graph_state = state
            st.session_state.validator_chat.append({"role": "assistant", "content": assistant_text})
            st.session_state.validator_llm_messages.append(verifier_result_as_message(result))

            st.rerun()

        if st.button("Reset verifier chat"):
            reset_validator_chat()
            st.rerun()

    with right:
        st.subheader("Workflow Inspector")
        render_flow_state(st.session_state.last_graph_state)

with tabs[1]:
    st.subheader("Compare two programs")
    st.caption("Compare triggers the existing single-program workflow twice in parallel: one run for Program A and one run for Program B.")

    a_card, b_card = st.columns(2, gap="large")
    with a_card:
        render_compare_card("a", "Program A")
    with b_card:
        render_compare_card("b", "Program B")

    if st.button("Run both verifier workflows in parallel", type="primary"):
        run_compare_sides_parallel(st.session_state.compare_a_input, st.session_state.compare_b_input)
        st.rerun()

    a_state = st.session_state.get("compare_a_state")
    b_state = st.session_state.get("compare_b_state")
    a_ready = bool(
        a_state
        and a_state.get("validation_result")
        and a_state["validation_result"].status == "resolved"
    )
    b_ready = bool(
        b_state
        and b_state.get("validation_result")
        and b_state["validation_result"].status == "resolved"
    )

    if a_ready and b_ready:
        st.success("Both program states are ready. Final comparison display can be built from these two completed states.")
    else:
        st.info("Run and resolve both Program A and Program B before generating the final comparison.")

with tabs[2]:
    if "converse_chat" not in st.session_state:
        st.session_state.converse_chat = []

    # Prefer the inspector state so the brief from stage 7 is immediately usable.
    _active_state = st.session_state.get("inspector_state") or st.session_state.get("last_graph_state")
    _brief = _active_state.get("final_brief") if _active_state else None
    _field_report = _active_state.get("field_report") if _active_state else None

    if _brief is None:
        st.info(
            "Run the full pipeline through **Stage 7 — Narration** in the Pipeline Inspector tab, "
            "then return here to ask questions about the program."
        )
    else:
        _prog_name = (_active_state or {}).get("program_name", "the program")
        st.subheader(f"Converse: {_prog_name}")

        with st.expander("Program Brief", expanded=True):
            st.markdown(_brief.brief_text)
            st.caption(f"{_brief.word_count} words · brief ID {_brief.brief_id}")

        st.divider()

        for _msg in st.session_state.converse_chat:
            with st.chat_message(_msg["role"]):
                st.markdown(_msg["content"])
                if _msg.get("status"):
                    _color = {"supported": "green", "conflicting": "orange"}.get(_msg["status"], "gray")
                    st.caption(f":{_color}[{_msg['status']}]")

        _question = st.chat_input("Ask a question about this program…")
        if _question:
            st.session_state.converse_chat.append({"role": "user", "content": _question})
            with st.chat_message("user"):
                st.markdown(_question)

            with st.chat_message("assistant"):
                with st.spinner("Answering…"):
                    from converse import answer_question as _answer
                    _result = _answer(_question, _brief, _field_report)
                st.markdown(_result.answer)
                _status_color = {"supported": "green", "conflicting": "orange"}.get(
                    str(_result.status), "gray"
                )
                st.caption(f":{_status_color}[{_result.status}]")

            st.session_state.converse_chat.append({
                "role": "assistant",
                "content": _result.answer,
                "status": str(_result.status),
            })
            st.rerun()

        if st.session_state.converse_chat and st.button("Clear conversation", key="converse_clear"):
            st.session_state.converse_chat = []
            st.rerun()

with tabs[3]:
    render_inspector_tab()
