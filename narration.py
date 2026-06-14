"""Narrator stage — synthesizes a 600-900 word program brief from adjudicated field data."""

from __future__ import annotations

import time

import requests

from providers import provider_for_stage
from schemas import AgentState, BriefOutput, FieldReport, PipelineError, SchemaCoverage, new_id, now_iso


_SECTION_ORDER = [
    "program_basics",
    "earn_mechanics",
    "burn_mechanics",
    "tier_system",
    "partnerships",
    "digital_experience",
    "member_sentiment",
    "competitive_position",
]

_SECTION_LABELS = {
    "program_basics": "Program Overview",
    "earn_mechanics": "Earning",
    "burn_mechanics": "Redemption",
    "tier_system": "Tiers",
    "partnerships": "Partnerships",
    "digital_experience": "Digital Experience",
    "member_sentiment": "Member Sentiment",
    "competitive_position": "Competitive Position",
}

_NARRATION_PROMPT = """\
You are writing a professional loyalty-program intelligence brief for internal use at a loyalty consulting firm.

PROGRAM: {program_name}{brand_suffix}

TASK: Write a 600-900 word authoritative brief covering the program's key attributes. Use ONLY the facts listed in EXTRACTION DATA below. Do not add, infer, or speculate about anything not listed. Where confidence is LOW or a field is flagged, reflect uncertainty naturally in prose (e.g. "reportedly", "per one source", "needs verification").

EXTRACTION DATA:
{context_block}

WRITING RULES:
- Organize into clear paragraphs. Section groupings in the data are a guide — not required as headers.
- Integrate facts naturally into readable prose; do not list raw field names.
- Mark flagged fields as uncertain: "sources conflict on this point" or "this needs verification".
- Do NOT invent any facts, percentages, or details not present in the EXTRACTION DATA.
- If competitive_position data is available, end with a brief competitive or strategic summary.
- Output ONLY the brief text. No preamble, no "Here is the brief:", no meta-commentary.
- Target length: 600-900 words.\
"""

_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def narrator_node(state: AgentState) -> dict:
    """Generate a program brief from the post-adjudication field report."""
    field_report = state.get("field_report")
    if not field_report:
        return {
            "errors": [
                *state.get("errors", []),
                PipelineError(stage="narration", message="Narration skipped: no field report available."),
            ],
            "updated_at": now_iso(),
        }

    usable = [
        e for e in field_report.entries
        if e.value is not None and e.status in ("extracted", "flagged", "ambiguous")
    ]
    if not usable:
        return {
            "errors": [
                *state.get("errors", []),
                PipelineError(stage="narration", message="Narration skipped: field report has no extracted values."),
            ],
            "updated_at": now_iso(),
        }

    program_name = state.get("program_name") or "the program"
    brand = state.get("brand")

    try:
        brief_text = _generate_brief(field_report, program_name, brand)
    except Exception as exc:
        return {
            "errors": [
                *state.get("errors", []),
                PipelineError(stage="narration", message=str(exc)),
            ],
            "updated_at": now_iso(),
        }

    brief = BriefOutput(
        brief_id=new_id("brief"),
        run_id=state.get("run_id") or "",
        brief_text=brief_text,
        word_count=len(brief_text.split()),
    )

    coverage = SchemaCoverage(
        total_fields=len(field_report.entries) or SchemaCoverage.model_fields["total_fields"].default,
        supported_fields=field_report.extracted_count,
        manual_review_fields=field_report.ambiguous_count + field_report.flagged_count,
        null_fields=field_report.not_found_count,
        rejected_fields=0,
    )
    total = coverage.total_fields or 1
    data_quality = round(
        (coverage.supported_fields + coverage.manual_review_fields * 0.3) / total, 2
    )

    return {
        "final_brief": brief,
        "schema_coverage": coverage,
        "data_quality": data_quality,
        "updated_at": now_iso(),
    }


def _generate_brief(field_report: FieldReport, program_name: str, brand: str | None) -> str:
    return _build_template_brief(field_report, program_name, brand)


