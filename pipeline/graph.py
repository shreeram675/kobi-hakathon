"""LangGraph orchestration for Kobie's validation-first flow."""

from __future__ import annotations

from collections.abc import Callable
import os
from typing import Literal, cast

from langgraph.graph import END, START, StateGraph

from pipeline.stages.firecrawl_scraper import scrape_retrieved_urls
from pipeline.nodes.ingest_node import ingest_node as post_firecrawl_ingest_node
from pipeline.stages.app_ratings_fetcher import build_app_ratings_packet, fetch_app_ratings
from pipeline.stages.direct_url_seeder import seed_urls
from pipeline.stages.wikipedia_fetcher import build_wikipedia_block, fetch_wikipedia_summary
from pipeline.stages.query_generator import generate_queries
from pipeline.stages.retrieval import retrieve_urls
from core.schemas import AgentState, FirecrawlScrapeOutput, NormalizedObjectPacket, ScrapedUrlBlock, PipelineError, build_initial_state, new_id, now_iso
from pipeline.stages.validation import validate_conversation


def input_validator_node(state: AgentState) -> dict:
    messages = state.get("validation_messages") or [{"role": "user", "content": state["user_input"]}]
    validation_result = validate_conversation(messages)
    update: dict = {
        "validation_result": validation_result,
        "validation_messages": messages,  # persist so clarify can append to the full conversation
        "updated_at": now_iso(),
    }

    if validation_result.status == "rejected":
        update["errors"] = [
            *state["errors"],
            PipelineError(stage="input_validator", message=validation_result.reason or "Input could not be resolved."),
        ]
        return update

    if validation_result.status != "resolved" or validation_result.identity is None:
        # needs_clarification — awaiting follow-up answers, not an error
        return update

    identity = validation_result.identity
    update.update(
        {
            "program_identity": identity,
            "program_name": identity.program_name,
            "brand": identity.brand,
            "domain": identity.domain,
            "country_or_region": identity.country_or_region,
            "program_subtype": identity.program_subtype,
        }
    )
    return update


def route_after_input_validator(state: AgentState) -> Literal["query_generator", "__end__"]:
    result = state.get("validation_result")
    if result and result.status == "resolved" and result.identity is not None:
        return "query_generator"
    return "__end__"


def query_generator_node(state: AgentState) -> dict:
    identity = state.get("program_identity")
    if identity is None:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="query_generator", message="Query generator skipped because program identity is missing."),
            ],
            "updated_at": now_iso(),
        }

    try:
        query_generation_result = generate_queries(identity)
    except Exception as exc:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="query_generator", message=str(exc)),
            ],
            "updated_at": now_iso(),
        }

    return {
        "query_generation_result": query_generation_result,
        "search_queries": query_generation_result.queries,
        "updated_at": now_iso(),
    }


def app_ratings_node(state: AgentState) -> dict:
    program_name = state.get("program_name") or ""
    brand = state.get("brand") or program_name
    country = (state.get("country_or_region") or "us").lower()
    if country in {"india", "in"}:
        country = "in"
    else:
        country = "us"

    try:
        result = fetch_app_ratings(program_name, brand, country=country)
        raw = build_app_ratings_packet(result, program_name)
        packet = NormalizedObjectPacket.model_validate(raw) if raw else None
    except Exception as exc:
        return {
            "prefetched_app_ratings": None,
            "errors": [*state["errors"], PipelineError(stage="app_ratings", message=str(exc))],
            "updated_at": now_iso(),
        }

    return {"prefetched_app_ratings": packet, "updated_at": now_iso()}


