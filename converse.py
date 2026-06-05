"""Question answering over stored claims only."""

from __future__ import annotations

from schemas import Claim, ClaimStatus, ConverseAnswer


def answer_from_claims(question: str, claims: list[Claim]) -> ConverseAnswer:
    normalized = question.lower()
    matching = [
        claim
        for claim in claims
        if claim.status == ClaimStatus.SUPPORTED and claim.field_path.split(".")[-1].replace("_", " ") in normalized
    ]
    if not matching:
        return ConverseAnswer(
            answer="not_found/manual_review_needed",
            status=ClaimStatus.NOT_FOUND,
            missing_field_paths=[],
        )

    claim = matching[0]
    return ConverseAnswer(
        answer=str(claim.value_json),
        status=ClaimStatus.SUPPORTED,
        cited_claim_ids=[claim.claim_id],
    )
