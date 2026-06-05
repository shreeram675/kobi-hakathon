"""Comparison logic for two completed program states."""

from __future__ import annotations

from schemas import Claim, ClaimStatus, ComparisonItem, ComparisonOutput


def compare_claim_sets(run_id: str, program_a: str, program_b: str, a_claims: list[Claim], b_claims: list[Claim]) -> ComparisonOutput:
    a_by_field = {claim.field_path: claim for claim in a_claims}
    b_by_field = {claim.field_path: claim for claim in b_claims}
    items: list[ComparisonItem] = []

    for field_path in sorted(set(a_by_field) | set(b_by_field)):
        a = a_by_field.get(field_path)
        b = b_by_field.get(field_path)
        if a is None:
            outcome = "missing_in_a"
            summary = f"{field_path} is present for {program_b} but missing for {program_a}."
            claim_ids = [b.claim_id] if b else []
        elif b is None:
            outcome = "missing_in_b"
            summary = f"{field_path} is present for {program_a} but missing for {program_b}."
            claim_ids = [a.claim_id]
        elif ClaimStatus.NOT_FOUND in {a.status, b.status}:
            outcome = "manual_review_needed"
            summary = f"{field_path} needs manual review before comparison."
            claim_ids = [a.claim_id, b.claim_id]
        elif ClaimStatus.NULL in {a.status, b.status}:
            outcome = "null"
            summary = f"{field_path} was not searched or is not applicable for at least one program."
            claim_ids = [a.claim_id, b.claim_id]
        elif a.value_json != b.value_json:
            outcome = "factual_mismatch"
            summary = f"{field_path} differs between the two programs."
            claim_ids = [a.claim_id, b.claim_id]
        else:
            outcome = "match"
            summary = f"{field_path} matches."
            claim_ids = [a.claim_id, b.claim_id]

        items.append(ComparisonItem(field_path=field_path, outcome=outcome, summary=summary, claim_ids=claim_ids))

    return ComparisonOutput(run_id=run_id, program_a=program_a, program_b=program_b, items=items)
