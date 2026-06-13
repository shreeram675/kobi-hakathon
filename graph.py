"""LangGraph orchestration for Kobie's validation-first flow."""

from __future__ import annotations

from collections.abc import Callable
import os
from typing import Literal

from langgraph.graph import END, START, StateGraph

from firecrawl_scraper import scrape_retrieved_urls
from pipeline.nodes.ingest_node import ingest_node as post_firecrawl_ingest_node
from query_generator import generate_queries
from retrieval import retrieve_urls
from schemas import AgentState, PipelineError, build_initial_state, now_iso
from validation import validate_conversation


def input_validator_node(state: AgentState) -> dict:
    messages = state.get("validation_messages") or [{"role": "user", "content": state["user_input"]}]
    validation_result = validate_conversation(messages)
    update: dict = {
        "validation_result": validation_result,
        "updated_at": now_iso(),
    }

    if validation_result.status != "resolved" or validation_result.identity is None:
        update["errors"] = [
            *state["errors"],
            PipelineError(stage="input_validator", message=validation_result.reason or "Input needs clarification."),
        ]
        return update

    identity = validation_result.identity
    update.update(
        {
            "program_identity": identity,
            "program_name": identity.program_name,
            "brand": identity.brand,
            "domain": identity.domain,
            "country_or_region": identity.country_or_region,
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


def firecrawl_node(state: AgentState) -> dict:
    urls = select_urls_for_firecrawl(state.get("retrieved_urls", []))
    if not urls:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="firecrawl_scraper", message="Firecrawl skipped because no retrieved URLs exist."),
            ],
            "updated_at": now_iso(),
        }

    try:
        firecrawl_result = scrape_retrieved_urls(urls)
    except Exception as exc:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="firecrawl_scraper", message=str(exc)),
            ],
            "updated_at": now_iso(),
        }

    all_failed = firecrawl_result.total_urls > 0 and firecrawl_result.successful_scrapes == 0
    failed_message = _firecrawl_all_failed_message(firecrawl_result) if all_failed else None

    return {
        "firecrawl_result": firecrawl_result,
        "scraped_blocks": firecrawl_result.blocks,
        "errors": [
            *state["errors"],
            *(
                [
                    PipelineError(
                        stage="firecrawl_scraper",
                        message=failed_message or "Firecrawl failed for every retrieved URL.",
                    )
                ]
                if all_failed
                else []
            ),
        ],
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
        from narration import narrator_node as _narrator
        return _narrator(state)
    except Exception as exc:
        return {
            "errors": [
                *state.get("errors", []),
                PipelineError(stage="narration", message=str(exc)),
            ],
            "updated_at": now_iso(),
        }


def adjudication_node(state: AgentState) -> dict:
    """Detect conflicting extracted claims and resolve them via debate."""

    try:
        from adjudication.conflict_adjudicator import adjudicator_node

        updated = adjudicator_node(state)
        return {
            "conflicts": updated.get("conflicts", []),
            "adjudicated": updated.get("adjudicated", []),
            "field_report": updated.get("field_report"),
            "human_review_queue": updated.get("human_review_queue", []),
            "updated_at": now_iso(),
        }
    except Exception as exc:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="adjudication", message=str(exc)),
            ],
            "updated_at": now_iso(),
        }


def build_kobie_graph():
    graph = StateGraph(AgentState)
    graph.add_node("input_validator", input_validator_node)
    graph.add_node("query_generator", query_generator_node)
    graph.add_node("retrieval", retrieval_node)
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
    graph.add_edge("query_generator", "retrieval")
    graph.add_edge("retrieval", "firecrawl_scraper")
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

    emit("retrieval", "running", "Retrieving and deduplicating Tavily URLs.")
    state = {**state, **retrieval_node(state)}
    if state.get("retrieval_result"):
        emit("retrieval", "complete", "Unique URL set is ready.")
    else:
        emit("retrieval", "error", _latest_error_message(state, "Retrieval failed."))
        return state

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
    return {**state, **query_generator_node(state)}


