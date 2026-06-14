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


_CONVERSE_CLIENT_POOL: list | None = None
_CONVERSE_POOL_COUNTER: int = 0


def _build_converse_pool() -> list:
    global _CONVERSE_CLIENT_POOL
    if _CONVERSE_CLIENT_POOL is not None:
        return _CONVERSE_CLIENT_POOL
    import os
    from groq import Groq

    raw = os.getenv("GROQ_API_KEYS", "").strip()
    if raw:
        keys = [k.strip() for k in raw.split(",") if k.strip()]
    else:
        seen: set[str] = set()
        keys = []
        for var in ("CONVERSE_API_KEY", "GROQ_API_KEY"):
            k = os.getenv(var, "").strip()
            if k and k not in seen:
                seen.add(k)
                keys.append(k)
        fallback = provider_for_stage("converse").api_key
        if fallback and fallback not in seen:
            keys.append(fallback)

    if not keys:
        raise RuntimeError("Converse is not configured. Set GROQ_API_KEYS or CONVERSE_API_KEY.")

    _CONVERSE_CLIENT_POOL = [Groq(api_key=k) for k in keys]
    return _CONVERSE_CLIENT_POOL


def _call_groq(prompt: str) -> str:
    import re as _re
    import time

    global _CONVERSE_POOL_COUNTER

    pool = _build_converse_pool()
    pool_size = len(pool)
    model = provider_for_stage("converse").resolved_model or "llama-3.3-70b-versatile"
    max_attempts = pool_size * 2
    delay = 5.0

    for attempt in range(max_attempts):
        client = pool[_CONVERSE_POOL_COUNTER % pool_size]
        _CONVERSE_POOL_COUNTER += 1
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=700,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            msg = str(exc)
            if "rate_limit_exceeded" not in msg and "429" not in msg:
                raise
            m = _re.search(r"try again in ([0-9.]+)s", msg)
            delay = float(m.group(1)) + 0.5 if m else delay * 2
            if attempt == max_attempts - 1:
                raise
            if attempt >= pool_size - 1:
                time.sleep(delay)

    raise RuntimeError("_call_groq: exhausted all keys and retries")
