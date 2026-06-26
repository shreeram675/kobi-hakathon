import pytest

from firecrawl_scraper import FirecrawlRestClient, extract_content_blob, normalize_firecrawl_api_base, scrape_retrieved_urls
from schemas import RetrievedUrl


class FakeFirecrawlClient:
    def __init__(self):
        self.calls = []

    def scrape(self, url):
        self.calls.append(url)
        if "fail" in url:
            raise RuntimeError("blocked")
        return {
            "data": {
                "metadata": {"title": "Program page"},
                "markdown": "# Program page\n\nEarn 1 point per dollar.",
            }
        }


def retrieved(url):
    return RetrievedUrl(
        url=url,
        canonical_url=url,
        title="Title",
        score=0.9,
        query="Example Rewards terms",
        query_id="query_test",
        source_type="terms",
    )


def test_extract_content_blob_prefers_markdown():
    assert extract_content_blob({"markdown": "# Title", "html": "<h1>Title</h1>"}) == "# Title"


def test_scrape_retrieved_urls_returns_raw_content_per_url_with_failures():
    client = FakeFirecrawlClient()
    output = scrape_retrieved_urls(
        [retrieved("https://example.com/program"), retrieved("https://example.com/fail.pdf")],
        client=client,
    )

    assert client.calls == ["https://example.com/program", "https://example.com/fail.pdf"]
    assert output.total_urls == 2
    assert output.successful_scrapes == 1
    assert output.failed_scrapes == 1
    assert "Earn 1 point per dollar" in output.blocks[0].content
    assert output.blocks[1].content is None
    assert output.blocks[1].scrape_status == "failed"


def test_normalize_firecrawl_api_base_upgrades_v1_scrape_endpoint():
    assert (
        normalize_firecrawl_api_base("https://api.firecrawl.dev/v1/scrape")
        == "https://api.firecrawl.dev/v2/scrape"
    )


def test_firecrawl_402_reports_insufficient_credits(monkeypatch):
    class FakeProvider:
        api_base = "https://api.firecrawl.dev/v2/scrape"
        api_key = "fc-test"

    class FakeResponse:
        status_code = 402

        def raise_for_status(self):
            raise AssertionError("raise_for_status should not be reached for 402")

    monkeypatch.setattr("firecrawl_scraper.provider_for_stage", lambda stage: FakeProvider())
    monkeypatch.setattr("firecrawl_scraper.requests.post", lambda *args, **kwargs: FakeResponse())

    client = FirecrawlRestClient(api_key="fc-test", api_base="https://api.firecrawl.dev/v2/scrape")
    with pytest.raises(RuntimeError, match="Insufficient Credits"):
        client.scrape("https://example.com")
