"""Inject high-confidence URLs directly into the Firecrawl queue.

These URLs are known from program metadata (official_domain, brand name)
and don't need a Tavily search to discover. Adding them here:
  - Guarantees we always attempt the Trustpilot brand review page
  - Seeds T&C and FAQ at the program's official domain
  - Reuses App Store / Play Store exact URLs already fetched by app_ratings_fetcher

If a seeded URL 404s or is blocked, Firecrawl records it as a failed scrape
and the pipeline continues normally — no URL here can cause a hard failure.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote, urlparse

from core.schemas import RetrievedUrl, new_id

LOGGER = logging.getLogger(__name__)

# Trustpilot's search page is always reachable (no domain guessing needed).
# Firecrawl scrapes it as a rendered page so we get brand review results.
_TRUSTPILOT_SEARCH = "https://www.trustpilot.com/search?query={query}"

# Top-3 T&C and FAQ paths by prevalence across loyalty program sites.
# Firecrawl silently drops ones that 404 or redirect away.
_TC_PATHS = ["/terms", "/terms-and-conditions", "/legal/terms"]
_FAQ_PATHS = ["/faq", "/help"]

# Suffixes that appear in program domains but not the parent brand's Trustpilot slug.
_PROGRAM_DOMAIN_NOISE = re.compile(
    r"(rewards|loyalty|club|plus|points|miles|perks|advantage|elite|app)\.",
    re.IGNORECASE,
)


def seed_urls(
    brand: str,
    program_name: str,
    official_domain: str | None,
    app_store_url: str | None = None,
    play_store_url: str | None = None,
) -> list[RetrievedUrl]:
    """Return a list of high-confidence RetrievedUrls to inject into the Firecrawl queue."""
    seeded: list[RetrievedUrl] = []

    seeded.extend(_trustpilot_urls(brand))
    seeded.extend(_tc_faq_urls(official_domain, program_name))

    if app_store_url and "apple.com" in app_store_url:
        seeded.append(_make_url(app_store_url, "app_reviews", program_name, score=0.85))

    if play_store_url and "play.google.com" in play_store_url:
        seeded.append(_make_url(play_store_url, "app_reviews", program_name, score=0.85))

    LOGGER.debug("Seeded %d direct URLs for '%s'", len(seeded), program_name)
    return seeded


# ── Trustpilot ────────────────────────────────────────────────────────────────

def _trustpilot_urls(brand: str) -> list[RetrievedUrl]:
    urls: list[RetrievedUrl] = []

    # 1. Search page — always valid, shows brand ratings in rendered output
    search_url = _TRUSTPILOT_SEARCH.format(query=quote(brand, safe=""))
    urls.append(_make_url(search_url, "forums", brand, score=0.80,
                          title=f"Trustpilot reviews: {brand}"))

    # 2. Direct review page — works when Trustpilot's slug matches the brand name
    #    e.g. "Starbucks" → trustpilot.com/review/starbucks.com
    slug = brand.lower().strip().replace(" ", "") + ".com"
    direct_url = f"https://www.trustpilot.com/review/{slug}"
    urls.append(_make_url(direct_url, "forums", brand, score=0.75,
                          title=f"Trustpilot: {brand}"))

    return urls


# ── T&C and FAQ ───────────────────────────────────────────────────────────────

def _tc_faq_urls(official_domain: str | None, program_name: str) -> list[RetrievedUrl]:
    if not official_domain:
        return []

    domain = _normalise_domain(official_domain)
    if not domain:
        return []

    base = f"https://{domain}"
    urls: list[RetrievedUrl] = []

    for path in _TC_PATHS:
        urls.append(_make_url(f"{base}{path}", "terms", program_name, score=0.70,
                              title=f"{program_name} terms and conditions"))

    for path in _FAQ_PATHS:
        urls.append(_make_url(f"{base}{path}", "faq", program_name, score=0.65,
                              title=f"{program_name} FAQ"))

    return urls


def _normalise_domain(raw: str) -> str | None:
    """Return a clean hostname from a raw domain string, or None if unparseable."""
    raw = raw.strip().lower()
    if not raw.startswith("http"):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
        host = parsed.netloc or parsed.path
        # Strip www. prefix so Trustpilot slug construction is cleaner
        host = re.sub(r"^www\.", "", host)
        if "." not in host:
            return None
        return host
    except Exception:
        return None


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_url(
    url: str,
    source_type: str,
    query_text: str,
    *,
    score: float = 0.70,
    title: str | None = None,
) -> RetrievedUrl:
    return RetrievedUrl(
        url=url,
        canonical_url=url,
        title=title,
        score=score,
        query=query_text,
        query_id=new_id("seeded"),
        external_query_id=None,
        source_type=source_type,
    )
