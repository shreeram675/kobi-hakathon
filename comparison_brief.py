"""Generates a structured competitive comparison brief from multiple program field reports."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

import cost_tracker
from providers import provider_for_stage
from schemas import (
    CategoryVerdict,
    ComparisonBrief,
    FieldReport,
    KeyDifferentiator,
    ProgramPersona,
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
  "executive_summary": "<3-4 sentences: what this comparison reveals, who leads and why, biggest tension>",
  "category_verdicts": [
    {{
      "category": "<category key from list below>",
      "label": "<human-readable label>",
      "winner": "<program name, 'Tie', or 'Insufficient data'>",
      "insight": "<1-2 sentences citing actual values from the data, e.g. '10 pts/$ vs 5 miles/$'>"
    }}
  ],
  "key_differentiators": [
    {{
      "topic": "<short topic name>",
      "insight": "<what differs and why it matters to a member — be specific with numbers>",
      "advantage": "<program name that wins on this dimension>"
    }}
  ],
  "personas": [
    {{
      "program": "<program name>",
      "best_for": "<the specific type of traveller/consumer who gets the most value here>"
    }}
  ]
}}

RULES:
- category_verdicts must cover all 8 categories in this order: {category_keys}
- key_differentiators: pick the 3-5 most impactful differences only
- personas: one entry per program
- If a category has no data for any program, set winner to "Insufficient data" and insight to "No data extracted."
- overall_winner must be null if the margin is not meaningful or data is sparse
- Cite actual extracted values in insights (e.g. "24-month expiry vs 12-month expiry")
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
        line = f"    {field_label}: {entry.value} (conf={conf_label}){flag}"
        by_section.setdefault(section, []).append(line)

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

    raw = _call_gemini(prompt)
    data = _parse_json(raw)
    return _build_brief(run_id, programs, data)


def _build_brief(run_id: str, programs: list[str], data: dict[str, Any]) -> ComparisonBrief:
    category_verdicts = [
        CategoryVerdict(
            category=v.get("category", ""),
            label=v.get("label", ""),
            winner=v.get("winner", "Insufficient data"),
            insight=v.get("insight", ""),
        )
        for v in (data.get("category_verdicts") or [])
    ]
    key_differentiators = [
        KeyDifferentiator(
            topic=d.get("topic", ""),
            insight=d.get("insight", ""),
            advantage=d.get("advantage", ""),
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
    return ComparisonBrief(
        brief_id=new_id("compbrief"),
        run_id=run_id,
        programs=programs,
        overall_winner=data.get("overall_winner") or None,
        executive_summary=data.get("executive_summary", ""),
        category_verdicts=category_verdicts,
        key_differentiators=key_differentiators,
        personas=personas,
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
                    "maxOutputTokens": 4096,
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
