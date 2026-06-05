"""Claim extraction helpers.

The full LLM extraction stage will live here. The initial scaffold focuses on
evaluation-safe absent fields.
"""

from __future__ import annotations

from schemas import Claim, ClaimStatus, SCHEMA_FIELD_PATHS, volatility_for_field


def manual_review_claims_for_unsearched_fields(run_id: str, searched_field_paths: set[str]) -> list[Claim]:
    claims: list[Claim] = []
    for field_path in SCHEMA_FIELD_PATHS:
        if field_path in searched_field_paths:
            continue
        claims.append(
            Claim(
                run_id=run_id,
                field_path=field_path,
                value_json=None,
                status=ClaimStatus.NULL,
                confidence=0,
                volatility=volatility_for_field(field_path),
            )
        )
    return claims
