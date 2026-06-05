"""Narrator stage scaffold."""

from __future__ import annotations

from schemas import BriefOutput, Claim, ClaimStatus


def build_placeholder_brief(run_id: str, claims: list[Claim]) -> BriefOutput:
    supported = [claim for claim in claims if claim.status == ClaimStatus.SUPPORTED]
    text = (
        "Kobie has not generated the final analyst brief yet. "
        "The narrator requires verified, adjudicated claims with source attribution before writing."
    )
    return BriefOutput(
        run_id=run_id,
        brief_text=text,
        cited_claim_ids=[claim.claim_id for claim in supported],
        word_count=len(text.split()),
        entailment_passed=False,
        unsupported_sentences=[],
    )
