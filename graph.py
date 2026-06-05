"""LangGraph orchestration for Kobie's validation-first flow."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from query_generator import generate_queries
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


def build_kobie_graph():
    graph = StateGraph(AgentState)
    graph.add_node("input_validator", input_validator_node)
    graph.add_node("query_generator", query_generator_node)
    graph.add_edge(START, "input_validator")
    graph.add_conditional_edges(
        "input_validator",
        route_after_input_validator,
        {"query_generator": "query_generator", "__end__": END},
    )
    graph.add_edge("query_generator", END)
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


def run_query_generation(state: AgentState) -> AgentState:
    return {**state, **query_generator_node(state)}
