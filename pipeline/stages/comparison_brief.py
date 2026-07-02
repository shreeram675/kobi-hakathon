"""Generates a structured competitive comparison brief from multiple program field reports."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

from core import cost_tracker
from core.providers import provider_for_stage
from core.schemas import (
    CategoryVerdict,
    ComparisonBrief,
    DifferentiationTheme,
    FieldReport,
    KeyDifferentiator,
    ProgramPersona,
    ProgramStrategicProfile,
    new_id,
    now_iso,
)

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
    "tier_system": "Tier Structure",
    "partnerships": "Partnerships",
    "digital_experience": "Digital Experience",
    "member_sentiment": "Member Sentiment",
    "competitive_position": "Competitive Position",
}

_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

_PROMPT_TEMPLATE = """\
You are a senior loyalty program analyst producing a competitive intelligence brief for a consulting client.

You have extracted intelligence on {n} loyalty programs: {program_names}.

Your task: compare these programs and produce a structured JSON brief. Base EVERY judgment solely on the data provided below — do not use external knowledge or make up facts.

{program_blocks}

OUTPUT (strict JSON only — no markdown fences, no commentary):
{{
  "overall_winner": "<program name that clearly leads, or null if genuinely tied>",
  "executive_summary": "<An analyst narrative, 250-400 words, written as flowing prose paragraphs (separate paragraphs with \\n\\n) — NOT a bulleted list and NOT a single terse blurb. Open with the headline finding and who leads overall and why; then walk through the 2-3 categories where the programs differ most sharply, weaving in actual numbers and domain-only source citations like (source: domain.com) as you go; close with a short takeaway on which consumer profile each program suits best. Never paste full URLs into this text.>",
  "category_verdicts": [
    {{
      "category": "<category key from list below>",
      "label": "<human-readable label>",
      "winner": "<program name, 'Tie', or 'Insufficient data'>",
      "insight": "<1-2 crisp sentences citing actual values, e.g. '10 pts/$ vs 5 miles/$ — Aerie earns 3x faster.' Cite sources by domain only, e.g. (source: example.com) — NEVER paste full URLs into this text. If a conflicting value was rejected, add one short clause noting it.>",
      "source_urls": ["<full URL 1>", "<full URL 2>"]
    }}
  ],
  "key_differentiators": [
    {{
      "topic": "<short topic name>",
      "insight": "<2-3 sentences, specific numbers; cite by domain only e.g. (source: example.com), never full URLs>",
      "advantage": "<program name that wins on this dimension>",
      "source_urls": ["<full URL>"],
      "rejected_note": "<if a conflicting value exists: 'Program X also claimed Y (source: url) — rejected because Z'. Omit field if no conflict.>"
    }}
  ],
  "personas": [
    {{
      "program": "<program name>",
      "best_for": "<the specific type of traveller/consumer who gets the most value here>"
    }}
  ],
  "strategic_profiles": [
    {{
      "program": "<program name>",
      "advantages": ["<2-4 concise bullet strings — each a distinct strategic strength of this program, grounded in extracted data>"],
      "gaps": ["<2-4 concise bullet strings — each a distinct weakness, data gap, or area where this program trails competitors>"]
    }}
  ]
}}

