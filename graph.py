"""LangGraph orchestration for Kobie's validation-first flow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from langgraph.graph import END, START, StateGraph

from firecrawl_scraper import scrape_retrieved_urls
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
    urls = state.get("retrieved_urls", [])
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

    return {
        "firecrawl_result": firecrawl_result,
        "scraped_blocks": firecrawl_result.blocks,
        "errors": [
            *state["errors"],
            *(
                [
                    PipelineError(
                        stage="firecrawl_scraper",
                        message=(
                            "Firecrawl failed for every retrieved URL. Check FIRECRAWL_API_KEY, "
                            "FIRECRAWL_API_BASE, and Firecrawl plan/access permissions."
                        ),
                    )
                ]
                if firecrawl_result.total_urls > 0 and firecrawl_result.successful_scrapes == 0
                else []
            ),
        ],
        "updated_at": now_iso(),
    }


def build_kobie_graph():
    graph = StateGraph(AgentState)
    graph.add_node("input_validator", input_validator_node)
    graph.add_node("query_generator", query_generator_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("firecrawl_scraper", firecrawl_node)
    graph.add_edge(START, "input_validator")
    graph.add_conditional_edges(
        "input_validator",
        route_after_input_validator,
        {"query_generator": "query_generator", "__end__": END},
    )
    graph.add_edge("query_generator", "retrieval")
    graph.add_edge("retrieval", "firecrawl_scraper")
    graph.add_edge("firecrawl_scraper", END)
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

    emit("firecrawl_scraper", "running", "Scraping URLs and extracting per-URL schema fields.")
    state = {**state, **firecrawl_node(state)}
    if state.get("firecrawl_result") and state["firecrawl_result"].successful_scrapes > 0:
        emit("firecrawl_scraper", "complete", "Per-URL scrape blocks are ready.")
    elif state.get("firecrawl_result"):
        emit("firecrawl_scraper", "error", _latest_error_message(state, "Firecrawl failed for every URL."))
    else:
        emit("firecrawl_scraper", "error", _latest_error_message(state, "Firecrawl scraping failed."))
    return state


def run_query_generation(state: AgentState) -> AgentState:
    return {**state, **query_generator_node(state)}


def run_retrieval(state: AgentState) -> AgentState:
    return {**state, **retrieval_node(state)}


def run_firecrawl(state: AgentState) -> AgentState:
    return {**state, **firecrawl_node(state)}


def _latest_error_message(state: AgentState, fallback: str) -> str:
    errors = state.get("errors", [])
    return errors[-1].message if errors else fallback
