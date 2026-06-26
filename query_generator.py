"""Gemini-powered Tavily query generation."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Protocol

import requests

import cost_tracker
from providers import provider_for_stage
from schemas import ProgramIdentity, QueryGenerationOutput, SearchQuery


def _record_gemini_usage(stage: str, usage: dict) -> None:
    ledger = cost_tracker.get_current_ledger()
    if ledger is None:
        return
    prompt = int(usage.get("promptTokenCount") or 0)
    completion = int(usage.get("candidatesTokenCount") or 0)
    if prompt or completion:
        ledger.record_gemini(stage, prompt, completion)


QUERY_GENERATOR_SYSTEM_PROMPT = """
You are the Kobie Loyalty Program Research Query Planner.

MISSION
Generate 9–15 Tavily search queries whose scraped content will populate the maximum number
of fields in the schema below. Every query must serve one or more named schema fields.
Queries that do not map to a schema field waste budget and must not appear.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TARGET SCHEMA  (these field names drive every query you write)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GROUP A  program_basics
         membership_count · industry · program_type · geography

GROUP B  earn_mechanics          ← high priority
         base_earn_rate · bonus_categories · non_transactional_earn

GROUP C  burn_mechanics          ← high priority
         redemption_options · redemption_thresholds · point_value_cpp · expiry_policy

GROUP D  tier_system             ← high priority
         tier_names · qualification_criteria · tier_benefits · qualification_period

GROUP E  partnerships            ← high priority
         partner_names · partnership_type · details

GROUP F  digital_experience
         mobile_app_available · app_ratings · personalization_features · gamification_features

GROUP G  member_sentiment
         ratings · common_praise · common_complaints · sources_checked

GROUP H  competitive_position
         key_differentiators · weaknesses · closest_competitors

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "program_name":      "<official program name>",
  "brand":             "<parent brand>",
  "domain":            "<optional: provided program category>",
  "country_or_region": "<optional: IN | US | UK | GLOBAL>",
  "program_subtype":   "<B2B | B2C | omitted>"
}
If "domain" is provided, use it as detected_category verbatim — do not override or drift to "Other".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — CHARACTERISE THE PROGRAM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Reason through these before writing any query:

1a. PROGRAM TYPE
    Identify the business category from the program name and brand alone:
    airline · hotel · banking/credit card · QSR/coffee · grocery · pharmacy ·
    fuel/petrol · e-commerce · retail · coalition · fitness · gaming · telco · other
    Use domain input if provided; infer otherwise.

1b. CORPORATE PARENT
    Identify the owning company (e.g. Dunkin' Rewards → Inspire Brands / Dunkin').
    If the parent is a private company with no public investor filings, skip Group A financial queries.

1c. WEB PRESENCE SCALE
    Estimate how much is publicly searchable for this specific program:
    · Major global (>50 M members, household name): 13–15 queries — dedicated pages exist for most fields
    · Mid-tier or regional:                         11–13 queries — some fields share a page
    · Niche, new, or private-label:                  9–11 queries — focus on official pages and news
    Do not inflate query count to reach 15 if the program does not have that much web presence.

1d. FIELD REACHABILITY
    For each schema group, ask: is there a public web page that contains this data for this program?
    · Groups B, C, D, E: almost always findable on official program pages — never skip these
    · Groups F, G:       findable via app stores and review sites — never skip these
    · Group A (membership_count): findable only if corporate parent has public investor filings
    · Group H:           findable via comparison/analysis articles — never skip this

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — SCHEMA-DRIVEN QUERY PLAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For each schema group, here is the source type and page type most likely to contain its fields:

  Group B (earn_mechanics)      → "official"    — earn rates page, how-it-works page
  Group C (burn_mechanics)      → "official"    — redeem page, T&C for expiry
                                  "valuation"   — CPP / point value analysis articles
  Group D (tier_system)         → "official"    — single page listing ALL membership tiers
  Group E (partnerships)        → "partners"    — partner list or transfer partner overview
  Group F (digital_experience)  → SKIP — app_ratings are fetched directly from store APIs;
                                  do NOT generate any "app_reviews" queries. Generate a query
                                  only if the program has notable personalization or gamification
                                  features documented on its official site ("official" source_type).
  Group G (member_sentiment)    → "forums"      — Trustpilot, FlyerTalk (airline/hotel), expert blogs
  Group H (competitive_position)→ "competitors" — [program] vs [competitor] comparison articles
  Group A (membership_count)    → "financial"   — annual report or investor presentation