def web_enrichment_node(state: AgentState) -> dict:
    """Inject directly-known URLs and Wikipedia text without spending Tavily budget.

    Runs after retrieval so it can append seeded URLs to retrieved_urls before
    Firecrawl picks them up. Wikipedia extract goes into additional_blocks so
    ingest_node processes it alongside Firecrawl output.
    """
    program_name = state.get("program_name") or ""
    brand = state.get("brand") or program_name
    identity = state.get("program_identity")
    official_domain = identity.official_domain if identity else None

    # --- direct URL seeding --------------------------------------------------
    app_ratings = state.get("prefetched_app_ratings")
    app_store_url: str | None = None
    play_store_url: str | None = None
    if app_ratings:
        for field_name, field_val in app_ratings.fields.items():
            if field_name == "app_store_rating" and field_val.source_url:
                app_store_url = field_val.source_url
            elif field_name == "play_store_rating" and field_val.source_url:
                play_store_url = field_val.source_url

    try:
        seeded = seed_urls(
            brand=brand,
            program_name=program_name,
            official_domain=official_domain,
            app_store_url=app_store_url,
            play_store_url=play_store_url,
        )
    except Exception as exc:
        seeded = []
        _log_enrichment_error("url_seeder", exc)

    existing_urls = state.get("retrieved_urls", [])
    existing_canonical = {u.canonical_url for u in existing_urls}
    new_urls = [u for u in seeded if u.canonical_url not in existing_canonical]
    merged_urls = existing_urls + new_urls

    # --- Wikipedia extract ---------------------------------------------------
    additional_blocks: list[ScrapedUrlBlock] = list(state.get("additional_blocks") or [])
    try:
        wiki = fetch_wikipedia_summary(brand, program_name)
        if wiki:
            raw = build_wikipedia_block(wiki)
            block = ScrapedUrlBlock.model_validate(raw)
            existing_wiki = {b.canonical_url for b in additional_blocks}
            if block.canonical_url not in existing_wiki:
                additional_blocks = [block, *additional_blocks]
    except Exception as exc:
        _log_enrichment_error("wikipedia", exc)

    return {
        "retrieved_urls": merged_urls,
        "additional_blocks": additional_blocks,
        "updated_at": now_iso(),
    }


def _log_enrichment_error(source: str, exc: Exception) -> None:
    import logging
    logging.getLogger(__name__).warning("web_enrichment[%s] non-fatal error: %s", source, exc)


def retrieval_node(state: AgentState) -> dict:
    queries = state.get("search_queries", [])
    if not queries:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="retrieval", message="Retrieval skipped because no search queries exist."),
            ],
            "updated_at": now_iso(),
        }

    try:
        retrieval_result = retrieve_urls(queries)
    except Exception as exc:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="retrieval", message=str(exc)),
            ],
            "updated_at": now_iso(),
        }

    return {
        "retrieval_result": retrieval_result,
        "retrieved_urls": retrieval_result.urls,
        "updated_at": now_iso(),
    }


def firecrawl_node(state: AgentState, on_progress=None) -> dict:
    all_retrieved = state.get("retrieved_urls", [])
    ordered = select_urls_for_firecrawl(all_retrieved)
    if not ordered:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="firecrawl_scraper", message="Firecrawl skipped because no retrieved URLs exist."),
            ],
            "updated_at": now_iso(),
        }

    batch = ordered[:20]

    try:
        batch_result = scrape_retrieved_urls(batch, on_progress=on_progress)
    except Exception as exc:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="firecrawl_scraper", message=str(exc)),
            ],
            "updated_at": now_iso(),
        }

    successes = sum(1 for b in batch_result.blocks if b.scrape_status == "success" and b.content)
    firecrawl_result = FirecrawlScrapeOutput(
        total_urls=len(batch_result.blocks),
        successful_scrapes=successes,
        failed_scrapes=len(batch_result.blocks) - successes,
        blocks=batch_result.blocks,
    )

    return {
        "firecrawl_result": firecrawl_result,
        "scraped_blocks": firecrawl_result.blocks,
        "errors": state["errors"],
        "updated_at": now_iso(),
    }


def ingest_node(state: AgentState) -> dict:
    try:
        return post_firecrawl_ingest_node(state)
    except Exception as exc:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="ingest", message=str(exc)),
            ],
            "updated_at": now_iso(),
        }


