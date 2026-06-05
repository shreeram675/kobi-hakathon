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


if "validator_chat" not in st.session_state:
    reset_validator_chat()

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
    st.info("Comparison wiring is scaffolded. Run two completed states before comparing.")

with tabs[2]:
    st.info("Converse is scaffolded to answer only from stored claim JSON.")
