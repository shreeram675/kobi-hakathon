"""Streamlit UI for Kobie's validation-first flow."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from graph import run_validation_chat, run_validation_chat_traced
from validation import verifier_result_as_message


st.set_page_config(page_title="Kobie Phase 2", layout="wide")

st.title("Kobie Phase 2")
st.caption("Grounded loyalty-program intelligence agent")


NODE_LABELS = {
    "input_validator": "Input Validator",
    "query_generator": "Query Generator",
    "retrieval": "Tavily Retrieval",
    "firecrawl_scraper": "Firecrawl Scraper",
}


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
    if state.get("firecrawl_result"):
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
    cols = st.columns(4)
    for column, node in zip(cols, ("input_validator", "query_generator", "retrieval", "firecrawl_scraper")):
        status = statuses[node]
        with column:
            with st.container(border=True):
                st.markdown(f"**{NODE_LABELS[node]}**")
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

    return statuses


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

tabs = st.tabs(["Input verifier", "Compare", "Converse"])

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
    st.info("Converse starts after the final brief is generated. It answers follow-up questions only from stored claim JSON and brief JSON.")