Allocate at least 1 query per group for groups B, C, D, E, G, H.
Group F requires a query only when personalization/gamification features exist on official pages.
A single query may cover multiple fields within the same group.
Add a second query for a group only when field coverage clearly benefits (e.g. earn + expiry are on
different pages).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — QUERY CONSTRUCTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY RULES — no exceptions
✓ Every query must contain the exact program name OR resolved corporate parent name.
✓ One query = one intent. Do not bundle unrelated schema groups into one query.
✓ Concise noun phrases only. No questions. No conversational language. No placeholder text.
✓ Preferred length: 3–7 words. Hard maximum: 10 words.
✗ Do NOT include any year, date, or "latest" in query text — recency is handled automatically
  downstream via Tavily's date filter. Adding a year produces a static query that breaks
  the following year.

TIER QUERY
✓ Exactly one query must target a page that lists ALL tier levels together.
  Use natural phrasing such as "[program] membership tiers overview" or "[program] status levels".
✗ Do NOT query individual tier pages separately (e.g. "[program] Gold tier benefits").

PARTNERSHIP QUERY
✓ Exactly one query must target a partner list or transfer partner overview page.
  Use phrasing such as "[program] partners list" or "[program] earn burn partners".

FINANCIAL / MEMBERSHIP SCALE QUERY
✓ Use the corporate parent name (not program name) for investor / annual report queries.
✗ Omit if the corporate parent is unknown or has no known public investor filings.

PROGRAM RULES QUERY (T&C)
✓ Include one query targeting T&C or program rules to anchor expiry_policy and earn rate limits.
  Use phrasing such as "[program] terms and conditions" or "[program] program rules FAQ".

SENTIMENT SOURCES — use these; do not invent others
  Trustpilot is seeded AUTOMATICALLY — do NOT generate a site:trustpilot.com query.
  AIRLINE / HOTEL programs only: site:flyertalk.com [program] complaints
  INDIA programs (IN):           site:technofino.com [program]  OR  site:cardexpert.in [program]
  India news / scale:            [program] site:economictimes.indiatimes.com
  ALL other programs:            [program] reviews complaints (general web sentiment query)

BLOCKED DOMAINS — never generate queries targeting:
✗ reddit.com (all subdomains — Firecrawl cannot scrape it)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HALLUCINATION PREVENTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Violations here produce queries that return irrelevant pages and waste extraction budget.

✗ DO NOT name specific partners, airlines, hotels, or merchants in a query unless you are
  certain they are a documented partner of this specific program.
✗ DO NOT use terminology that belongs to a different program type
  (e.g. do not use "elite nights" for a coffee chain; do not use "miles" for a retail points program;
   do not use "award chart" for a banking card program).
✗ DO NOT add "site:" restrictions unless you are confident that site has content about this program.
  Permitted site: restrictions and their conditions:
    site:trustpilot.com    — universal, always permitted
    site:flyertalk.com     — airline and hotel programs only
    site:technofino.com    — India banking/credit card programs only
    site:cardexpert.in     — India banking/credit card programs only
    site:economictimes.indiatimes.com — India programs only
✗ DO NOT reference tier names, earn rates, or partner names you have not confirmed for this program.
✗ DO NOT generate a membership_count / financial query if the corporate parent is unknown or private
  with no public filings.
✗ DO NOT generate queries for fields that are structurally inapplicable
  (e.g. "transfer partners" for a closed-loop QSR program with no transfer partners).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
B2B CORPORATE PROGRAM RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Apply only when program_subtype is "B2B":
✓ All queries must target the corporate/business variant of the program.
✓ Append "for business" or "corporate" qualifiers where needed to avoid consumer program pages.
✓ Tier queries → company-level spend thresholds and unique traveler counts, NOT individual elite tiers.
✓ Partnership queries → corporate earn/burn mechanics.
✓ Competitive queries → specifically named B2B competitor programs (e.g. AAdvantage Business, PerksPlus).
✗ Do NOT retrieve individual consumer program pages.

When program_subtype is "B2C" or omitted: generate queries for the individual consumer program normally.
✗ Do NOT retrieve corporate or business program pages.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCE TYPE ENUM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every query MUST use exactly one of these 10 values (lowercase — no other values accepted):

  "official"    Brand-owned pages: earn/redeem how-it-works, membership portal, program overview
  "terms"       T&C, legal documents, cardholder agreements, program rules
  "faq"         FAQ and help center pages
  "valuation"   CPP analysis, point/mile/cashback value benchmarks, redemption value
  "partners"    Partner lists, transfer partner pages, earn/burn partner overviews
  "app_reviews" App Store or Google Play store listings, ratings, and reviews
  "forums"      Trustpilot, FlyerTalk, expert review blogs, consumer sentiment pages
  "competitors" vs. articles, competitive comparison, benchmark reports
  "news"        Press releases, program change / devaluation announcements
  "financial"   Annual reports, investor presentations, loyalty liability disclosures

