"""Fetch app store ratings directly via Google Play Scraper and iTunes Search API.

Called once per pipeline run after query generation. Results bypass Tavily/Firecrawl
and are injected as a pre-built NormalizedObjectPacket in the ingest node.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

import requests as http_requests

LOGGER = logging.getLogger(__name__)

_ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
_ITUNES_TIMEOUT = 8
_GP_TIMEOUT = 10


@dataclass
class AppRatingsResult:
    play_store_score: float | None = None
    play_store_ratings_count: int | None = None
    play_store_app_id: str | None = None
    play_store_title: str | None = None

    app_store_score: float | None = None
    app_store_ratings_count: int | None = None
    app_store_app_id: str | None = None
    app_store_title: str | None = None

    errors: list[str] = field(default_factory=list)

    @property
    def found_any(self) -> bool:
        return self.play_store_score is not None or self.app_store_score is not None

    def as_text(self) -> str:
        """Human-readable summary for injection as extraction evidence."""
        parts: list[str] = []
        if self.play_store_score is not None:
            parts.append(
                f"Google Play Store rating: {self.play_store_score:.1f}/5"
                + (f" ({self.play_store_ratings_count:,} ratings)" if self.play_store_ratings_count else "")
            )
        if self.app_store_score is not None:
            parts.append(
                f"Apple App Store rating: {self.app_store_score:.1f}/5"
                + (f" ({self.app_store_ratings_count:,} ratings)" if self.app_store_ratings_count else "")
            )
        return "; ".join(parts) if parts else "App ratings not available"


def fetch_app_ratings(program_name: str, brand: str, country: str = "us") -> AppRatingsResult:
    """Return app ratings from Google Play and App Store for the given loyalty program."""
    result = AppRatingsResult()

    query = f"{program_name} loyalty"
    brand_query = f"{brand} loyalty"

    _fetch_play_store(result, query, brand_query, country)
    _fetch_app_store(result, query, brand_query, country)

    return result


def _fetch_play_store(result: AppRatingsResult, primary: str, fallback: str, country: str) -> None:
    try:
        from google_play_scraper import search as gp_search  # type: ignore[import-untyped]
    except ImportError:
        result.errors.append("google-play-scraper not installed")
        return

    for query in (primary, fallback):
        try:
            hits = gp_search(query, lang="en", country=country, n_hits=3)
        except Exception as exc:
            result.errors.append(f"Play Store search error: {exc}")
            continue

        hit = _best_hit(hits, primary)
        if hit:
            result.play_store_score = hit.get("score")
            result.play_store_ratings_count = hit.get("ratings")
            result.play_store_app_id = hit.get("appId")
            result.play_store_title = hit.get("title")
            LOGGER.debug(
                "Play Store: %s score=%.2f (%s ratings)",
                result.play_store_title,
                result.play_store_score or 0,
                result.play_store_ratings_count,
            )
            return


def _fetch_app_store(result: AppRatingsResult, primary: str, fallback: str, country: str) -> None:
    for query in (primary, fallback):
        try:
            resp = http_requests.get(
                _ITUNES_SEARCH_URL,
                params={"term": query, "entity": "software", "limit": 5, "country": country},
                timeout=_ITUNES_TIMEOUT,
            )
            resp.raise_for_status()
            hits = resp.json().get("results", [])
        except Exception as exc:
            result.errors.append(f"App Store search error: {exc}")
            continue

        hit = _best_hit(hits, primary, title_key="trackName", score_key="averageUserRating")
        if hit:
            result.app_store_score = hit.get("averageUserRating")
            result.app_store_ratings_count = hit.get("userRatingCount")
            result.app_store_app_id = str(hit.get("trackId", ""))
            result.app_store_title = hit.get("trackName")
            LOGGER.debug(
                "App Store: %s score=%.2f (%s ratings)",
                result.app_store_title,
                result.app_store_score or 0,
                result.app_store_ratings_count,
            )
            return


def _best_hit(
    hits: list[dict[str, Any]],
    query: str,
    *,
    title_key: str = "title",
    score_key: str = "score",
) -> dict[str, Any] | None:
    """Return the hit whose title most closely matches the query, filtering junk scores."""
    query_tokens = set(query.lower().split())
    best: dict[str, Any] | None = None
    best_overlap = -1

    for hit in hits:
        score = hit.get(score_key)
        if not score or score < 1.0:
            continue
        title = str(hit.get(title_key) or "").lower()
        overlap = len(query_tokens & set(title.split()))
        if overlap > best_overlap:
            best_overlap = overlap
            best = hit

    return best


def build_app_ratings_packet(result: AppRatingsResult, program_name: str) -> dict[str, Any] | None:
    """Build a NormalizedObjectPacket-shaped dict from a fetched AppRatingsResult.

    Returns None when no ratings were found.
    """
    if not result.found_any:
        return None

    from core.schemas import ExtractedField, NormalizedObjectPacket

    combined_rating = _combined_rating_string(result)
    source_url = _synthetic_source_url(result)
    chunk_id = sha256(f"app_ratings:{program_name}:{combined_rating}".encode()).hexdigest()[:16]

    fields: dict[str, ExtractedField] = {
        "app_ratings": ExtractedField(
            value=combined_rating,
            status="EXTRACTED",
            source_url=source_url,
            source_snippet=result.as_text(),
            confidence=0.95,
        ),
        "mobile_app_available": ExtractedField(
            value="yes",
            status="EXTRACTED",
            source_url=source_url,
            source_snippet="App found on Google Play or App Store.",
            confidence=0.99,
        ),
    }

    if result.play_store_score is not None:
        fields["play_store_rating"] = ExtractedField(
            value=f"{result.play_store_score:.1f}",
            status="EXTRACTED",
            source_url=f"https://play.google.com/store/apps/details?id={result.play_store_app_id or ''}",
            source_snippet=f"Google Play: {result.play_store_score:.1f}/5",
            confidence=0.95,
        )

    if result.app_store_score is not None:
        fields["app_store_rating"] = ExtractedField(
            value=f"{result.app_store_score:.1f}",
            status="EXTRACTED",
            source_url=f"https://apps.apple.com/app/id{result.app_store_app_id or ''}",
            source_snippet=f"App Store: {result.app_store_score:.1f}/5",
            confidence=0.95,
        )

    packet = NormalizedObjectPacket(
        object_type="digital_experience",
        fields=fields,
        source_url=source_url,
        chunk_id=chunk_id,
        scope={},
        identity_hash=chunk_id,
    )
    return packet.model_dump()


def _combined_rating_string(result: AppRatingsResult) -> str:
    parts: list[str] = []
    if result.app_store_score is not None:
        parts.append(f"{result.app_store_score:.1f} / 5 App Store")
    if result.play_store_score is not None:
        parts.append(f"{result.play_store_score:.1f} / 5 Play Store")
    return " ; ".join(parts)


def _synthetic_source_url(result: AppRatingsResult) -> str:
    if result.play_store_app_id:
        return f"https://play.google.com/store/apps/details?id={result.play_store_app_id}"
    if result.app_store_app_id:
        return f"https://apps.apple.com/app/id{result.app_store_app_id}"
    return "app-store://direct-fetch"
