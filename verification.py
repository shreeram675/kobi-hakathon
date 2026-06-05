"""Confidence scoring, conflict detection, and adjudication."""

from __future__ import annotations

from collections import defaultdict

from schemas import Claim, ClaimStatus, ConflictRecord, Volatility


def confidence_score(recency: float, authority: float, corroboration: float, volatility: Volatility) -> float:
    if volatility == Volatility.HIGH:
        score = (0.50 * recency) + (0.25 * authority) + (0.25 * corroboration)
    else:
        score = (0.20 * recency) + (0.50 * authority) + (0.30 * corroboration)
    return max(0.0, min(1.0, round(score, 4)))


def exclude_unsupported(claims: list[Claim]) -> list[Claim]:
    return [claim for claim in claims if claim.status != ClaimStatus.REJECTED_UNSUPPORTED]


def detect_conflicts(run_id: str, claims: list[Claim]) -> list[ConflictRecord]:
    by_field: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        if claim.status in {ClaimStatus.SUPPORTED, ClaimStatus.CONFLICTING}:
            by_field[claim.field_path].append(claim)

    conflicts: list[ConflictRecord] = []
    for field_path, field_claims in by_field.items():
        values = {repr(claim.value_json) for claim in field_claims}
        if len(values) <= 1:
            continue
        sorted_claims = sorted(field_claims, key=lambda claim: claim.confidence, reverse=True)
        gap = sorted_claims[0].confidence - sorted_claims[1].confidence
        conflicts.append(
            ConflictRecord(
                run_id=run_id,
                field_path=field_path,
                claim_ids=[claim.claim_id for claim in field_claims],
                score_gap=round(gap, 4),
                resolution_status="auto_resolved" if gap > 0.20 else "debate_required",
                judge_reason="Claims disagree for the same field_path.",
            )
        )
    return conflicts
