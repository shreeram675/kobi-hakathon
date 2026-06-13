"""Converse stage — answers user questions grounded only in the final brief and field report."""

from __future__ import annotations

from providers import provider_for_stage
from schemas import BriefOutput, ClaimStatus, ConverseAnswer, FieldReport


_CONVERSE_PROMPT = """\
You are a loyalty-program research assistant. You answer questions ONLY from the BRIEF and FIELD DATA provided below. Never use external knowledge or make inferences beyond what is explicitly stated.

RULES:
- Answer in 1-3 short paragraphs.
- When citing a specific fact, note the field name in parentheses, e.g. (earn_mechanics.base_earn_rate).
- If the answer cannot be found in the data below, reply exactly: "I don't have that information in the current brief."
- If a value is flagged as needing verification, mention the caveat clearly.
- Do not speculate or infer beyond what is stated.

BRIEF:
{brief_text}

FIELD DATA (structured):
{field_data}

QUESTION: {question}\
"""


def answer_question(
    question: str,
    brief: BriefOutput,
    field_report: FieldReport | None = None,
) -> ConverseAnswer:
    """Answer a single question grounded in the brief and field report."""
    field_data = _build_field_data(field_report) if field_report else "(no structured field data)"
    prompt = _CONVERSE_PROMPT.format(
        brief_text=brief.brief_text,
        field_data=field_data,
        question=question,
    )

    try:
        answer_text = _call_groq(prompt)
    except Exception as exc:
        return ConverseAnswer(
            answer=f"Error: {exc}",
            status=ClaimStatus.NULL,
        )

    lower = answer_text.lower()
    if "don't have that information" in lower or "not in the current brief" in lower:
        status = ClaimStatus.NOT_FOUND
    elif "conflict" in lower or "needs verification" in lower or "flagged" in lower:
        status = ClaimStatus.CONFLICTING
    else:
        status = ClaimStatus.SUPPORTED

    return ConverseAnswer(answer=answer_text, status=status)


def _build_field_data(field_report: FieldReport) -> str:
    lines: list[str] = []
    for entry in field_report.entries:
        if entry.value is None or entry.status == "not_found":
            continue
        flag = " [NEEDS VERIFICATION]" if entry.status == "flagged" else ""
        lines.append(f"{entry.field_path}: {entry.value}{flag}")
    return "\n".join(lines) if lines else "(no extracted values)"


def _call_groq(prompt: str) -> str:
    from groq import Groq

    provider = provider_for_stage("converse")
    api_key = provider.api_key
    if not api_key:
        raise RuntimeError("Converse is not configured. Set CONVERSE_API_KEY or GROQ_API_KEY.")

    model = provider.resolved_model or "llama-3.1-70b-versatile"
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=700,
    )
    return (response.choices[0].message.content or "").strip()
