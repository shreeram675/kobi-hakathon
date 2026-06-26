"""Firecrawl scraping that stores raw page/PDF content per URL."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Protocol

import requests

import cost_tracker
from providers import provider_for_stage
from schemas import FirecrawlScrapeOutput, RetrievedUrl, ScrapedUrlBlock


class ForbiddenError(RuntimeError):
    """Raised when Firecrawl returns 403 Forbidden for a URL."""


class FirecrawlClient(Protocol):
    def scrape(self, url: str) -> dict[str, Any]:
        """Return Firecrawl scrape payload for one URL."""


class _FirecrawlKeyPool:
    """Round-robin selector across FIRECRAWL_API_KEYS (comma-separated).

    Falls back to FIRECRAWL_API_KEY then the provider key for single-key setups.
    """

    def __init__(self) -> None:
        keys = self._load_keys()
        if not keys:
            raise RuntimeError("Firecrawl scraping is not configured. Set FIRECRAWL_API_KEY.")
        self._keys = keys
        self._index = 0
        self._lock = threading.Lock()

    @staticmethod
    def _load_keys() -> list[str]:
        multi = os.getenv("FIRECRAWL_API_KEYS", "")
        keys = [k.strip() for k in multi.split(",") if k.strip()]
        if not keys:
            provider = provider_for_stage("retrieval_fetch")
            if provider.api_key:
                keys = [provider.api_key]
        return keys

    def current(self) -> str:
        with self._lock:
            return self._keys[self._index % len(self._keys)]

    def advance(self) -> str:
        with self._lock:
            self._index = (self._index + 1) % len(self._keys)
            return self._keys[self._index]

    def __len__(self) -> int:
        return len(self._keys)

    def all_keys(self) -> list[str]:
        return list(self._keys)


class FirecrawlRestClient:
    """Firecrawl scrape REST client for a single API key."""

    def __init__(self, api_key: str, api_base: str) -> None:
        self.api_base = api_base
        self.api_key = api_key

    def scrape(self, url: str) -> dict[str, Any]:
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
            raise ForbiddenError(
                f"Firecrawl returned 403 Forbidden for {self.api_base}. "
                "Check FIRECRAWL_API_KEY, plan access, and ensure FIRECRAWL_API_BASE uses /v2/scrape."
            )
        response.raise_for_status()
        return response.json()


def _scrape_one(retrieved: RetrievedUrl, client: FirecrawlClient) -> ScrapedUrlBlock:
    try:
        payload = client.scrape(retrieved.url)
        ledger = cost_tracker.get_current_ledger()
        if ledger:
            ledger.record_firecrawl(1)
        return parse_firecrawl_payload(retrieved, payload)
    except ForbiddenError as exc:
        return ScrapedUrlBlock(
            url=retrieved.url,
            canonical_url=retrieved.canonical_url,
            content=None,
            scrape_status="forbidden",
            error=str(exc),
        )
    except Exception as exc:
        return ScrapedUrlBlock(
            url=retrieved.url,
            canonical_url=retrieved.canonical_url,
            content=None,
            scrape_status="failed",
            error=str(exc),
        )


def scrape_retrieved_urls(
    urls: list[RetrievedUrl],
    client: FirecrawlClient | None = None,
    on_progress: "Callable[[list[ScrapedUrlBlock], int], None] | None" = None,
) -> FirecrawlScrapeOutput:
    if not urls:
        return FirecrawlScrapeOutput(total_urls=0, successful_scrapes=0, failed_scrapes=0, blocks=[])

    if client is not None:
        # Test/override path: single client, sequential
        blocks: list[ScrapedUrlBlock] = []
        for r in urls:
            blocks.append(_scrape_one(r, client))
            if on_progress:
                on_progress(list(blocks), len(urls))
    else:
        blocks = _scrape_with_pool(urls, on_progress=on_progress)

    successful = sum(1 for b in blocks if b.scrape_status == "success" and b.content)
    return FirecrawlScrapeOutput(
        total_urls=len(urls),
        successful_scrapes=successful,
        failed_scrapes=len(blocks) - successful,
        blocks=blocks,
    )


def _scrape_with_pool(
    urls: list[RetrievedUrl],
    on_progress: "Callable[[list[ScrapedUrlBlock], int], None] | None" = None,
) -> list[ScrapedUrlBlock]:
    """Distribute URLs across all configured Firecrawl keys and scrape in parallel."""
    pool = _FirecrawlKeyPool()
    api_base = normalize_firecrawl_api_base(
        provider_for_stage("retrieval_fetch").api_base
    )
    keys = pool.all_keys()
    n_keys = len(keys)

    # Round-robin assign: URL i → key i % n_keys, preserving original order via index
    buckets: list[list[tuple[int, RetrievedUrl]]] = [[] for _ in keys]
    for i, url in enumerate(urls):
        buckets[i % n_keys].append((i, url))

    results: dict[int, ScrapedUrlBlock] = {}
    progress_lock = threading.Lock()

    def scrape_bucket(key: str, bucket: list[tuple[int, RetrievedUrl]]) -> None:
        fc = FirecrawlRestClient(api_key=key, api_base=api_base)
        for idx, retrieved in bucket:
            block = _scrape_one(retrieved, fc)
            with progress_lock:
                results[idx] = block
                if on_progress:
                    completed = [results[i] for i in sorted(results.keys())]
                    on_progress(completed, len(urls))

    with ThreadPoolExecutor(max_workers=n_keys) as executor:
        futures = [
            executor.submit(scrape_bucket, keys[i], buckets[i])
            for i in range(n_keys)
            if buckets[i]
        ]
        for f in as_completed(futures):
            f.result()  # re-raise any unexpected exception

    return [results[i] for i in range(len(urls))]


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
        published_date=_extract_published_date(metadata),
        scrape_status="success" if content else "failed",
        error=None if content else "Firecrawl returned no markdown/content for this URL.",
    )


def _extract_published_date(metadata: dict[str, Any]) -> str | None:
    """Return the first publication date found in Firecrawl page metadata."""
    for key in ("publishedTime", "publishedDate", "datePublished", "date", "modifiedTime"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_content_blob(data: dict[str, Any]) -> str | None:
    for key in ("markdown", "content", "text", "html", "rawHtml"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
