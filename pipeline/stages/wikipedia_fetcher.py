"""Fetch Wikipedia company summary and inject it as a synthetic scraped block.

Bypasses Tavily + Firecrawl entirely. Wikipedia's REST API is free, has no
rate limit for occasional queries, and reliably returns structured JSON for
any publicly traded or well-known brand.

Result: a ScrapedUrlBlock whose content goes through the normal
chunking → Gemini extraction pipeline, so all relevant schema fields
(company description, membership scale hints, parent entity) are extracted
without hard-coding which fields to populate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

import requests

LOGGER = logging.getLogger(__name__)

_REST_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_SEARCH_API = "https://en.wikipedia.org/w/api.php"
_HEADERS = {"User-Agent": "KobieResearchBot/1.0 (loyalty-program-research)"}
_TIMEOUT = 8

# Suffixes that make a program name differ from the parent brand name on Wikipedia
_PROGRAM_NOISE = (
    " rewards", " loyalty", " club", " plus", " points", " miles",
    " perks", " advantage", " frequent flyer", " frequent guest",
    " elite", " program", " membership",
)


@dataclass
class WikipediaResult:
    title: str
    url: str
    extract: str
    description: str | None


def fetch_wikipedia_summary(brand: str, program_name: str) -> WikipediaResult | None:
    """Return a WikipediaResult or None if no relevant article is found."""

    candidates = _build_candidates(brand, program_name)
    for candidate in candidates:
        result = _try_summary(candidate)
        if result and _is_relevant(result, brand, program_name):
            LOGGER.debug("Wikipedia: found '%s' for brand='%s'", result.title, brand)
            return result

    # Last resort: Wikipedia search API
    return _search_fallback(brand, program_name)


def build_wikipedia_block(result: WikipediaResult) -> dict:
    """Return a ScrapedUrlBlock-shaped dict from a WikipediaResult."""

    content_lines = [
        f"# {result.title}",
        "",
        result.description or "",
        "",
        result.extract,
    ]
    content = "\n".join(line for line in content_lines if line is not None)

    return {
        "url": result.url,
        "canonical_url": result.url,
        "title": result.title,
        "content": content,
        "scrape_status": "success",
        "error": None,
        "published_date": None,
    }


# ── internals ────────────────────────────────────────────────────────────────

def _build_candidates(brand: str, program_name: str) -> list[str]:
    """Return Wikipedia article title candidates, most likely first."""
    candidates: list[str] = []

    # Try brand name directly
    candidates.append(brand)

    # Strip loyalty-specific noise to get parent brand
    base = program_name
    for noise in _PROGRAM_NOISE:
        if base.lower().endswith(noise):
            base = base[: -len(noise)].strip()
            break
    if base and base.lower() != brand.lower():
        candidates.append(base)

    return list(dict.fromkeys(candidates))  # deduplicate, preserve order


def _try_summary(title: str) -> WikipediaResult | None:
    url = _REST_API.format(title=quote(title.replace(" ", "_"), safe=""))
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        extract: str = data.get("extract", "").strip()
        if not extract:
            return None
        return WikipediaResult(
            title=data.get("title", title),
            url=data.get("content_urls", {}).get("desktop", {}).get("page", url),
            extract=extract,
            description=data.get("description"),
        )
    except Exception as exc:
        LOGGER.debug("Wikipedia REST API error for '%s': %s", title, exc)
        return None


def _search_fallback(brand: str, program_name: str) -> WikipediaResult | None:
    """Use the Wikipedia search API to find the most relevant article."""
    query = f"{brand} company"
    try:
        resp = requests.get(
            _SEARCH_API,
            params={"action": "query", "list": "search", "srsearch": query,
                    "format": "json", "srlimit": 3},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json().get("query", {}).get("search", [])
    except Exception as exc:
        LOGGER.debug("Wikipedia search API error for '%s': %s", brand, exc)
        return None

    for hit in hits:
        title = hit.get("title", "")
        result = _try_summary(title)
        if result and _is_relevant(result, brand, program_name):
            return result

    return None


def _is_relevant(result: WikipediaResult, brand: str, program_name: str) -> bool:
    """Reject disambiguation pages and articles clearly about something else."""
    title_lower = result.title.lower()
    extract_lower = result.extract.lower()

    # Reject obvious disambiguation pages
    if "may refer to" in extract_lower[:120]:
        return False

    brand_words = set(brand.lower().split())
    # At least one brand word must appear in title or first 300 chars of extract
    text_sample = title_lower + " " + extract_lower[:300]
    if not any(word in text_sample for word in brand_words if len(word) > 3):
        return False

    return True
