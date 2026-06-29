from unittest.mock import Mock, patch

import pytest
import requests

from pipeline.stages.query_generator import (
    GeminiQueryGeneratorClient,
    QUERY_GENERATOR_SYSTEM_PROMPT,
    build_local_query_generation_output,
    generate_queries,
    parse_query_generation_output,
)
from core.schemas import ProgramIdentity


class FakeQueryClient:
    def complete_json(self, prompt):
        self.prompt = prompt
        return {
            "detected_category": "Other",
            "resolved_corporate_parent": "American Express",
            "geography": "US",
            "query_strategy_summary": "Prioritize valuation, partners, and sentiment.",
            "priority_fields": ["Point Value", "Transfer Partners"],
            "estimated_web_coverage": 0.8,
            "field_query_map": {"point_value": ["Q01"], "member_sentiment": ["Q02"]},
            "queries": [
                {
                    "query_id": "Q01",
                    "query": "American Express Membership Rewards transfer partners redemption value",
                    "intent": "partnership valuation",
                    "target_fields": ["point_value", "partnerships"],
                    "source_type": "partners",
                },
                "American Express Membership Rewards Reddit complaints app rating",
            ],
        }


class RateLimitedQueryClient:
    def complete_json(self, prompt):
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError(
            "Gemini query generator is temporarily unavailable (429) for model gemini-2.5-flash.",
            response=response,
        )


def test_generate_queries_uses_validated_identity():
    identity = ProgramIdentity(
        raw_input="american express",
        program_name="American Express Membership Rewards",
        brand="American Express",
        domain="Banking/Credit Card",
        country_or_region="United States",
        confidence=0.95,
    )

    client = FakeQueryClient()
    result = generate_queries(identity, client=client)

    assert "American Express Membership Rewards" in client.prompt
    assert '"domain": "Banking/Credit Card"' in client.prompt
    assert result.detected_category == "Banking/Credit Card"
    assert result.resolved_corporate_parent == "American Express"
    assert result.field_query_map["point_value"] == [result.queries[0].query_id]
    assert len(result.queries) == 2
    assert result.queries[0].query_id.startswith("query_")
    assert result.queries[0].external_query_id == "Q01"
    assert result.queries[0].target_fields == ["point_value", "partnerships"]
    assert result.queries[1].source_type == "app_reviews"


def test_generate_queries_uses_local_fallback_for_gemini_429(monkeypatch):
    monkeypatch.delenv("QUERY_GENERATOR_LOCAL_FALLBACK", raising=False)
    monkeypatch.setenv("QUERY_GENERATOR_GROQ_API_KEYS", "")
    identity = ProgramIdentity(
        raw_input="Air India",
        program_name="Air India Maharaja Club",
        brand="Air India",
        domain="Airline",
        country_or_region="India",
        confidence=0.95,
    )

    result = generate_queries(identity, client=RateLimitedQueryClient())

    assert result.detected_category == "Airline"
    assert "Gemini returned 429" in result.query_strategy_summary
    assert len(result.queries) >= 9
    assert result.field_query_map
    assert any(query.source_type == "forums" for query in result.queries)
    assert any("competitive_position" in query.target_fields for query in result.queries)


def test_local_query_fallback_keeps_queries_concise():
    identity = ProgramIdentity(
        raw_input="Amex",
        program_name="American Express Membership Rewards",
        brand="American Express",
        domain="Banking/Credit Card",
        country_or_region="United States",
        confidence=0.95,
    )

    result = build_local_query_generation_output(identity, reason="Gemini returned 429")

    assert 9 <= len(result.queries) <= 15
    assert all(len(query.query.split()) <= 10 for query in result.queries)
    assert any("lounge_access" in query.target_fields for query in result.queries)
    assert not any(q.source_type == "app_reviews" for q in result.queries)


