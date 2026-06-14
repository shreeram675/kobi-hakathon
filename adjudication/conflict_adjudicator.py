"""Conflict adjudicator node: detect disagreeing claims and resolve them.

Runs after extraction/normalization. Conflicts where the confidence gap is
decisive (> 0.20) auto-resolve to the stronger claim; close calls go through
the 5-step adversarial debate engine. The logic is program-agnostic — every
value, source, and date comes from the pipeline state, never from the model.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, datetime
import json
from typing import Any

from schemas import AgentState, FieldReport, NormalizedObjectPacket, RawDocument, new_id, now_iso
from adjudication.debate_engine import run_debate


AUTO_RESOLVE_SCORE_GAP = 0.20
FLAG_CONFIDENCE = 0.40
FLAG_TEXT = "CONFLICTING SOURCES — verify manually"

# Universal volatility classification by field-path suffix, falling back to
# the section. Matches the ArcGuide AG-8 volatility split.
HIGH_VOLATILITY_FIELD_NAMES = frozenset(
    {
        "earn_rate_base",
        "base_earn_rate",
        "earn_rate_unit",
        "tier_thresholds",
        "redemption_value",
        "redemption_thresholds",
        "point_value_cpp",
        "cpp",
        "app_ratings",
        "ratings",
        "recent_changes_last_6_months",
    }
)
LOW_VOLATILITY_FIELD_NAMES = frozenset(
    {
        "program_name",
        "program_type",
        "founding_year",
        "tier_names",
        "brand",
        "industry",
        "geography",
    }
)
HIGH_VOLATILITY_SECTIONS = frozenset(
    {"earn_mechanics", "burn_mechanics", "partnerships", "digital_experience", "member_sentiment"}
)

# Map pipeline source_type vocabulary (current and legacy) to debate authority tiers.
SOURCE_TYPE_TO_AUTHORITY = {
    "official": "official",
    "terms": "official",
    "faq": "official",
    "partners": "official",
    "financial": "major_publication",
    "news": "news",
    "review": "aggregator",
    "valuation": "aggregator",
    "app_reviews": "aggregator",
    "competitors": "aggregator",
    "forum": "forum",
    "forums": "forum",
}
DEFAULT_AUTHORITY = "aggregator"


def adjudicator_node(state: AgentState) -> AgentState:
    """Resolve every conflict in state into state["adjudicated"]."""

    run_id = state.get("run_id") or ""
    conflicts = [item for item in state.get("conflicts") or [] if isinstance(item, dict) and "claim_a" in item]
    if not conflicts:
        conflicts = detect_conflicts_from_packets(
            state.get("normalized_packets", []),
            state.get("raw_documents", []),
        )

    adjudicated: list[dict[str, Any]] = []
    human_review_items: list[dict[str, Any]] = list(state.get("human_review_queue") or [])
    debated: list[dict[str, Any]] = []
    for conflict in conflicts:
        confidence_a = float(conflict["claim_a"].get("confidence") or 0.0)
        confidence_b = float(conflict["claim_b"].get("confidence") or 0.0)
        score_gap = abs(confidence_a - confidence_b)
        if score_gap > AUTO_RESOLVE_SCORE_GAP:
            winner = "A" if confidence_a >= confidence_b else "B"
            claim = conflict["claim_a"] if winner == "A" else conflict["claim_b"]
            adjudicated.append(
                {
                    "field_name": conflict["field_name"],
                    "winner": winner,
                    "value": str(claim["value"]),
                    "source_url": claim.get("source_url"),
                    "confidence": float(claim.get("confidence") or 0.0),
                    "resolution": "auto",
                    "deciding_factor": "confidence_gap",
                    "reasoning": f"Score gap {score_gap:.2f} > {AUTO_RESOLVE_SCORE_GAP} auto-resolved without debate.",
                }
            )
        else:
            debated.append(conflict)

    if debated:
        results = asyncio.run(_run_debates(debated))
        for conflict, result in zip(debated, results):
            entries = _entries_from_debate(conflict, result)
            adjudicated.extend(entries)
            if result.get("winner") == "FLAG":
                human_review_items.append(_build_human_review_item(conflict, result, run_id))

    updated: AgentState = {
        **state,
        "conflicts": conflicts,
        "adjudicated": adjudicated,
        "human_review_queue": human_review_items,
        "updated_at": now_iso(),
    }
    field_report = state.get("field_report")
    if field_report is not None and adjudicated:
        updated["field_report"] = apply_adjudication_to_field_report(field_report, adjudicated)
    return updated


def _build_human_review_item(
    conflict: dict[str, Any], debate_result: dict[str, Any], run_id: str
) -> dict[str, Any]:
    """Build a structured human-review queue entry when the judge returns FLAG."""
    return {
        "review_id": new_id("review"),
        "run_id": run_id,
        "field_name": str(conflict["field_name"]),
        "claim_a": conflict["claim_a"],
        "claim_b": conflict["claim_b"],
        "volatility": conflict.get("volatility"),
        "debate_transcript": {
            "argument_a": debate_result.get("argument_a", ""),
            "argument_b": debate_result.get("argument_b", ""),
            "rebuttal_a": debate_result.get("rebuttal_a", ""),
            "rebuttal_b": debate_result.get("rebuttal_b", ""),
        },
        "judge_verdict": {
            "deciding_factor": debate_result.get("deciding_factor"),
            "reasoning": debate_result.get("reasoning"),
            "rebuttal_assessment": debate_result.get("rebuttal_assessment"),
            "hallucination_detected": debate_result.get("hallucination_detected"),
        },
        "final_confidence": debate_result.get("final_confidence"),
        "flagged_at": now_iso(),
    }


async def _run_debates(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Reset the semaphore so it binds to the current event loop created by
    # asyncio.run() — avoids "bound to a different event loop" on repeated runs.
    import adjudication.debate_engine as _de
    _de._GROQ_SEMAPHORE = asyncio.Semaphore(3)
    # Debates run concurrently; the semaphore caps Groq calls at 3.
    return list(await asyncio.gather(*(run_debate(conflict, use_rebuttal=True) for conflict in conflicts)))


def _entries_from_debate(conflict: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    if result["winner"] == "FLAG":
        # Use the debate's final_confidence (judge may have adjusted it) rather than
        # the hard-coded constant, falling back to FLAG_CONFIDENCE if absent.
        flag_confidence = float(result.get("final_confidence") or FLAG_CONFIDENCE)
        return [
            {
                "field_name": conflict["field_name"],
                "winner": "FLAG",
                "value": str(claim["value"]),
                "source_url": claim.get("source_url"),
                "confidence": flag_confidence,
                "resolution": "flag",
                "deciding_factor": result.get("deciding_factor", "unresolvable"),
                "reasoning": result.get("reasoning", ""),
                "flag": FLAG_TEXT,
                "debate": result,
            }
            for claim in (conflict["claim_a"], conflict["claim_b"])
        ]

    claim = conflict["claim_a"] if result["winner"] == "A" else conflict["claim_b"]
    return [
        {
            "field_name": conflict["field_name"],
            "winner": result["winner"],
            "value": result.get("winning_value") or str(claim["value"]),
            "source_url": claim.get("source_url"),
            "confidence": float(result.get("final_confidence") or 0.0),
            "resolution": "debate",
            "deciding_factor": result.get("deciding_factor", ""),
            "reasoning": result.get("reasoning", ""),
            "debate": result,
        }
    ]


def detect_conflicts_from_packets(
    packets: list[NormalizedObjectPacket],
    raw_documents: list[RawDocument],
) -> list[dict[str, Any]]:
    """Find fields where two sources disagree and build debate-ready conflicts.

    Groups EXTRACTED values per field path across all packets; when at least
    two distinct values are backed by distinct sources, the two strongest
    value groups become claim_a and claim_b.
    """

    documents_by_url = {document.url: document for document in raw_documents}
    groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    for packet in packets:
        for field_name, field in packet.fields.items():
            # Include EXTRACTED fields and AMBIGUOUS fields that still carry a value.
            # AMBIGUOUS-with-value arises when the normalizer validation flags a suspicious
            # extraction (e.g. a room count in membership_count). Including it here lets the
            # auto-resolve path pick the correct EXTRACTED value from another source
            # (confidence gap > 0.20 is guaranteed when one side is 0.0).
            # AMBIGUOUS fields with value=None carry no evidence and are always skipped.
            if field.value is None or not field.source_url:
                continue
            if field.status not in ("EXTRACTED", "AMBIGUOUS"):
                continue
            value_key = json.dumps(field.value, sort_keys=True, ensure_ascii=True, default=str)
            group = groups[field_name].setdefault(
                value_key,
                {"value": field.value, "source_urls": set(), "confidence": 0.0},
            )
            group["source_urls"].add(field.source_url)
            # AMBIGUOUS confidence is kept at 0.0 so EXTRACTED values always win auto-resolve.
            if field.status == "EXTRACTED":
                group["confidence"] = max(group["confidence"], field.confidence or 0.0)

    conflicts: list[dict[str, Any]] = []
    for field_name, value_groups in groups.items():
        if len(value_groups) < 2:
            continue
        ranked = sorted(
            value_groups.values(),
            key=lambda group: (len(group["source_urls"]), group["confidence"]),
            reverse=True,
        )
        claim_a = _claim_from_group(ranked[0], documents_by_url)
        claim_b = _claim_from_group(ranked[1], documents_by_url)
        if claim_a["source_url"] == claim_b["source_url"]:
            continue
        conflicts.append(
            {
                "field_name": field_name,
                "volatility": classify_volatility(field_name),
                "claim_a": claim_a,
                "claim_b": claim_b,
            }
        )
    return conflicts


def classify_volatility(field_name: str) -> str:
    suffix = field_name.split(".")[-1].lower()
    if suffix in HIGH_VOLATILITY_FIELD_NAMES:
        return "HIGH"
    if suffix in LOW_VOLATILITY_FIELD_NAMES:
        return "LOW"
    section = field_name.split(".")[0].lower()
    return "HIGH" if section in HIGH_VOLATILITY_SECTIONS else "LOW"


def apply_adjudication_to_field_report(
    report: FieldReport,
    adjudicated: list[dict[str, Any]],
) -> FieldReport:
    """Reflect adjudication outcomes in the final field report."""

    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in adjudicated:
        by_field[str(entry["field_name"])].append(entry)

    entries = []
    for entry in report.entries:
        resolutions = by_field.get(entry.field_path)
        if not resolutions:
            entries.append(entry)
            continue
        if any(resolution["resolution"] == "flag" for resolution in resolutions):
            entries.append(
                entry.model_copy(update={"status": "flagged", "confidence": FLAG_CONFIDENCE})
            )
            continue
        resolution = resolutions[0]
        # Promote status to "extracted" — debate produced a clear winner, regardless of
        # what the entry's pre-adjudication status was (extracted or ambiguous).
        entries.append(
            entry.model_copy(
                update={
                    "status": "extracted",
                    "value": resolution["value"],
                    "source_urls": [resolution["source_url"]] if resolution.get("source_url") else entry.source_urls,
                    "confidence": resolution["confidence"],
                }
            )
        )

    return report.model_copy(
        update={
            "entries": entries,
            "extracted_count": sum(1 for item in entries if item.status == "extracted"),
            "ambiguous_count": sum(1 for item in entries if item.status == "ambiguous"),
            "not_found_count": sum(1 for item in entries if item.status == "not_found"),
            "flagged_count": sum(1 for item in entries if item.status == "flagged"),
        }
    )


def _claim_from_group(group: dict[str, Any], documents_by_url: dict[str, RawDocument]) -> dict[str, Any]:
    source_url = _best_source_url(group["source_urls"], documents_by_url)
    document = documents_by_url.get(source_url)
    return {
        "value": str(group["value"]),
        "source_url": source_url,
        "date": _document_date(document),
        "authority": _document_authority(document),
        "corroboration": len(group["source_urls"]),
        "confidence": round(float(group["confidence"]), 4),
    }


def _best_source_url(source_urls: set[str], documents_by_url: dict[str, RawDocument]) -> str:
    def authority_score(url: str) -> float:
        document = documents_by_url.get(url)
        return document.source_authority or 0.0 if document else 0.0

    return max(sorted(source_urls), key=authority_score)


def _document_date(document: RawDocument | None) -> date:
    if document and document.retrieved_at:
        try:
            return datetime.fromisoformat(document.retrieved_at).date()
        except ValueError:
            pass
    return date.today()


def _document_authority(document: RawDocument | None) -> str:
    if document is None:
        return DEFAULT_AUTHORITY
    source_type = str(document.metadata.get("source_type") or "").strip().lower()
    return SOURCE_TYPE_TO_AUTHORITY.get(source_type, DEFAULT_AUTHORITY)
