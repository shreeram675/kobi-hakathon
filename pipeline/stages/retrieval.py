"""Tavily URL retrieval and deduplication."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import time
from typing import Any, Protocol

import requests

from core import cost_tracker
from core.providers import provider_for_stage
from core.schemas import RetrievalOutput, RetrievedUrl, SearchQuery


RESULTS_PER_QUERY = 3

# Source types whose content rarely changes — official program pages, T&Cs, FAQs.
# For all other source types, Tavily will be restricted to the past year to avoid
# returning stale SEO articles that predate program changes.
_STATIC_SOURCE_TYPES = frozenset({"official", "terms", "faq"})
_RECENCY_DAYS = 365


class TavilyClient(Protocol):
    def search(self, query: str, max_results: int = RESULTS_PER_QUERY, days: int | None = None) -> list[dict[str, Any]]:
        """Return Tavily result dictionaries for one query."""


class TavilyRestClient:
    """Tavily Search API REST client."""

    def __init__(self, max_retries: int = 2, retry_sleep_seconds: float = 1.0) -> None:
        import os
        provider = provider_for_stage("retrieval_search")
        self.api_base = provider.api_base or "https://api.tavily.com/search"
        self.retry_sleep_seconds = retry_sleep_seconds

        # Support multiple keys via TAVILY_API_KEYS (comma-separated) for rotation on 432.
        multi = os.getenv("TAVILY_API_KEYS", "")
        self._api_keys: list[str] = [k.strip() for k in multi.split(",") if k.strip()]
        if not self._api_keys and provider.api_key:
            self._api_keys = [provider.api_key]
        self._key_index = 0
        self.max_retries = max_retries + len(self._api_keys)  # extra attempts for key rotation

    @property
    def api_key(self) -> str | None:
        return self._api_keys[self._key_index] if self._api_keys else None

    def _rotate_key(self) -> bool:
        """Advance to the next API key. Returns True if a new key is available."""
        if self._key_index + 1 < len(self._api_keys):
            self._key_index += 1
            return True
        return False

    def search(self, query: str, max_results: int = RESULTS_PER_QUERY, days: int | None = None) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("Tavily retrieval is not configured. Set TAVILY_API_KEY.")

        response = self._post_with_retries(query=query, max_results=max_results, days=days)
        response.raise_for_status()
        payload = response.json()
        return payload.get("results", [])

    def _post_with_retries(self, query: str, max_results: int, days: int | None = None) -> requests.Response:
        last_error: requests.RequestException | None = None
        body: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_answer": False,
            "include_raw_content": False,
        }
        if days is not None:
            body["days"] = days
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    self.api_base,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=45,
                )
                # 432 = credits exhausted for this dev key; try the next one.
                if response.status_code == 432 and self._rotate_key():
                    continue
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep_seconds * (attempt + 1))

        raise RuntimeError(
            "Tavily retrieval could not reach api.tavily.com. Check internet access, "
            "DNS resolution, firewall/VPN settings, and TAVILY_API_BASE."
        ) from last_error


def retrieve_urls(
    queries: list[SearchQuery],
    client: TavilyClient | None = None,
    results_per_query: int = RESULTS_PER_QUERY,
) -> RetrievalOutput:
    tavily = client or TavilyRestClient()
    deduped: dict[str, RetrievedUrl] = {}
    raw_count = 0

    ledger = cost_tracker.get_current_ledger()
    for search_query in queries:
        days = None if search_query.source_type in _STATIC_SOURCE_TYPES else _RECENCY_DAYS
        results = tavily.search(search_query.query, max_results=results_per_query, days=days)
        if ledger:
            ledger.record_tavily(1)
        raw_count += len(results)
        for result in results[:results_per_query]:
            url = str(result.get("url") or "").strip()
            if not url:
                continue
            canonical = canonicalize_url(url)
            score = normalize_score(result.get("score"))
            candidate = RetrievedUrl(
                url=url,
                canonical_url=canonical,
                title=result.get("title"),
                score=score,
                query=search_query.query,
                query_id=search_query.query_id,
                external_query_id=search_query.external_query_id,
                source_type=search_query.source_type,
            )

            existing = deduped.get(canonical)
            if existing is None or candidate.score > existing.score:
                deduped[canonical] = candidate

    urls = sorted(deduped.values(), key=lambda item: item.score, reverse=True)
    return RetrievalOutput(
        total_queries=len(queries),
        requested_results_per_query=results_per_query,
        raw_result_count=raw_count,
        unique_result_count=len(urls),
        urls=urls,
    )


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parsed.path.rstrip("/") or "/"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))