RULES:
- executive_summary is the centerpiece of this brief — write it as genuine analyst prose (multiple paragraphs, no bullet points), not a compressed list of facts
- category_verdicts must cover all 8 categories in this order: {category_keys}
- key_differentiators: pick the 3-5 most impactful differences only
- personas: one entry per program
- strategic_profiles: one entry per program; advantages and gaps must be grounded in extracted data, not invented
- If a category has no data for any program, set winner to "Insufficient data" and insight to "No data extracted."
- overall_winner must be null if the margin is not meaningful or data is sparse
- NEVER paste full URLs (https://...) into insight/summary/advantages/gaps prose — cite by bare domain, e.g. (source: example.com). Full URLs belong ONLY in the source_urls arrays
- strategic_profiles advantages/gaps bullets must be short punchy phrases (under 15 words each), no URLs
- For every field that lists a REJECTED value, you MUST acknowledge it: state the rejected value, its source, and why it was rejected
- When a field shows "REJECTED" data, the reason often reveals whether the data was stale, lower-confidence, or from a less authoritative source — explain this nuance
- Do NOT reject one source entirely when both may be valid (e.g. one is recent data, one is older) — instead acknowledge the discrepancy with context
- Fields marked "[varies by context]" contain ALL_VALUES entries showing all simultaneously-valid rates. Use these to say "earns X on Y and Z on W" rather than a single flat number
- Fields marked "[range across sources]" list values from multiple sources that may apply to different categories — describe the full range in your insight
- Fields marked "[combined from multiple sources]" are union-merged lists — treat the merged value as the complete picture
- source_urls arrays must contain the full URLs (https://...), not just domains
- Target total brief length: 500-900 words across all fields combined — concise and scannable beats exhaustive
- Output ONLY the JSON object. No preamble.\
"""


def _build_program_block(name: str, field_report: FieldReport) -> str:
    by_section: dict[str, list[str]] = {}
    for entry in field_report.entries:
        if entry.value is None or entry.status == "not_found":
            continue
        section = entry.field_path.split(".")[0]
        field_label = entry.field_path.split(".", 1)[-1].replace("_", " ")
        conf = entry.confidence or 0.0
        conf_label = "HIGH" if conf >= 0.75 else "MED" if conf >= 0.40 else "LOW"
        flag = " [verify]" if entry.status in ("flagged", "ambiguous") else ""
        sources_str = ""
        if entry.source_urls:
            sources_str = "\n      Sources: " + ", ".join(entry.source_urls)

        # Show conflict_type annotation when values were merged/ranged
        conflict_note = ""
        ct = getattr(entry, "conflict_type", None)
        if ct and ct != "contradictory":
            ct_labels = {
                "complementary": "varies by context",
                "range": "range across sources",
                "union": "combined from multiple sources",
                "recency": "most recent value kept",
                "majority_vote": "majority consensus",
            }
            conflict_note = f" [{ct_labels.get(ct, ct)}]"

        lines_for_field = [f"    {field_label}: {entry.value} (conf={conf_label}){flag}{conflict_note}{sources_str}"]

        # Show all simultaneously-valid values for non-contradictory resolutions
        all_vals = getattr(entry, "all_values", None)
        if all_vals and ct and ct != "contradictory":
            for av in all_vals:
                av_val = av.get("value", "")
                av_ctx = av.get("context")
                av_url = av.get("source_url", "")
                ctx_str = f" (context: {av_ctx})" if av_ctx else ""
                src_str = f" | source: {av_url}" if av_url else ""
                lines_for_field.append(f"      ALL_VALUES: {av_val}{ctx_str}{src_str}")

        for rej in (entry.rejected_alternatives or []):
            rej_val = rej.get("value", "")
            rej_urls = rej.get("source_urls") or []
            rej_reason = rej.get("reason", "")
            rej_src = (", ".join(rej_urls)) if rej_urls else "unknown source"
            lines_for_field.append(f"      REJECTED: {rej_val} | source: {rej_src} | reason: {rej_reason}")
        by_section.setdefault(section, []).extend(lines_for_field)

    parts: list[str] = [f"=== {name} ==="]
    for section in _SECTION_ORDER:
        lines = by_section.get(section)
        if lines:
            label = _SECTION_LABELS.get(section, section.replace("_", " ").title())
            parts.append(f"  [{label}]\n" + "\n".join(lines))
    for section, lines in by_section.items():
        if section not in _SECTION_ORDER:
            label = section.replace("_", " ").title()
            parts.append(f"  [{label}]\n" + "\n".join(lines))

    if len(parts) == 1:
        parts.append("  (no data extracted)")
    return "\n".join(parts)


def _collect_known_urls(field_reports: list[FieldReport]) -> set[str]:
    """Collect all source URLs that actually appear in the provided field reports."""
    known: set[str] = set()
    for fr in field_reports:
        for entry in fr.entries:
            for url in (entry.source_urls or []):
                if url:
                    known.add(url)
    return known


def _filter_invented_urls(urls: list[str], known: set[str]) -> list[str]:
    """Drop any URL the LLM generated that wasn't in the provided data."""
    return [u for u in urls if u in known]


def generate_comparison_brief(
    run_id: str,
    programs: list[str],
    field_reports: list[FieldReport],
) -> ComparisonBrief:
    program_blocks = "\n\n".join(
        _build_program_block(name, fr) for name, fr in zip(programs, field_reports)
    )
    prompt = _PROMPT_TEMPLATE.format(
        n=len(programs),
        program_names=", ".join(programs),
        program_blocks=program_blocks,
        category_keys=", ".join(_SECTION_ORDER),
    )

    known_urls = _collect_known_urls(field_reports)
    raw = _call_gemini(prompt)
    data = _parse_json(raw)
    if not data.get("category_verdicts"):
        # The model occasionally returns a hollow object (summary only, empty
        # arrays). Retry once rather than persisting an unusable brief.
        raw = _call_gemini(prompt)
        data = _parse_json(raw)
    if not data.get("category_verdicts"):
        raise RuntimeError(
            "Comparison brief LLM returned no category verdicts after retry"
        )
    return _build_brief(run_id, programs, data, known_urls=known_urls)


def _build_brief(run_id: str, programs: list[str], data: dict[str, Any], *, known_urls: set[str] | None = None) -> ComparisonBrief:
    _known = known_urls or set()
    category_verdicts = [
        CategoryVerdict(
            category=v.get("category", ""),
            label=v.get("label", ""),
            winner=v.get("winner", "Insufficient data"),
            insight=v.get("insight", ""),
            source_urls=_filter_invented_urls(v.get("source_urls") or [], _known) if _known else (v.get("source_urls") or []),
        )
        for v in (data.get("category_verdicts") or [])
    ]
    key_differentiators = [
        KeyDifferentiator(
            topic=d.get("topic", ""),
            insight=d.get("insight", ""),
            advantage=d.get("advantage", ""),
            source_urls=_filter_invented_urls(d.get("source_urls") or [], _known) if _known else (d.get("source_urls") or []),
            rejected_note=d.get("rejected_note") or None,
        )
        for d in (data.get("key_differentiators") or [])
    ]
    personas = [
        ProgramPersona(
            program=p.get("program", ""),
            best_for=p.get("best_for", ""),
        )
        for p in (data.get("personas") or [])
    ]
    strategic_profiles = [
        ProgramStrategicProfile(
            program=s.get("program", ""),
            advantages=[a for a in (s.get("advantages") or []) if isinstance(a, str)],
            gaps=[g for g in (s.get("gaps") or []) if isinstance(g, str)],
        )
        for s in (data.get("strategic_profiles") or [])
    ]
    differentiation_themes = [
        DifferentiationTheme(
            theme=t.get("theme", ""),
            summary=t.get("summary", ""),
            leader=t.get("leader") or None,
        )
        for t in (data.get("differentiation_themes") or [])
    ]
    return ComparisonBrief(
        brief_id=new_id("compbrief"),
        run_id=run_id,
        programs=programs,
        overall_winner=data.get("overall_winner") or None,
        executive_summary=data.get("executive_summary", ""),
        category_verdicts=category_verdicts,
        key_differentiators=key_differentiators,
        personas=personas,
        strategic_profiles=strategic_profiles,
        differentiation_themes=differentiation_themes,
        generated_at=now_iso(),
    )


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    # Strip markdown fences if the model added them despite instructions
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _call_gemini(prompt: str, max_retries: int = 2) -> str:
    provider = provider_for_stage("comparison_brief")
    raw = os.getenv("NARRATION_API_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()] or ([provider.api_key] if provider.api_key else [])
    if not keys:
        raise RuntimeError("Comparison brief: no API key configured. Set NARRATION_API_KEYS or NARRATION_API_KEY or GEMINI_API_KEY.")

    api_base = (provider.api_base or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    model = provider.resolved_model or "gemini-2.5-flash"
    url = f"{api_base}/models/{model}:generateContent"

    last_error: Exception | None = None
    key_idx = 0
    for attempt in range((max_retries + 1) * len(keys)):
        api_key = keys[key_idx % len(keys)]
        response = requests.post(
            url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 16384,
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            },
            timeout=120,
        )
        if response.status_code not in _TRANSIENT_STATUS_CODES:
            response.raise_for_status()
            payload = response.json()
            usage = payload.get("usageMetadata", {})
            ledger = cost_tracker.get_current_ledger()
            if ledger:
                ledger.record_gemini(
                    "comparison_brief",
                    int(usage.get("promptTokenCount") or 0),
                    int(usage.get("candidatesTokenCount") or 0),
                )
            return payload["candidates"][0]["content"]["parts"][0]["text"].strip()

        last_error = requests.HTTPError(
            f"Comparison brief LLM returned {response.status_code}",
            response=response,
        )
        if response.status_code == 429:
            key_idx += 1
        else:
            time.sleep(2 ** min(attempt, 4))

    raise last_error or RuntimeError("Comparison brief LLM request failed.")
