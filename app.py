"""Streamlit UI for Kobie's validation-first flow."""

from __future__ import annotations

import streamlit as st

from graph import run_validation_chat
from validation import verifier_result_as_message


st.set_page_config(page_title="Kobie Phase 2", layout="wide")

st.title("Kobie Phase 2")
st.caption("Grounded loyalty-program intelligence agent")


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


def reset_compare_side(side: str) -> None:
    st.session_state[f"compare_{side}_input"] = ""
    st.session_state[f"compare_{side}_state"] = None


def run_compare_side(side: str, program_input: str) -> None:
    if not program_input.strip():
        st.session_state[f"compare_{side}_state"] = None
        return

    st.session_state[f"compare_{side}_state"] = run_validation_chat(
        [{"role": "user", "content": program_input.strip()}]
    )


def render_flow_state(state) -> None:
    if not state:
        st.info("Enter a program name and run the workflow.")
        return

    result = state.get("validation_result")
    if result is None:
        st.warning("No validation result returned.")
        return

    if result.status == "resolved" and result.identity:
        st.success("Resolved and ready for the next stage")
        st.metric("Program", result.identity.program_name)
        st.metric("Domain", result.identity.domain)
        st.metric("Confidence", f"{result.confidence:.2f}")

        query_result = state.get("query_generation_result")
        if query_result:
            st.subheader("Query generator")
            st.caption(query_result.query_strategy_summary)
            st.json(
                {
                    "detected_category": query_result.detected_category,
                    "priority_fields": query_result.priority_fields,
                    "queries": [query.model_dump() for query in query_result.queries],
                }
            )
        elif state.get("errors"):
            st.warning(state["errors"][-1].message)
        return

    if result.status == "rejected":
        st.error("No such loyalty program found")
    else:
        st.warning("Needs clarification before retrieval")
    st.markdown(result_to_assistant_text(result))
    st.json(result.model_dump())


def render_compare_card(side: str, title: str) -> None:
    with st.container(border=True):
        st.subheader(title)
        with st.form(f"compare_{side}_form"):
            program_input = st.text_input(
                "Program name",
                key=f"compare_{side}_input",
                placeholder="Example: Marriott Bonvoy",
            )
            submitted = st.form_submit_button("Run workflow")
            if submitted:
                run_compare_side(side, program_input)
                st.rerun()

        if st.button("Reset", key=f"compare_{side}_reset"):
            reset_compare_side(side)
            st.rerun()

        render_flow_state(st.session_state.get(f"compare_{side}_state"))


if "validator_chat" not in st.session_state:
    reset_validator_chat()
if "compare_a_state" not in st.session_state:
    reset_compare_side("a")
if "compare_b_state" not in st.session_state:
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

            state = run_validation_chat(st.session_state.validator_llm_messages)
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
        st.subheader("Flow initializer")
        result = st.session_state.validation_result
        if result and result.status == "resolved" and result.identity:
            st.success("Ready to start retrieval")
            st.metric("Program", result.identity.program_name)
            st.metric("Domain", result.identity.domain)
            st.metric("Confidence", f"{result.confidence:.2f}")
            state = st.session_state.last_graph_state
            query_result = state.get("query_generation_result") if state else None
            if query_result:
                st.subheader("Query generator")
                st.caption(query_result.query_strategy_summary)
                st.json(
                    {
                        "detected_category": query_result.detected_category,
                        "priority_fields": query_result.priority_fields,
                        "queries": [query.model_dump() for query in query_result.queries],
                    }
                )
            elif state and state.get("errors"):
                st.warning(state["errors"][-1].message)
        elif result:
            if result.status == "rejected":
                st.error("No such loyalty program found")
            else:
                st.warning("Waiting for a high-confidence program identity")
            st.json(result.model_dump())
        else:
            st.info("The rest of the pipeline stays locked until the verifier resolves one program with confidence >= 0.90.")

with tabs[1]:
    st.subheader("Compare two programs")
    st.caption("Each side runs the same validation-first workflow independently. The final comparison output will be configured later.")

    a_card, b_card = st.columns(2, gap="large")
    with a_card:
        render_compare_card("a", "Program A")
    with b_card:
        render_compare_card("b", "Program B")

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
