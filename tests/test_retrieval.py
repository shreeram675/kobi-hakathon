from pipeline.stages.retrieval import canonicalize_url, retrieve_urls
from pipeline.stages.retrieval import TavilyRestClient
from core.schemas import SearchQuery
from unittest.mock import patch

import pytest
import requests


class FakeTavilyClient:
    def __init__(self):
        self.calls = []

    def search(self, query, max_results=5, days=None):  # noqa: unused-parameter
        self.calls.append((query, max_results))
        return [
            {
                "title": "Official",
                "url": "https://www.example.com/program?utm_source=x",
                "content": "Official page",
                "score": 0.82,
            },
            {
                "title": "Duplicate higher score",
                "url": "https://example.com/program/",
                "content": "Same page",
                "score": 0.91,
            },
            {
                "title": "Terms",
                "url": "https://example.com/terms",
                "content": "Terms",
                "score": 0.77,
            },
        ]


def test_retrieve_urls_requests_five_per_query_and_dedupes_urls():
    queries = [
        SearchQuery(query="Example Rewards terms", source_type="terms", external_query_id="Q01"),
        SearchQuery(query="Example Rewards valuation", source_type="valuation"),
    ]
    client = FakeTavilyClient()

    result = retrieve_urls(queries, client=client)

    assert client.calls == [("Example Rewards terms", 3), ("Example Rewards valuation", 3)]
    assert result.total_queries == 2
    assert result.raw_result_count == 6
    assert result.unique_result_count == 2
    assert result.urls[0].canonical_url == "https://example.com/program"
    assert result.urls[0].score == 0.91
    assert result.urls[0].external_query_id == "Q01"


def test_canonicalize_url_removes_tracking_and_www():
    assert (
        canonicalize_url("https://www.example.com/path/?utm_campaign=x&a=1#section")
        == "https://example.com/path?a=1"
    )


def test_tavily_client_reports_dns_or_network_failure(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test_key")
    client = TavilyRestClient(max_retries=1, retry_sleep_seconds=0)

    with patch("retrieval.requests.post", side_effect=requests.ConnectionError("dns failed")):
        with patch("retrieval.time.sleep"):
            with pytest.raises(RuntimeError, match="could not reach api.tavily.com"):
                client.search("Example Rewards terms")