def run_retrieval(state: AgentState) -> AgentState:
    return {**state, **retrieval_node(state)}


def run_firecrawl(state: AgentState) -> AgentState:
    return {**state, **firecrawl_node(state)}


def run_ingest(state: AgentState) -> AgentState:
    return {**state, **ingest_node(state)}


def run_adjudication(state: AgentState) -> AgentState:
    return {**state, **adjudication_node(state)}


def _latest_error_message(state: AgentState, fallback: str) -> str:
    errors = state.get("errors", [])
    return errors[-1].message if errors else fallback


def select_urls_for_firecrawl(urls) -> list:
    """Limit Firecrawl spend while keeping every query's field coverage.

    URLs are grouped per originating query and taken round-robin (best URL of
    each query first), so a small scrape budget still covers sentiment, news,
    financial, and competitive queries instead of only official pages. Query
    groups are interleaved by source type so each source class survives a
    budget smaller than the query count.

    A hard floor of MIN_CONSUMER_URLS is reserved for consumer-facing source types
    (review / forum / app_reviews) so sentiment and app-ratings evidence always
    reaches the extraction stage regardless of Tavily relevance scores.
    """

    max_urls = _env_int("MAX_FIRECRAWL_URLS", 12)
    if max_urls <= 0 or len(urls) <= max_urls:
        return list(urls)

    # Source types that carry consumer evidence (sentiment, app ratings, forum threads).
    _CONSUMER_SOURCE_TYPES = frozenset({"review", "forum", "forums", "app_reviews"})
    # Reserve slots proportional to budget (1 per 6 URLs, min 0 so tiny budgets are unaffected).
    min_consumer = max_urls // 6

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

    # Split pool into consumer and non-consumer early so the floor can be enforced.
    consumer_pool = sorted(
        [u for u in urls if str(u.source_type).lower() in _CONSUMER_SOURCE_TYPES],
        key=url_rank,
    )
    non_consumer_pool = [u for u in urls if str(u.source_type).lower() not in _CONSUMER_SOURCE_TYPES]

    # Reserve up to min_consumer slots from the consumer pool.
    reserved_consumer = consumer_pool[:min_consumer]
    remaining_consumer = consumer_pool[min_consumer:]

    # Fill the non-reserved budget using the existing round-robin logic over non-consumer
    # URLs plus any overflow consumer URLs.
    remaining_budget = max_urls - len(reserved_consumer)
    candidates = non_consumer_pool + remaining_consumer

    groups: dict[str, list] = {}
    for item in sorted(candidates, key=url_rank):
        groups.setdefault(str(item.query_id), []).append(item)

    groups_by_type: dict[str, list[list]] = {}
    for group in sorted(groups.values(), key=lambda group: url_rank(group[0])):
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

    round_robin_selected: list = []
    while ordered_groups and len(round_robin_selected) < remaining_budget:
        remaining_groups = []
        for group in ordered_groups:
            if len(round_robin_selected) >= remaining_budget:
                break
            round_robin_selected.append(group.pop(0))
            if group:
                remaining_groups.append(group)
        ordered_groups = remaining_groups

    return reserved_consumer + round_robin_selected


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _firecrawl_all_failed_message(firecrawl_result) -> str:
    errors = [block.error for block in firecrawl_result.blocks if block.error]
    if not errors:
        return "Firecrawl failed for every retrieved URL."

    first_error = errors[0]
    if "Insufficient Credits" in first_error or "Insufficient credits" in first_error:
        return (
            "Firecrawl credentials are valid, but Firecrawl returned insufficient credits. "
            "Add credits or upgrade the Firecrawl plan, then retry."
        )
    if "403 Forbidden" in first_error:
        return (
            "Firecrawl returned 403 Forbidden for every URL. Check Firecrawl plan permissions, "
            "workspace access, and FIRECRAWL_API_BASE."
        )
    return f"Firecrawl failed for every URL. First error: {first_error}"