Assign these exactly — never deviate:
  site:trustpilot.com ...                   → "forums"
  site:flyertalk.com ...                    → "forums"
  site:technofino.com / cardexpert.in ...   → "forums"
  ... complaints / praise / reviews ...     → "forums"
  ... app review Google Play / App Store ... → "app_reviews"
  ... vs [program] / comparison ...         → "competitors"
  ... redemption value / cpp / valuation    → "valuation"
  ... annual report / investor / liability  → "financial"
  ... devaluation / recent changes / news   → "news"
  ... terms and conditions / program rules  → "terms"
  ... FAQ / help ...                        → "faq"
  ... partners list / transfer partners ... → "partners"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUERY ORDERING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Order queries strictly by schema extraction priority. Source type does NOT affect order.

  1. earn_mechanics     (base_earn_rate, bonus_categories, non_transactional_earn)
  2. tier_system        (tier_names, qualification_criteria, tier_benefits, qualification_period)
  3. burn_mechanics     (redemption_options, point_value_cpp, redemption_thresholds, expiry_policy)
  4. partnerships       (partner_names, partnership_type, details)
  5. digital_experience (app_ratings, mobile_app_available, personalization_features, gamification_features)
  6. program_basics     (membership_count — financial query using corporate parent name)
  7. member_sentiment   (common_praise, common_complaints, ratings, sources_checked)
  8. competitive_position (closest_competitors, key_differentiators, weaknesses)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY valid JSON. No explanation. No markdown fences.

Use the exact schema field names shown in the TARGET SCHEMA for target_fields and field_query_map keys.

estimated_web_coverage: fraction of the 30 schema fields that have at least one public web source.
  · Major global programs (household name, >50 M members): 0.75–0.95
  · Mid-tier / regional:                                    0.55–0.75
  · Niche / new / private-label:                            0.35–0.55
  Never output 0.0 — even the smallest program has at least its earn rules and T&C publicly available.