def _build_context_block(field_report: FieldReport) -> str:
    by_section: dict[str, list[str]] = {}
    for entry in field_report.entries:
        if entry.value is None or entry.status == "not_found":
            continue
        section = entry.field_path.split(".")[0]
        field_label = entry.field_path.split(".", 1)[-1].replace("_", " ")
        conf = entry.confidence or 0.0
        conf_label = "HIGH" if conf >= 0.75 else "MED" if conf >= 0.40 else "LOW"
        flag_note = " [FLAGGED — verify]" if entry.status == "flagged" else ""
        corr = entry.corroboration_count
        line = f"  {field_label}: {entry.value} (conf={conf_label}, corroboration={corr}){flag_note}"
        by_section.setdefault(section, []).append(line)

    parts: list[str] = []
    for section in _SECTION_ORDER:
        lines = by_section.get(section)
        if lines:
            label = _SECTION_LABELS.get(section, section.replace("_", " ").title())
            parts.append(f"[{label}]\n" + "\n".join(lines))
    for section, lines in by_section.items():
        if section not in _SECTION_ORDER:
            label = section.replace("_", " ").title()
            parts.append(f"[{label}]\n" + "\n".join(lines))

    return "\n\n".join(parts) if parts else "(no extracted data)"


def _build_template_brief(field_report: FieldReport, program_name: str, brand: str | None) -> str:
    """Build a structured prose brief directly from extracted field data — no LLM call."""
    by_section: dict[str, dict[str, str]] = {}
    for entry in field_report.entries:
        if entry.value is None or entry.status == "not_found":
            continue
        section = entry.field_path.split(".")[0]
        field = entry.field_path.split(".", 1)[-1].replace("_", " ").title()
        conf = entry.confidence or 0.0
        flag = " *(verify)*" if entry.status in ("flagged", "ambiguous") else ""
        by_section.setdefault(section, {})[field] = f"{entry.value}{flag}"

    brand_suffix = f" ({brand})" if brand and brand != program_name else ""
    paragraphs = [f"# {program_name}{brand_suffix} — Loyalty Intelligence Brief\n"]

    section_intros = {
        "program_basics": "**Program Overview.**",
        "earn_mechanics": "**Earning.**",
        "burn_mechanics": "**Redemption.**",
        "tier_system": "**Tier Structure.**",
        "partnerships": "**Partnerships.**",
        "digital_experience": "**Digital Experience.**",
        "member_sentiment": "**Member Sentiment.**",
        "competitive_position": "**Competitive Position.**",
    }

    for section in _SECTION_ORDER:
        fields = by_section.get(section)
        if not fields:
            continue
        label = section_intros.get(section, f"**{section.replace('_',' ').title()}.**")
        lines = [f"- {k}: {v}" for k, v in fields.items()]
        paragraphs.append(f"{label}\n" + "\n".join(lines))

    for section, fields in by_section.items():
        if section not in _SECTION_ORDER:
            label = f"**{section.replace('_',' ').title()}.**"
            lines = [f"- {k}: {v}" for k, v in fields.items()]
            paragraphs.append(f"{label}\n" + "\n".join(lines))

    if len(paragraphs) == 1:
        paragraphs.append("*No extracted data available for this program.*")

    return "\n\n".join(paragraphs)


def _call_gemini(prompt: str, max_retries: int = 2) -> str:
    provider = provider_for_stage("narration")
    api_key = provider.api_key
    if not api_key:
        raise RuntimeError("Narration is not configured. Set NARRATION_API_KEY or GEMINI_API_KEY.")

    api_base = (provider.api_base or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    model = provider.resolved_model or "gemini-2.5-flash"
    url = f"{api_base}/models/{model}:generateContent"

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        response = requests.post(
            url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 2048,
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            },
            timeout=90,
        )
        if response.status_code not in _TRANSIENT_STATUS_CODES:
            response.raise_for_status()
            payload = response.json()
            return payload["candidates"][0]["content"]["parts"][0]["text"].strip()

        last_error = requests.HTTPError(
            f"Narration LLM returned {response.status_code}",
            response=response,
        )
        if attempt < max_retries:
            time.sleep(2**attempt)

    raise last_error or RuntimeError("Narration LLM request failed.")
