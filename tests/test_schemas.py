import pytest

from core.schemas import Claim, ClaimStatus, Volatility, build_initial_state


def test_supported_claim_requires_source_and_access_date():
    with pytest.raises(ValueError):
        Claim(
            run_id="run_test",
            field_path="program_basics.program_name",
            value_json="Marriott Bonvoy",
            status=ClaimStatus.SUPPORTED,
            confidence=0.95,
            volatility=Volatility.LOW,
        )


def test_initial_state_has_required_arcguide_keys():
    state = build_initial_state("Air India")

    for key in (
        "run_id",
        "mode",
        "user_input",
        "validation_messages",
        "validation_result",
        "program_identity",
        "query_generation_result",
        "search_queries",
        "retrieval_result",
        "retrieved_urls",
        "firecrawl_result",
        "scraped_blocks",
        "retrieved_pages",
        "sanitized_chunks",
        "extracted_claims",
        "conflicts",
        "adjudicated_claims",
        "schema_coverage",
        "data_quality",
        "final_brief",
        "comparison_output",
        "conversation_answer",
        "errors",
        "created_at",
        "updated_at",
    ):
        assert key in state