{
  "detected_category": "",
  "resolved_corporate_parent": "",
  "geography": "",
  "priority_fields": ["base_earn_rate", "tier_names", "point_value_cpp", "partner_names"],
  "query_strategy_summary": "",
  "estimated_web_coverage": 0.65,
  "field_query_map": {
    "base_earn_rate":           ["Q01"],
    "bonus_categories":         ["Q01", "Q02"],
    "non_transactional_earn":   ["Q02"],
    "tier_names":               ["Q03"],
    "qualification_criteria":   ["Q03"],
    "tier_benefits":            ["Q03"],
    "qualification_period":     ["Q03"],
    "redemption_options":       ["Q04"],
    "point_value_cpp":          ["Q05"],
    "redemption_thresholds":    ["Q04"],
    "expiry_policy":            ["Q06"],
    "partner_names":            ["Q07"],
    "partnership_type":         ["Q07"],
    "personalization_features": ["Q08"],
    "gamification_features":    ["Q08"],
    "membership_count":         ["Q09"],
    "common_praise":            ["Q10"],
    "common_complaints":        ["Q10"],
    "ratings":                  ["Q10"],
    "sources_checked":          ["Q10"],
    "closest_competitors":      ["Q11"],
    "key_differentiators":      ["Q11"],
    "weaknesses":               ["Q11"]
  },
  "queries": [
    {
      "query_id": "Q01",
      "query": "",
      "intent": "",
      "target_fields": ["base_earn_rate", "bonus_categories"],
      "source_type": "official"
    }
  ]
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VALIDATION RULES  (checked by the calling system — violations are rejected)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- query count: 9–15
- max 10 words per query
- no placeholder text in any field
- field_query_map must not be empty
- at least one query must target: member_sentiment · competitive_position · membership_count ·
  tier_names (all levels) · partner_names (full list)
- do NOT generate "app_reviews" source_type queries — app_ratings are fetched directly via store APIs
- no query may contain "reddit.com"
- every source_type must be one of the 10 canonical values (lowercase)
""".strip()


class QueryGeneratorClient(Protocol):
    def complete_json(self, prompt: str) -> dict[str, Any]:
        """Return the query generator response parsed as JSON."""


TRANSIENT_GEMINI_STATUS_CODES = {429, 500, 502, 503, 504}


class _QueryGenKeyPool:
    """Round-robin across QUERY_GENERATOR_API_KEYS; advances on 429."""

    def __init__(self) -> None:
        keys = self._load_keys()
        if not keys:
            raise RuntimeError("Query generator is not configured. Set GEMINI_API_KEY.")
        self._keys = keys
        self._index = 0
        self._lock = threading.Lock()

    @staticmethod
    def _load_keys() -> list[str]:
        multi = os.getenv("QUERY_GENERATOR_API_KEYS", "")
        keys = [k.strip() for k in multi.split(",") if k.strip()]
        if not keys:
            provider = provider_for_stage("query_generator")
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


class GeminiQueryGeneratorClient:
    """Google Gemini generateContent REST client with key-pool rotation on 429."""

    def __init__(self, max_retries: int | None = None, retry_sleep_seconds: float = 1.0) -> None:
        provider = provider_for_stage("query_generator")
        self.api_base = (provider.api_base or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self._key_pool = _QueryGenKeyPool()
        self.model = provider.resolved_model or "gemini-2.5-flash"
        self.models = _ordered_models(
            self.model,
            _fallback_models_env("QUERY_GENERATOR_FALLBACK_MODELS", "gemini-2.5-flash-lite"),
        )
        self.max_retries = max_retries if max_retries is not None else _env_int("QUERY_GENERATOR_MAX_RETRIES", 2)
        self.retry_sleep_seconds = retry_sleep_seconds

    def complete_json(self, prompt: str) -> dict[str, Any]:
        response = self._post_with_retries(prompt)
        payload = response.json()
        usage = payload.get("usageMetadata", {})
        _record_gemini_usage("query_generator", usage)
        content = payload["candidates"][0]["content"]["parts"][0]["text"]
        return parse_json_content(content)

    def _post_with_retries(self, prompt: str) -> requests.Response:
        last_error: requests.HTTPError | None = None
        for model_index, model in enumerate(self.models):
            for attempt in range(self.max_retries + 1):
                api_key = self._key_pool.current()
                response = requests.post(
                    f"{self.api_base}/models/{model}:generateContent",
                    headers={
                        "x-goog-api-key": api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0.2,
                            "responseMimeType": "application/json",
                            "thinkingConfig": {"thinkingBudget": 0},
                        },
                    },
                    timeout=60,
                )
                if response.status_code == 429:
                    self._key_pool.advance()

                if response.status_code not in TRANSIENT_GEMINI_STATUS_CODES:
                    response.raise_for_status()
                    self.model = model
                    return response

                last_error = requests.HTTPError(
                    f"Gemini query generator is temporarily unavailable "
                    f"({response.status_code}) for model {model}.",
                    response=response,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep_seconds * (attempt + 1))
            if model_index + 1 < len(self.models):
                time.sleep(self.retry_sleep_seconds)

        if last_error:
            raise last_error
        raise RuntimeError("Gemini query generator request failed.")


class GroqQueryGeneratorClient:
    """Groq-backed query generator — used as a fallback when Gemini is exhausted.

    Reads keys from QUERY_GENERATOR_GROQ_API_KEYS (comma-separated).
    Returns the same JSON structure as GeminiQueryGeneratorClient so it
    satisfies the QueryGeneratorClient protocol transparently.
    """

    def __init__(self) -> None:
        raw = os.getenv("QUERY_GENERATOR_GROQ_API_KEYS", "").strip()
        self._keys = [k.strip() for k in raw.split(",") if k.strip()]
        self._index = 0

    @property
    def configured(self) -> bool:
        return bool(self._keys)

    def complete_json(self, prompt: str) -> dict[str, Any]:
        if not self._keys:
            raise RuntimeError("QUERY_GENERATOR_GROQ_API_KEYS not set.")
        from groq import Groq
        import re as _re

        model = os.getenv("QUERY_GENERATOR_GROQ_MODEL", "llama-3.3-70b-versatile")
        last_exc: Exception | None = None
        for _ in range(len(self._keys) * 2):
            key = self._keys[self._index % len(self._keys)]
            self._index += 1
            try:
                client = Groq(api_key=key)
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=2048,
                )
                content = (response.choices[0].message.content or "").strip()
                return parse_json_content(content)
            except Exception as exc:
                msg = str(exc)
                if "rate_limit_exceeded" not in msg and "429" not in msg:
                    raise
                last_exc = exc
        raise last_exc or RuntimeError("GroqQueryGeneratorClient: exhausted all keys.")


_CANONICAL_SOURCE_TYPES = frozenset({
    "official", "terms", "faq", "valuation", "partners",
    "app_reviews", "forums", "competitors", "news", "financial",
})

# Maps LLM-generated drift values to their canonical equivalents.
# None means "ambiguous — fall back to infer_source_type on the query text."
_SOURCE_TYPE_ALIASES: dict[str, str | None] = {
    # Capitalization / pluralisation variants of canonical names
    "forum": "forums",
    "partner": "partners",
    "app_review": "app_reviews",
    # LLM-invented names seen in practice
    "sentiment": "forums",
    "review": None,       # could be app_reviews OR forums — let text inference decide
    "reviews": None,
    "comparison": "competitors",
    "competitive": "competitors",
    "competitor": "competitors",
    "analysis": "competitors",   # "competitive analysis" context
    "investor": "financial",
    "ir": "financial",
    "ir_filing": "financial",
}


def _normalize_source_type(raw: str, query: str) -> str:
    """Map a raw source_type string from the LLM to a canonical value.

    Lowercases first; checks the canonical set; resolves known aliases;
    falls back to infer_source_type on the query text for ambiguous or unknown types.
    """
    lowered = raw.strip().lower()
    if lowered in _CANONICAL_SOURCE_TYPES:
        return lowered
    resolved = _SOURCE_TYPE_ALIASES.get(lowered)
    if resolved is not None:
        return resolved
    return infer_source_type(query)


# Priority tier for each target_field name — lower number = higher priority.
# Queries covering tier-1 fields should run before tier-4 sentiment queries so the
# scraper/extractor spends its budget on high-value schema fields first.
_FIELD_EXTRACTION_PRIORITY: dict[str, int] = {
    # Tier 1 — core transactional fields
    "earn_rate_base": 1, "base_earn_rate": 1, "bonus_categories": 1,
    "non_transactional_earn": 1,
    "tier_names": 1, "tier_structure": 1, "qualification_criteria": 1, "tier_benefits": 1,
    "redemption_options": 1, "point_value_cpp": 1, "redemption_thresholds": 1,
    "expiry_policy": 1,
    # Tier 2 — partnerships and transfers
    "transfer_partners": 2, "partner_names": 2, "partnership_type": 2, "partnerships": 2,
    "partner_ecosystem": 2, "redemption_network": 2,
    # Tier 3 — digital experience and program rules
    "app_ratings": 3, "mobile_app": 3, "personalization": 3, "gamification": 3,
    "app_store_rating": 3, "play_store_rating": 3,
    "lounge_access": 3, "reward_rate": 3, "cashback_value": 3,
    "award_chart": 3, "elite_nights": 3, "alliance_partners": 3,
    # Tier 4 — scale, sentiment, competitive
    "membership_count": 4, "loyalty_liability": 4,
    "member_sentiment": 4, "common_complaints": 4, "common_praise": 4,
    "competitive_position": 4, "closest_competitors": 4,
    "recent_changes_last_6_months": 4,
}

_DEFAULT_FIELD_PRIORITY = 3


def _query_extraction_priority(query: "SearchQuery") -> int:
    """Return the best (lowest) extraction priority tier across a query's target_fields.

    Queries with no target_fields get a neutral mid-tier score so they don't
    crowd out high-value queries but aren't pushed all the way to the end.
    """
    if not query.target_fields:
        return _DEFAULT_FIELD_PRIORITY
    return min(
        _FIELD_EXTRACTION_PRIORITY.get(field, _DEFAULT_FIELD_PRIORITY)
        for field in query.target_fields
    )


def _rank_queries_by_extraction_priority(queries: list["SearchQuery"]) -> list["SearchQuery"]:
    """Stable-sort queries so high extraction-value fields come first.

    Source type is not used as a sort key — only target_fields coverage matters.
    """
    return sorted(queries, key=_query_extraction_priority)


_BLOCKED_DOMAIN_PATTERNS = ("reddit.com",)


def _filter_blocked_queries(queries: list["SearchQuery"]) -> list["SearchQuery"]:
    """Drop any query whose text targets a domain the scraper cannot access."""
    return [
        q for q in queries
        if not any(domain in q.query.lower() for domain in _BLOCKED_DOMAIN_PATTERNS)
    ]


def generate_queries(
    identity: ProgramIdentity,
    client: QueryGeneratorClient | None = None,
) -> QueryGenerationOutput:
    generator = client or GeminiQueryGeneratorClient()
    try:
        payload = generator.complete_json(build_query_generator_prompt(identity))
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in TRANSIENT_GEMINI_STATUS_CODES:
            groq_client = GroqQueryGeneratorClient()
            if groq_client.configured:
                try:
                    payload = groq_client.complete_json(build_query_generator_prompt(identity))
                    output = parse_query_generation_output(payload, identity=identity)
                    ranked = _rank_queries_by_extraction_priority(
                        _filter_blocked_queries(_anchor_year_to_volatile_queries(output.queries))
                    )
                    return output.model_copy(update={"queries": ranked})
                except Exception:
                    pass
            if _local_fallback_enabled():
                return build_local_query_generation_output(identity, reason=f"Gemini returned {status_code}")
        raise
    output = parse_query_generation_output(payload, identity=identity)
    ranked = _rank_queries_by_extraction_priority(
        _filter_blocked_queries(_anchor_year_to_volatile_queries(output.queries))
    )
    return output.model_copy(update={"queries": ranked})


def build_local_query_generation_output(identity: ProgramIdentity, reason: str) -> QueryGenerationOutput:
    """Create a conservative Tavily query plan when Gemini is rate-limited."""

    program = identity.program_name.strip()
    brand = identity.brand.strip()
    subject = _query_subject(program, brand)
    geography = identity.country_or_region or "GLOBAL"
    domain = identity.domain or "Other"
    templates = _domain_query_templates(domain, geography)
    queries: list[SearchQuery] = []

    for index, template in enumerate(templates, start=1):
        query = _compact_query(f"{subject} {template['suffix']}")
        queries.append(
            SearchQuery(
                external_query_id=f"Q{index:02d}",
                query=query,
                intent=template["intent"],
                target_fields=template["target_fields"],
                source_type=template["source_type"],
            )
        )

    queries = _rank_queries_by_extraction_priority(
        _filter_blocked_queries(_anchor_year_to_volatile_queries(queries))
    )
    external_to_internal = {query.external_query_id: query.query_id for query in queries if query.external_query_id}
    field_query_map: dict[str, list[str]] = {}
    for query in queries:
        for field in query.target_fields:
            if query.external_query_id:
                field_query_map.setdefault(field, []).append(external_to_internal[query.external_query_id])

    return QueryGenerationOutput(
        detected_category=domain,
        resolved_corporate_parent=brand or None,
        geography=geography,
        query_strategy_summary=(
            f"Generated a local fallback query plan because {reason}. "
            "Gemini key validation is separate from rate limits and quota."
        ),
        priority_fields=_priority_fields_for_domain(domain),
        estimated_web_coverage=0.55,
        field_query_map=field_query_map,
        queries=queries,
    )


# Only "news" and "financial" queries benefit from an explicit year in the query text —
# "news" to surface this year's announcements over older SEO content, "financial" to target
# this year's annual report rather than a prior filing.
# All other source types are handled by Tavily's `days` recency filter (see retrieval.py),
# which is cleaner and doesn't inflate the query with a static-looking date.
_YEAR_ANCHOR_SOURCE_TYPES = frozenset({"news", "financial"})


def _strip_embedded_year(text: str) -> str:
    """Remove any four-digit calendar year the LLM baked into query text.

    The prompt instructs the LLM not to add years, but as a safety net we strip
    them here before our own year-anchor logic runs. This prevents double-year
    and ensures official/partners/valuation queries stay year-free.
    """
    return re.sub(r"\s*\b20\d{2}\b", "", text).strip()


def _anchor_year_to_volatile_queries(queries: list[SearchQuery]) -> list[SearchQuery]:
    """Append the current year only to news and financial queries.

    For all other source types, Tavily's `days=365` recency filter is sufficient.
    Steps per query:
      1. Strip any year the LLM embedded in the query text.
      2. Append the current year only if source_type is "news" or "financial".
    """
    year = str(datetime.now(timezone.utc).year)
    result: list[SearchQuery] = []
    for query in queries:
        clean_text = _strip_embedded_year(query.query)
        if query.source_type in _YEAR_ANCHOR_SOURCE_TYPES:
            words = clean_text.split()
            if len(words) < 10:
                clean_text = f"{clean_text} {year}"
            else:
                clean_text = " ".join(words[:9]) + f" {year}"
        if clean_text != query.query:
            query = query.model_copy(update={"query": clean_text})
        result.append(query)
    return result


def build_query_generator_prompt(identity: ProgramIdentity) -> str:
    prompt_identity = {
        "program_name": identity.program_name,
        "brand": identity.brand,
        "domain": identity.domain,
        "country_or_region": identity.country_or_region or "GLOBAL",
        "program_subtype": identity.program_subtype or "B2C",
    }
    return (
        f"{QUERY_GENERATOR_SYSTEM_PROMPT}\n\n"
        "VALIDATED PROGRAM IDENTITY\n"
        f"{json.dumps(prompt_identity, indent=2, ensure_ascii=True)}"
    )


def parse_query_generation_output(
    payload: dict[str, Any],
    identity: ProgramIdentity | None = None,
) -> QueryGenerationOutput:
    queries: list[SearchQuery] = []
    for item in payload.get("queries", [])[:15]:
        if isinstance(item, str):
            query = item.strip()
            source_type = infer_source_type(query)
            external_query_id = None
            intent = None
            target_fields: list[str] = []
        elif isinstance(item, dict):
            query = str(item.get("query") or "").strip()
            raw_source_type = str(item.get("source_type") or "").strip()
            source_type = (
                _normalize_source_type(raw_source_type, query)
                if raw_source_type
                else infer_source_type(query)
            )
            external_query_id = item.get("query_id")
            intent = item.get("intent")
            target_fields = [str(field) for field in item.get("target_fields", [])]
        else:
            continue

        if query:
            query_kwargs: dict[str, Any] = {
                "query": query,
                "source_type": source_type or "official",
                "intent": str(intent) if intent else None,
                "target_fields": target_fields,
            }
            if external_query_id:
                query_kwargs["external_query_id"] = str(external_query_id)
            queries.append(SearchQuery(**query_kwargs))

    external_to_internal = {
        query.external_query_id: query.query_id
        for query in queries
        if query.external_query_id
    }

    detected_category = str(payload.get("detected_category") or "").strip()
    if identity and identity.domain:
        detected_category = identity.domain

    return QueryGenerationOutput(
        detected_category=detected_category or "Other",
        resolved_corporate_parent=empty_to_none(payload.get("resolved_corporate_parent")),
        geography=empty_to_none(payload.get("geography")) or (identity.country_or_region if identity else None),
        query_strategy_summary=str(payload.get("query_strategy_summary") or "Generated Tavily query plan."),
        priority_fields=[str(field) for field in payload.get("priority_fields", [])],
        estimated_web_coverage=normalize_coverage(payload.get("estimated_web_coverage")),
        field_query_map={
            str(field): [
                external_to_internal.get(str(query_id), str(query_id))
                for query_id in query_ids
            ]
            for field, query_ids in (payload.get("field_query_map") or {}).items()
            if isinstance(query_ids, list)
        },
        queries=queries,
    )


def empty_to_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def normalize_coverage(value: object) -> float:
    try:
        coverage = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, coverage))


def parse_json_content(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _domain_query_templates(domain: str, geography: str) -> list[dict[str, Any]]:
    domain_lower = domain.lower()
    templates = [
        {
            "suffix": "terms conditions",
            "intent": "official program rules",
            "target_fields": ["earn_rate_base", "expiry_policy"],
            "source_type": "terms",
        },
        {
            "suffix": "FAQ benefits",
            "intent": "official FAQ and member benefits",
            "target_fields": ["tier_structure", "redemption_options"],
            "source_type": "faq",
        },
        {
            "suffix": "earn points bonus categories",
            "intent": "earn mechanics",
            "target_fields": ["earn_rate_base", "bonus_categories"],
            "source_type": "official",
        },
        {
            "suffix": "redeem points value",
            "intent": "redemption value",
            "target_fields": ["point_value", "redemption_thresholds"],
            "source_type": "valuation",
        },
        {
            "suffix": "partners transfer redemption",
            "intent": "partner ecosystem",
            "target_fields": ["partnerships", "transfer_partners"],
            "source_type": "partners",
        },
        {
            "suffix": "recent changes devaluation",
            "intent": "recent changes and devaluations",
            "target_fields": ["recent_changes_last_6_months"],
            "source_type": "news",
        },
        {
            "suffix": "members annual report liability",
            "intent": "membership scale and loyalty liability",
            "target_fields": ["membership_count", "loyalty_liability"],
            "source_type": "news",
        },
        {
            "suffix": "reviews complaints member feedback",
            "intent": "member sentiment",
            "target_fields": ["member_sentiment", "common_complaints"],
            "source_type": "forums",
        },
        {
            "suffix": "competitors comparison value",
            "intent": "competitive position",
            "target_fields": ["competitive_position", "closest_competitors"],
            "source_type": "competitors",
        },
    ]

    if "airline" in domain_lower:
        templates.insert(
            3,
            {
                "suffix": "elite status award chart",
                "intent": "airline tier and award rules",
                "target_fields": ["tier_structure", "award_chart", "elite_status"],
                "source_type": "official",
            },
        )
    elif "hotel" in domain_lower:
        templates.insert(
            3,
            {
                "suffix": "elite nights points per night",
                "intent": "hotel tier and redemption rules",
                "target_fields": ["tier_structure", "elite_nights", "redemption_value"],
                "source_type": "official",
            },
        )
    elif "bank" in domain_lower or "credit" in domain_lower:
        templates.insert(
            3,
            {
                "suffix": "lounge access reward rate",
                "intent": "banking card benefits",
                "target_fields": ["lounge_access", "reward_rate"],
                "source_type": "official",
            },
        )
    elif "retail" in domain_lower or "commerce" in domain_lower:
        templates.insert(
            3,
            {
                "suffix": "cashback rewards value",
                "intent": "retail cashback value",
                "target_fields": ["cashback_value", "redemption_options"],
                "source_type": "valuation",
            },
        )
    else:
        templates.insert(
            3,
            {
                "suffix": "partner ecosystem redemption network",
                "intent": "coalition partner network",
                "target_fields": ["partner_ecosystem", "redemption_network"],
                "source_type": "partners",
            },
        )

    if geography.lower() in {"india", "in"}:
        templates.append(
            {
                "suffix": "Technofino CardExpert review",
                "intent": "India-specific expert analysis",
                "target_fields": ["member_sentiment", "competitive_position"],
                "source_type": "forums",
            }
        )

    return templates[:12]


def _priority_fields_for_domain(domain: str) -> list[str]:
    """Return schema field names (matching FIELD_ALIASES keys) that matter most for this domain."""
    domain_lower = domain.lower()
    # Airline
    if "airline" in domain_lower:
        return ["base_earn_rate", "tier_names", "point_value_cpp", "partner_names"]
    # Hotel
    if "hotel" in domain_lower:
        return ["tier_names", "qualification_criteria", "point_value_cpp", "partner_names"]
    # Banking / credit card
    if "bank" in domain_lower or "credit" in domain_lower:
        return ["base_earn_rate", "partner_names", "tier_names", "point_value_cpp"]
    # Retail / e-commerce / QSR / any consumer program
    return ["base_earn_rate", "redemption_options", "point_value_cpp", "expiry_policy"]


def _query_subject(program: str, brand: str) -> str:
    program_words = program.split()
    if len(program_words) <= 6:
        return program
    return brand or " ".join(program_words[:6])


def _compact_query(query: str) -> str:
    words = query.split()
    return " ".join(words[:10])


def _ordered_models(primary_model: str, fallback_models: str) -> list[str]:
    models = [primary_model.strip()]
    models.extend(model.strip() for model in fallback_models.split(",") if model.strip())
    return list(dict.fromkeys(models))


def _fallback_models_env(name: str, default: str) -> str:
    if name in os.environ:
        return os.environ[name]
    return os.getenv("GEMINI_FALLBACK_MODELS") or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _local_fallback_enabled() -> bool:
    return os.getenv("QUERY_GENERATOR_LOCAL_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}


def infer_source_type(query: str) -> str:
    lowered = query.lower()
    if "terms" in lowered or "conditions" in lowered:
        return "terms"
    if "faq" in lowered:
        return "faq"
    # Financial / investor relations — check before "partner" to avoid false match on "annual"
    if (
        "annual report" in lowered
        or "investor presentation" in lowered
        or "loyalty liability" in lowered
        or "deferred revenue" in lowered
        or "bond prospectus" in lowered
    ):
        return "financial"
    if "partner" in lowered or "transfer" in lowered:
        return "partners"
    # App store reviews — must check before generic "app" in case "app" appears in other queries
    if "google play" in lowered or "app store" in lowered or "play store" in lowered:
        return "app_reviews"
    if "rating" in lowered and "app" in lowered:
        return "app_reviews"
    # Community forums and consumer sentiment
    if (
        "reddit" in lowered
        or "flyertalk" in lowered
        or "trustpilot" in lowered
        or "forum" in lowered
        or "complaint" in lowered
        or "praise" in lowered
    ):
        return "forums"
    # Competitive analysis
    if "competitor" in lowered or "comparison" in lowered or " vs " in lowered:
        return "competitors"
    # Redemption / points value analysis
    if "value" in lowered or "valuation" in lowered or "cpp" in lowered or "cents per point" in lowered:
        return "valuation"
    # Time-sensitive news / change tracking
    if "news" in lowered or "recent" in lowered or "devaluation" in lowered or "changes" in lowered:
        return "news"
    # App (broad) — mobile experience without explicit store reference
    if "app" in lowered or "mobile" in lowered:
        return "app_reviews"
    return "official"