def narrator_node(state: AgentState) -> dict:
    """Generate a 600-900 word program brief from the adjudicated field report."""
    try:
        from pipeline.stages.narration import narrator_node as _narrator
        return _narrator(state)
    except Exception as exc:
        return {
            "errors": [
                *state.get("errors", []),
                PipelineError(stage="narration", message=str(exc)),
            ],
            "updated_at": now_iso(),
        }


def _build_debate_rounds(entry: dict) -> list[dict]:
    """Convert flat debate transcript keys into DebateRound list for the frontend."""
    debate = entry.get("debate") or {}
    rounds = []
    n = 1
    for phase, agent, key in [
        ("opening",  "Advocate A", "argument_a"),
        ("opening_b","Advocate B", "argument_b"),
        ("cross",    "Advocate A", "rebuttal_a"),
        ("cross_b",  "Advocate B", "rebuttal_b"),
    ]:
        text = debate.get(key) or ""
        if text.strip():
            rounds.append({"round": n, "phase": phase, "agent": agent, "argument": text})
            n += 1
    reasoning = entry.get("reasoning") or debate.get("reasoning") or ""
    if reasoning.strip():
        rounds.append({"round": n, "phase": "final_decision", "agent": "Judge", "argument": reasoning})
    return rounds


def _shape_adjudicated(adjudicated: list[dict], conflict_records: list[dict]) -> list[dict]:
    """Map flat adjudicator output → AdjudicatedClaim shape the frontend expects."""
    cr_by_field = {cr.get("field_path", ""): cr for cr in conflict_records}
    seen: set[str] = set()
    result = []
    for entry in adjudicated:
        field = entry.get("field_name", "")
        if field in seen:
            continue  # FLAG creates two entries per field; keep first
        seen.add(field)
        cr = cr_by_field.get(field, {})
        resolution = entry.get("resolution", "")
        winner = entry.get("winner", "FLAG")
        if resolution == "flag" or winner == "FLAG":
            res_status = "manual_review_needed"
        elif resolution == "auto":
            res_status = "auto_resolved"
        else:
            res_status = cr.get("resolution_status", "debate_required")
        rounds = _build_debate_rounds(entry)
        if not rounds and entry.get("reasoning"):
            rounds = [{"round": 1, "phase": "final_decision", "agent": "Judge",
                       "argument": entry["reasoning"]}]
        result.append({
            "conflict_id": cr.get("conflict_id") or new_id("conflict"),
            "field_path": field,
            "resolution_status": res_status,
            "winning_claim_id": None,
            "decision": winner,
            "rounds": rounds,
            "confidence": float(entry.get("confidence") or 0.0),
        })
    return result


def adjudication_node(state: AgentState) -> dict:
    """Detect conflicting extracted claims and resolve them via debate."""

    try:
        from pipeline.adjudication.conflict_adjudicator import adjudicator_node

        updated = adjudicator_node(state)
        raw_adj = updated.get("adjudicated", [])
        conflict_records = updated.get("conflicts", [])
        return {
            "conflicts": conflict_records,
            "adjudicated": _shape_adjudicated(raw_adj, conflict_records),
            "extracted_claims": updated.get("extracted_claims", []),
            "field_report": updated.get("field_report"),
            "human_review_queue": updated.get("human_review_queue", []),
            "updated_at": now_iso(),
        }
    except Exception as exc:
        from pipeline.adjudication.conflict_adjudicator import _claims_from_field_report
        extracted_claims = _claims_from_field_report(state.get("field_report"), state.get("run_id", ""))
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="adjudication", message=str(exc)),
            ],
            "conflicts": [],
            "adjudicated": [],
            "extracted_claims": extracted_claims,
            "updated_at": now_iso(),
        }


