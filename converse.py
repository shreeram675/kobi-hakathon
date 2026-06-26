"""Converse stage — answers user questions grounded only in the final brief and field report."""

from __future__ import annotations

import cost_tracker
from providers import provider_for_stage
from schemas import BriefOutput, ClaimStatus, ComparisonBrief, ConverseAnswer, FieldReport


_CONVERSE_PROMPT = """\
You are a loyalty-program research assistant. You answer questions ONLY from the BRIEF and FIELD DATA provided below. Never use external knowledge or make inferences beyond what is explicitly stated.

RULES:
- Answer in 1-3 short paragraphs.
- When citing a specific fact, note the field name in parentheses, e.g. (earn_mechanics.base_earn_rate).
- If the answer cannot be found in the data below, reply exactly: "The requested information is not available in the extracted results."
- If a value is flagged as needing verification, mention the caveat clearly.
- Do not speculate or infer beyond what is stated.

BRIEF:
{brief_text}

FIELD DATA (structured):
{field_data}

QUESTION: {question}\
"""

_COMPARE_CONVERSE_PROMPT = """\
You are a senior loyalty program analyst assistant. You answer questions ONLY from the COMPARISON BRIEF and PROGRAM DATA provided below. Never use external knowledge, assumptions, or model-generated facts beyond what is explicitly stated in the data.

RULES:
- Answer in 1-3 short paragraphs.
- When citing a specific fact, note the program name and field in parentheses, e.g. (Delta SkyMiles — earn_mechanics.base_earn_rate).
- If the answer cannot be found in the data below, reply exactly: "The requested information is not available in the extracted results."
- If a value is flagged as needing verification, mention the caveat clearly.
- Do not speculate, infer, or introduce any external knowledge.
- Keep all responses strictly grounded in the comparison data provided.

COMPARISON BRIEF:
{brief_text}

PER-PROGRAM FIELD DATA:
{field_data}

QUESTION: {question}\
"""


def answer_comparison_question(
    question: str,
    comparison_brief: ComparisonBrief,
    program_reports: list[tuple[str, FieldReport | None]],
) -> ConverseAnswer:
    """Answer a comparison question grounded strictly in the comparison brief and field reports."""
    brief_text = _build_comparison_brief_text(comparison_brief)
    field_data = _build_multi_field_data(program_reports)
    prompt = _COMPARE_CONVERSE_PROMPT.format(
        brief_text=brief_text,
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
    if "not available in the extracted results" in lower or "don't have that information" in lower:
        status = ClaimStatus.NOT_FOUND
    elif "conflict" in lower or "needs verification" in lower or "flagged" in lower or "verify" in lower:
        status = ClaimStatus.CONFLICTING
    else:
        status = ClaimStatus.SUPPORTED

    source_urls = _extract_source_urls_multi(answer_text, program_reports)
    return ConverseAnswer(answer=answer_text, status=status, source_urls=source_urls)


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

    source_urls = _extract_source_urls(answer_text, field_report)

    return ConverseAnswer(answer=answer_text, status=status, source_urls=source_urls)


def _extract_source_urls(answer_text: str, field_report: FieldReport | None) -> list[str]:
    """Return deduplicated source URLs for field paths cited in the answer."""
    if not field_report:
        return []
    import re
    cited_paths = set(re.findall(r"\(([a-z_]+\.[a-z_]+(?:\.[a-z_]+)*)\)", answer_text))
    seen: set[str] = set()
    urls: list[str] = []
    for entry in field_report.entries:
        if entry.field_path in cited_paths or not cited_paths:
            for url in (entry.source_urls or []):
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls[:5]  # cap at 5 to keep the UI tidy


def _build_field_data(field_report: FieldReport) -> str:
    lines: list[str] = []
    for entry in field_report.entries:
        if entry.value is None or entry.status == "not_found":
            continue
        flag = " [NEEDS VERIFICATION]" if entry.status == "flagged" else ""
        lines.append(f"{entry.field_path}: {entry.value}{flag}")
    return "\n".join(lines) if lines else "(no extracted values)"


def _build_comparison_brief_text(brief: ComparisonBrief) -> str:
    lines: list[str] = [f"Programs compared: {', '.join(brief.programs)}"]
    if brief.overall_winner:
        lines.append(f"Overall winner: {brief.overall_winner}")
    lines.append(f"\nExecutive Summary:\n{brief.executive_summary}")
    if brief.category_verdicts:
        lines.append("\nCategory Verdicts:")
        for v in brief.category_verdicts:
            lines.append(f"  {v.label}: Winner = {v.winner}. {v.insight}")
    if brief.key_differentiators:
        lines.append("\nKey Differentiators:")
        for d in brief.key_differentiators:
            lines.append(f"  {d.topic} (advantage: {d.advantage}): {d.insight}")
    if brief.personas:
        lines.append("\nWho Should Choose:")
        for p in brief.personas:
            lines.append(f"  {p.program}: Best for {p.best_for}")
    return "\n".join(lines)


def _build_multi_field_data(program_reports: list[tuple[str, FieldReport | None]]) -> str:
    sections: list[str] = []
    for name, field_report in program_reports:
        if field_report is None:
            sections.append(f"=== {name} ===\n(no field data available)")
        else:
            sections.append(f"=== {name} ===\n{_build_field_data(field_report)}")
    return "\n\n".join(sections)


def _extract_source_urls_multi(
    answer_text: str,
    program_reports: list[tuple[str, FieldReport | None]],
) -> list[str]:
    import re
    cited_paths = set(re.findall(r"\((?:[^)]+—\s*)?([a-z_]+\.[a-z_]+(?:\.[a-z_]+)*)\)", answer_text))
    seen: set[str] = set()
    urls: list[str] = []
    for _, field_report in program_reports:
        if field_report is None:
            continue
        for entry in field_report.entries:
            if entry.field_path in cited_paths or not cited_paths:
                for url in (entry.source_urls or []):
                    if url and url not in seen:
                        seen.add(url)
                        urls.append(url)
    return urls[:5]


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
            if response.usage:
                ledger = cost_tracker.get_current_ledger()
                if ledger:
                    ledger.record_groq("converse", response.usage.prompt_tokens or 0, response.usage.completion_tokens or 0)
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
