"""Firecrawl scraping that stores raw page/PDF content per URL."""

from __future__ import annotations

from typing import Any, Protocol

import requests

from providers import provider_for_stage
from schemas import FirecrawlScrapeOutput, RetrievedUrl, ScrapedUrlBlock


class FirecrawlClient(Protocol):
    def scrape(self, url: str) -> dict[str, Any]:
        """Return Firecrawl scrape payload for one URL."""


class FirecrawlRestClient:
    """Firecrawl scrape REST client."""

    def __init__(self) -> None:
        provider = provider_for_stage("retrieval_fetch")
        self.api_base = normalize_firecrawl_api_base(provider.api_base)
        self.api_key = provider.api_key

    def scrape(self, url: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("Firecrawl scraping is not configured. Set FIRECRAWL_API_KEY.")

        response = requests.post(
            self.api_base,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "url": url,
                "formats": ["markdown"],
                "parsers": ["pdf"],
                "onlyMainContent": True,
                "timeout": 60000,
            },
            timeout=90,
        )
        if response.status_code == 402:
            raise RuntimeError(
                "Firecrawl returned 402 Insufficient Credits. The API key is valid, "
                "but the Firecrawl account does not have enough credits for this scrape."
            )
        if response.status_code == 403:
            raise RuntimeError(
                f"Firecrawl returned 403 Forbidden for {self.api_base}. "
                "Check FIRECRAWL_API_KEY, plan access, and ensure FIRECRAWL_API_BASE uses /v2/scrape."
            )
        response.raise_for_status()
        return response.json()


def scrape_retrieved_urls(
    urls: list[RetrievedUrl],
    client: FirecrawlClient | None = None,
) -> FirecrawlScrapeOutput:
    firecrawl = client or FirecrawlRestClient()
    blocks: list[ScrapedUrlBlock] = []

    for retrieved in urls:
        try:
            payload = firecrawl.scrape(retrieved.url)
            blocks.append(parse_firecrawl_payload(retrieved, payload))
        except Exception as exc:
            blocks.append(
                ScrapedUrlBlock(
                    url=retrieved.url,
                    canonical_url=retrieved.canonical_url,
                    content=None,
                    scrape_status="failed",
                    error=str(exc),
                )
            )

    successful = sum(1 for block in blocks if block.scrape_status == "success" and block.content)
    return FirecrawlScrapeOutput(
        total_urls=len(urls),
        successful_scrapes=successful,
        failed_scrapes=len(blocks) - successful,
        blocks=blocks,
    )


def normalize_firecrawl_api_base(value: str | None) -> str:
    api_base = (value or "https://api.firecrawl.dev/v2/scrape").strip().rstrip("/")
    if api_base.endswith("/v1/scrape"):
        return api_base[: -len("/v1/scrape")] + "/v2/scrape"
    return api_base


def parse_firecrawl_payload(retrieved: RetrievedUrl, payload: dict[str, Any]) -> ScrapedUrlBlock:
    data = payload.get("data", payload)
    metadata = data.get("metadata") or {}
    content = extract_content_blob(data)
    return ScrapedUrlBlock(
        url=retrieved.url,
        canonical_url=retrieved.canonical_url,
        title=metadata.get("title") or retrieved.title,
        content=content,
        scrape_status="success" if content else "failed",
        error=None if content else "Firecrawl returned no markdown/content for this URL.",
    )


def extract_content_blob(data: dict[str, Any]) -> str | None:
    for key in ("markdown", "content", "text", "html", "rawHtml"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
