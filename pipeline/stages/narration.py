"""Narrator stage — synthesizes a 600-900 word program brief from adjudicated field data."""

from __future__ import annotations

from core.schemas import AgentState, BriefOutput, FieldReport, PipelineError, SchemaCoverage, new_id, now_iso


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