def build_kobie_graph():
    graph = StateGraph(AgentState)
    graph.add_node("input_validator", input_validator_node)
    graph.add_node("query_generator", query_generator_node)
    graph.add_node("app_ratings", app_ratings_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("web_enrichment", web_enrichment_node)
    graph.add_node("firecrawl_scraper", firecrawl_node)
    graph.add_node("ingest", ingest_node)
    graph.add_node("adjudication", adjudication_node)
    graph.add_node("narration", narrator_node)
    graph.add_edge(START, "input_validator")
    graph.add_conditional_edges(
        "input_validator",
        route_after_input_validator,
        {"query_generator": "query_generator", "__end__": END},
    )
    graph.add_edge("query_generator", "app_ratings")
    graph.add_edge("app_ratings", "retrieval")
    graph.add_edge("retrieval", "web_enrichment")
    graph.add_edge("web_enrichment", "firecrawl_scraper")
    graph.add_edge("firecrawl_scraper", "ingest")
    graph.add_edge("ingest", "adjudication")
    graph.add_edge("adjudication", "narration")
    graph.add_edge("narration", END)
    return graph.compile()


KOBIE_GRAPH = build_kobie_graph()


def run_single(user_input: str) -> AgentState:
    state = build_initial_state(user_input)
    return KOBIE_GRAPH.invoke(state)


def run_validation_chat(messages: list[dict[str, str]]) -> AgentState:
    user_input = " | ".join(message["content"] for message in messages if message.get("role") == "user")
    state = build_initial_state(user_input)
    state["validation_messages"] = messages
    return KOBIE_GRAPH.invoke(state)


def run_validation_chat_traced(
    messages: list[dict[str, str]],
    on_event: Callable[[str, str, str], None] | None = None,
) -> AgentState:
    """Run the current linear graph while reporting node-level UI events."""

    def emit(node: str, status: str, message: str) -> None:
        if on_event:
            on_event(node, status, message)

    user_input = " | ".join(message["content"] for message in messages if message.get("role") == "user")
    state = build_initial_state(user_input)
    state["validation_messages"] = messages

    emit("input_validator", "running", "Resolving the program identity.")
    state = {**state, **input_validator_node(state)}
    result = state.get("validation_result")
    if result and result.status == "resolved":
        emit("input_validator", "complete", "Program identity resolved.")
    elif result and result.status == "rejected":
        emit("input_validator", "error", "No known loyalty program found.")
        return state
    else:
        emit("input_validator", "waiting", "Clarification is required.")
        return state

    emit("query_generator", "running", "Generating high-value Tavily queries.")
    state = {**state, **query_generator_node(state)}
    if state.get("query_generation_result"):
        emit("query_generator", "complete", "Query plan generated.")
    else:
        emit("query_generator", "error", _latest_error_message(state, "Query generation failed."))
        return state

    emit("app_ratings", "running", "Fetching app ratings from Google Play and App Store.")
    state = {**state, **app_ratings_node(state)}
    if state.get("prefetched_app_ratings"):
        emit("app_ratings", "complete", "App ratings fetched directly from store APIs.")
    else:
        emit("app_ratings", "waiting", "No app ratings found (program may not have a public app).")

    emit("retrieval", "running", "Retrieving and deduplicating Tavily URLs.")
    state = {**state, **retrieval_node(state)}
    if state.get("retrieval_result"):
        emit("retrieval", "complete", "Unique URL set is ready.")
    else:
        emit("retrieval", "error", _latest_error_message(state, "Retrieval failed."))
        return state

    emit("web_enrichment", "running", "Seeding direct URLs and fetching Wikipedia company data.")
    state = {**state, **web_enrichment_node(state)}
    n_seeded = len(cast(list, state.get("additional_blocks") or []))
    emit("web_enrichment", "complete", f"Direct URLs injected; {n_seeded} additional block(s) ready.")

    emit("firecrawl_scraper", "running", "Scraping URLs into raw markdown blocks.")
    state = {**state, **firecrawl_node(state)}
    if state.get("firecrawl_result") and state["firecrawl_result"].successful_scrapes > 0:
        emit("firecrawl_scraper", "complete", "Per-URL scrape blocks are ready.")
    elif state.get("firecrawl_result"):
        emit("firecrawl_scraper", "error", _latest_error_message(state, "Firecrawl failed for every URL."))
        return state
    else:
        emit("firecrawl_scraper", "error", _latest_error_message(state, "Firecrawl scraping failed."))
        return state

    emit("ingest", "running", "Storing, chunking, extracting, and normalizing scraped evidence.")
    state = {**state, **ingest_node(state)}
    if state.get("normalized_packets"):
        emit("ingest", "complete", "Normalized object packets are ready.")
    elif state.get("semantic_chunks"):
        emit("ingest", "waiting", "Chunks are ready, but no explicit schema facts were extracted.")
        return state
    elif state.get("raw_documents"):
        emit("ingest", "waiting", "Raw documents are stored, but no semantic chunks were produced.")
        return state
    else:
        emit("ingest", "waiting", "No usable raw documents were stored after Firecrawl.")
        return state

    emit("adjudication", "running", "Detecting conflicting claims and running adversarial debates.")
    state = {**state, **adjudication_node(state)}
    conflicts = state.get("conflicts", [])
    if conflicts:
        emit("adjudication", "complete", f"Adjudicated {len(conflicts)} conflicting fields.")
    else:
        emit("adjudication", "complete", "No conflicting claims between sources.")

    emit("narration", "running", "Synthesizing the program brief from adjudicated claims.")
    state = {**state, **narrator_node(state)}
    if state.get("final_brief"):
        emit("narration", "complete", f"Brief generated ({state['final_brief'].word_count} words).")
    else:
        emit("narration", "error", _latest_error_message(state, "Narration failed."))
    return state


def run_query_generation(state: AgentState) -> AgentState:
    return cast(AgentState, {**state, **query_generator_node(state)})


def run_retrieval(state: AgentState) -> AgentState:
    return cast(AgentState, {**state, **retrieval_node(state)})


def run_firecrawl(state: AgentState) -> AgentState:
    return cast(AgentState, {**state, **firecrawl_node(state)})


def run_ingest(state: AgentState) -> AgentState:
    return cast(AgentState, {**state, **ingest_node(state)})


def run_adjudication(state: AgentState) -> AgentState:
    return cast(AgentState, {**state, **adjudication_node(state)})


def _latest_error_message(state: AgentState, fallback: str) -> str:
    errors = state.get("errors", [])
    return errors[-1].message if errors else fallback


def select_urls_for_firecrawl(urls) -> list:
    """Return all retrieved URLs in coverage-aware priority order.

    URLs are grouped per originating query and interleaved round-robin across
    source types so the caller can take the first N and still get broad field
    coverage (official, terms, financial, review, forum, etc.) rather than
    many URLs from a single high-scoring query.

    The caller takes the first N from the returned list.
    """
    if not urls:
        return []

    priority = {
        "official": 0,
        "terms": 1,
        "financial": 2,
        "faq": 3,
        "partners": 4,
        "review": 5,
        "valuation": 5,
        "app_reviews": 6,
        "news": 7,
        "forum": 8,
        "forums": 8,
        "competitors": 9,
    }

    def url_rank(item):
        return (priority.get(str(item.source_type).lower(), 50), -float(item.score or 0))

    groups: dict[str, list] = {}
    for item in sorted(urls, key=url_rank):
        groups.setdefault(str(item.query_id), []).append(item)

    groups_by_type: dict[str, list[list]] = {}
    for group in sorted(groups.values(), key=lambda g: url_rank(g[0])):
        groups_by_type.setdefault(str(group[0].source_type).lower(), []).append(group)

    ordered_groups: list[list] = []
    type_queues = list(groups_by_type.values())
    while type_queues:
        remaining_queues = []
        for queue in type_queues:
            ordered_groups.append(queue.pop(0))
            if queue:
                remaining_queues.append(queue)
        type_queues = remaining_queues

    result: list = []
    while ordered_groups:
        remaining_groups = []
        for group in ordered_groups:
            result.append(group.pop(0))
            if group:
                remaining_groups.append(group)
        ordered_groups = remaining_groups

    return result


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