def test_query_generator_prompt_contains_strict_query_laws():
    assert "domain" in QUERY_GENERATOR_SYSTEM_PROMPT  # domain override rule must be present
    assert "10 words" in QUERY_GENERATOR_SYSTEM_PROMPT
    assert "reddit.com" in QUERY_GENERATOR_SYSTEM_PROMPT  # blocked domain must be listed
    assert "field_query_map" in QUERY_GENERATOR_SYSTEM_PROMPT
    assert '"queries": [' in QUERY_GENERATOR_SYSTEM_PROMPT


def test_validated_domain_overrides_gemini_other_category():
    identity = ProgramIdentity(
        raw_input="Marriott",
        program_name="Marriott Bonvoy",
        brand="Marriott",
        domain="Hotel",
        country_or_region="Global",
        confidence=0.95,
    )

    result = parse_query_generation_output(
        {
            "detected_category": "Other",
            "query_strategy_summary": "Test",
            "priority_fields": [],
            "field_query_map": {"tier_structure": ["Q01"]},
            "queries": [{"query_id": "Q01", "query": "Marriott Bonvoy elite nights", "source_type": "official"}],
        },
        identity=identity,
    )

    assert result.detected_category == "Hotel"


def test_parse_query_generation_output_limits_to_15_queries():
    result = parse_query_generation_output(
        {
            "detected_category": "Retail",
            "query_strategy_summary": "Test",
            "priority_fields": [],
            "queries": [f"query {index}" for index in range(20)],
        }
    )

    assert len(result.queries) == 15


def test_gemini_client_retries_transient_503(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    monkeypatch.setenv("GEMINI_API_BASE", "https://example.test/v1beta")
    monkeypatch.setenv("QUERY_GENERATOR_MODEL", "gemini-2.5-flash")

    unavailable = Mock(status_code=503)
    ok = Mock(status_code=200)
    ok.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": '{"detected_category":"Airline","query_strategy_summary":"ok","priority_fields":[],"queries":[]}'
                        }
                    ]
                }
            }
        ]
    }

    with patch("query_generator.requests.post", side_effect=[unavailable, ok]) as post:
        with patch("query_generator.time.sleep"):
            client = GeminiQueryGeneratorClient(max_retries=1, retry_sleep_seconds=0)
            result = client.complete_json("prompt")

    assert post.call_count == 2
    assert result["detected_category"] == "Airline"


def test_gemini_client_falls_back_to_lite_model_after_503(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    monkeypatch.setenv("GEMINI_API_BASE", "https://example.test/v1beta")
    monkeypatch.setenv("QUERY_GENERATOR_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("QUERY_GENERATOR_FALLBACK_MODELS", "gemini-2.5-flash-lite")

    unavailable = Mock(status_code=503)
    ok = Mock(status_code=200)
    ok.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": '{"detected_category":"Hotel","query_strategy_summary":"ok","priority_fields":[],"queries":[]}'
                        }
                    ]
                }
            }
        ]
    }

    with patch("query_generator.requests.post", side_effect=[unavailable, ok]) as post:
        with patch("query_generator.time.sleep"):
            client = GeminiQueryGeneratorClient(max_retries=0, retry_sleep_seconds=0)
            result = client.complete_json("prompt")

    assert post.call_count == 2
    assert "/models/gemini-2.5-flash:generateContent" in post.call_args_list[0].args[0]
    assert "/models/gemini-2.5-flash-lite:generateContent" in post.call_args_list[1].args[0]
    assert result["detected_category"] == "Hotel"


def test_gemini_client_reports_transient_failure_after_retries(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    monkeypatch.setenv("QUERY_GENERATOR_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("QUERY_GENERATOR_FALLBACK_MODELS", "")
    unavailable = Mock(status_code=503)

    with patch("query_generator.requests.post", return_value=unavailable):
        with patch("query_generator.time.sleep"):
            client = GeminiQueryGeneratorClient(max_retries=1, retry_sleep_seconds=0)
            with pytest.raises(requests.HTTPError, match="temporarily unavailable"):
                client.complete_json("prompt")
