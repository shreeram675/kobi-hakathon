from unittest.mock import Mock, patch

import pytest
import requests

from query_generator import GeminiQueryGeneratorClient, generate_queries, parse_query_generation_output
from schemas import ProgramIdentity


class FakeQueryClient:
    def complete_json(self, prompt):
        self.prompt = prompt
        return {
            "detected_category": "Banking/Credit Card",
            "query_strategy_summary": "Prioritize valuation, partners, and sentiment.",
            "priority_fields": ["Point Value", "Transfer Partners"],
            "queries": [
                {
                    "query": "American Express Membership Rewards transfer partners redemption value",
                    "source_type": "partners",
                },
                "American Express Membership Rewards Reddit complaints app rating",
            ],
        }


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
    assert result.detected_category == "Banking/Credit Card"
    assert len(result.queries) == 2
    assert result.queries[1].source_type == "app_reviews"


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


def test_gemini_client_reports_transient_failure_after_retries(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    unavailable = Mock(status_code=503)

    with patch("query_generator.requests.post", return_value=unavailable):
        with patch("query_generator.time.sleep"):
            client = GeminiQueryGeneratorClient(max_retries=1, retry_sleep_seconds=0)
            with pytest.raises(requests.HTTPError, match="temporarily unavailable"):
                client.complete_json("prompt")
