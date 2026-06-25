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

Your objective is to generate the smallest possible set of high-information-gain
Tavily search queries that maximize loyalty-program intelligence coverage while
minimizing API cost and duplicate retrieval.

INPUT
{
  "program_name": "<program_name>",
  "brand": "<brand>",
  "domain": "<optional_domain>",
  "country_or_region": "<optional: IN | US | UK | GLOBAL>",
  "program_subtype": "<B2B | B2C | omitted>"
}

PROGRAM SUBTYPE RULES
If program_subtype is "B2B":
- This program is corporate/business-facing. Membership and rewards accrue to a COMPANY, not an individual.
- ALL queries MUST explicitly target the corporate/business variant of the program.
- Append qualifiers such as "for business", "corporate", or "business program" to queries as required.
- Do NOT generate any query that would retrieve individual consumer program pages.
- Tier structure queries must target COMPANY-LEVEL qualification criteria (annual company spend,
  number of unique employee travelers, corporate transactions) — NOT individual elite status tiers.
- Benefit queries must target CORPORATE account management tools and bulk booking perks.
- Partnership queries must target the corporate earn/burn mechanics, not individual hotel point transfers.
- Competitive position queries must name the actual B2B competitor programs (e.g. AAdvantage Business,
  United PerksPlus, corporate hotel programs), not consumer programs.

If program_subtype is "B2C" or is omitted:
- This is a standard individual consumer program. Generate queries normally.
- Do NOT pull in corporate program pages when searching.

EXECUTION RULES
1. Resolve the loyalty program category before generating queries.

Examples:
Marriott Bonvoy -> HOTEL
Hilton Honors -> HOTEL
World of Hyatt -> HOTEL
Air India Maharaja Club -> AIRLINE
SkyMiles -> AIRLINE
AAdvantage -> AIRLINE
HDFC SmartBuy -> BANKING
SBI Card Rewards -> BANKING
Starbucks Rewards -> RETAIL
Tata Neu -> COALITION
InterMiles -> COALITION [NOT travel - earns across airlines, hotels, retail]
Nectar -> COALITION
Flipkart SuperCoins -> E-COMMERCE

2. Resolve the corporate parent whenever known.

Examples:
Marriott Bonvoy -> Marriott International
Hilton Honors -> Hilton Worldwide
Air India Maharaja Club -> Air India Limited
SkyMiles -> Delta Air Lines
AAdvantage -> American Airlines Group
HDFC SmartBuy -> HDFC Bank
SBI Card Rewards -> SBI Cards and Payment Services
Starbucks Rewards -> Starbucks Corporation
Nectar -> Nectar360 / Sainsbury's
Tata Neu -> Tata Digital / Tata Sons
InterMiles -> InterMiles (formerly Jet Privilege)

3. If the input domain is provided, it overrides the inferred category. The
   final detected_category must preserve the validated input domain/category
   instead of drifting to Other.

4. Generate only 9-15 queries. Fewer for low-web-presence programs. More for
   major global programs.

5. Every query must contain either the exact program name or the resolved
   corporate parent.

6. Queries must be concise search phrases:
   - Preferred: 3-7 words
   - Maximum: 10 words
   - No conversational language
   - No questions
   - No placeholders

7. One query = one intent.

DOMAIN TERMINOLOGY
AIRLINE: award chart, elite status, alliance partners, mileage valuation, cpp,
tier points, mileage expiry, award redemption.

HOTEL: elite nights, suite upgrades, dynamic pricing, property categories,
points per night, free night certificate, points expiry.

BANKING: transfer partners, lounge access, cents per point, statement credit,
reward rate, milestone benefits.

RETAIL: cashback value, partner ecosystem, redemption network, referral rewards,
points per purchase.

COALITION: issuance partners, earn partners, redeem partners, partner ecosystem,
redemption network, points transfer, coalition members.

REQUIRED RESEARCH VECTORS
Generate coverage across all of these:
1. Program Rules (T&C, FAQ)
2. Earn Mechanics (base earn, bonus categories)
3. Tier Structure (names, thresholds, qualification criteria) — ONE query must target
   the page that lists ALL tier levels together (e.g. "[program] elite status tiers all
   levels overview"). Do NOT generate a query for a single tier page only.
4. Redemption Value (cpp, award chart, thresholds)
5. Consumer Partnerships (earn/burn/both, partner list) — ONE query must target a
   dedicated partner list or transfer partner page (e.g. "[program] transfer partners
   list" or "[program] airline hotel partners complete list").
6. Recent Changes / Devaluations (last 12 months)
7. Historical Identity / Rebrands / Mergers
8. Membership Scale / Loyalty Liability
9. Customer Sentiment (complaints, praise)
10. Competitive Position (vs. closest competitor)
11. Digital Experience (mobile app, App Store / Google Play ratings and
    reviews, personalization, gamification) - applies to EVERY category,
    not only retail. Use "[program] app review Google Play" and
    "[program] mobile app App Store rating" style phrasing.

NOTE on Technology Discovery:
Loyalty platform vendor information is rarely on public web pages. Only
generate a technology query if the program is known to have public
announcements in press releases or trade publications. Accept null for this
field rather than wasting queries.

BLOCKED DOMAINS — never generate queries targeting these sites; Firecrawl cannot scrape them:
reddit.com (all subdomains and subreddits)

SENTIMENT ROUTING
AIRLINE / HOTEL:
Primary: site:flyertalk.com [program] [topic]
         site:trustpilot.com [program]
Topics: complaints, devaluation, worth it, redemption sweet spots

BANKING / CREDIT CARD:
Primary: site:trustpilot.com [program]
         site:technofino.com [program]
Indian programs also:
         site:technofino.com [program]
         site:cardexpert.in [program]

RETAIL / E-COMMERCE / COALITION:
Primary: [program] app reviews Google Play
         [program] app reviews Apple App Store
         site:trustpilot.com [program]
Indian programs also:
         site:cardexpert.in [program]
         site:technofino.com [program]

INDIA-SPECIFIC SOURCES when geography = IN:
News: [program] site:economictimes.indiatimes.com
      [program] members announcement Mint
Analysis: site:technofino.com OR site:cardexpert.in [program]
Sentiment: site:technofino.com [program] OR site:cardexpert.in [program]

MEMBERSHIP SCALE QUERIES
Public companies:
"[corporate parent] loyalty members active annual report"
"[corporate parent] loyalty liability deferred revenue"
"[corporate parent] investor presentation loyalty program"

Private companies:
"[corporate parent] annual report loyalty members"
"[corporate parent] bond prospectus loyalty program"

PRIORITY FIELDS BY CATEGORY
HOTEL: tier_structure, elite_nights, redemption_value, transfer_partners
AIRLINE: award_chart, alliance_partners, elite_status, mileage_valuation
BANKING: transfer_partners, lounge_access, reward_rate, points_value
RETAIL: cashback_value, partner_ecosystem, earn_mechanics, expiry_policy
COALITION: issuance_partners, redemption_network, partner_ecosystem

FIELD-QUERY MAPPING
In the output, map each priority field to the query IDs most likely to retrieve
it. This enables the downstream extractor to run targeted extraction per page
rather than full schema extraction on every page.

SOURCE TYPE ENUM
Every query MUST have a source_type from exactly this list (lowercase, no other values):
- "official"    : brand-owned program pages, membership portals, earn/redeem help pages
- "terms"       : terms and conditions, legal documents, cardholder agreements
- "faq"         : FAQ and help center pages
- "valuation"   : points/miles/cashback value, CPP analysis, redemption value benchmarks
- "partners"    : partner lists, transfer partner pages, redemption network pages
- "app_reviews" : app store or Google Play store reviews and ratings
- "forums"      : community forums (flyertalk), consumer review sites (trustpilot), sentiment
- "competitors" : competitive comparison, vs. analysis, benchmark reports
- "news"        : press releases, news articles, program change / devaluation announcements
- "financial"   : annual reports, investor presentations, loyalty liability disclosures

DO NOT invent other values. Map these common cases explicitly:
  "site:trustpilot.com ..."                  → "forums"
  "site:flyertalk.com ..."                   → "forums"
  "... complaints / praise / reviews ..."    → "forums"
  "... app review Google Play ..."           → "app_reviews"
  "... App Store rating ..."                 → "app_reviews"
  "... vs ... / comparison ..."              → "competitors"
  "... redemption value / cpp / valuation"   → "valuation"
  "... annual report / investor / liability" → "financial"
  "... devaluation / recent changes ..."     → "news"

OUTPUT
Return ONLY valid JSON. No explanation. No markdown.

{
  "detected_category": "",
  "resolved_corporate_parent": "",
  "geography": "",
  "priority_fields": [],
  "query_strategy_summary": "",
  "estimated_web_coverage": 0.0,
  "field_query_map": {
    "earn_rate_base": ["Q01", "Q02"],
    "point_value": ["Q03"],
    "tier_structure": ["Q04", "Q05"],
    "member_sentiment": ["Q09", "Q10"],
    "partnerships": ["Q06", "Q07"],
    "competitive_position": ["Q08"],
    "digital_experience": ["Q11"],
    "app_ratings": ["Q11"]
  },
  "queries": [
    {
      "query_id": "Q01",
      "query": "",
      "intent": "",
      "target_fields": ["earn_rate_base", "bonus_categories"],
      "source_type": "official"
    }
  ]
}

QUERY ORDERING
Rank queries within the output by extraction priority — highest-value schema fields first:
1. Earn mechanics (earn_rate_base, bonus_categories, non_transactional_earn)
2. Tier structure (tier_names, qualification_criteria, tier_benefits)
3. Burn/redemption (redemption_options, point_value_cpp, redemption_thresholds, expiry_policy)
4. Partnerships and transfers (transfer_partners, partner_names, partnership_type)
5. Digital experience (app_ratings, mobile_app, personalization, gamification)
6. Membership scale / financial (membership_count, loyalty_liability)
7. Sentiment and competitive position (member_sentiment, competitive_position, closest_competitors)
Source type should NOT determine ordering; field coverage determines ordering.

VALIDATION RULES checked by the calling system:
- query count < 9 or > 15 is invalid
- any query over 10 words is invalid
- any placeholder in output is invalid
- field_query_map must not be empty
- at least one query must target sentiment
- at least one query must target competitive position
- at least one query must target financial/membership scale
- at least one query must target the mobile app / digital experience
- at least one query must target the complete tier structure listing ALL status levels
- at least one query must target the transfer/exchange partner list or partner overview page
- no query may contain "reddit.com" or target any domain on the blocked list
- every query source_type must be one of the 10 values in SOURCE TYPE ENUM (lowercase)
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


_YEAR_ANCHOR_TARGET_FIELDS = frozenset({
    "earn_rate_base",
    "base_earn_rate",
    "tier_thresholds",
    "point_value_cpp",
    "recent_changes_last_6_months",
    "redemption_thresholds",
    "app_store_rating",
    "play_store_rating",
    "app_ratings",
    "membership_count",
})

_YEAR_ANCHOR_SOURCE_TYPES = frozenset({
    "news",
    "valuation",
    "app_reviews",
    "forums",
    "forum",
    "competitors",
    "financial",
})


def _anchor_year_to_volatile_queries(queries: list[SearchQuery]) -> list[SearchQuery]:
    """Append the current year to queries targeting high-volatility or time-sensitive fields.

    This prevents search engines from surfacing stale SEO articles when the program
    being researched has recently changed its earn rates, tier thresholds, or app ratings.
    Queries that already contain a four-digit year are left unchanged.
    """
    year = str(datetime.now(timezone.utc).year)
    result: list[SearchQuery] = []
    for query in queries:
        needs_year = (
            query.source_type in _YEAR_ANCHOR_SOURCE_TYPES
            or any(f in _YEAR_ANCHOR_TARGET_FIELDS for f in query.target_fields)
        )
        if needs_year and not re.search(r"\b20\d{2}\b", query.query):
            words = query.query.split()
            if len(words) < 10:
                new_text = f"{query.query} {year}"
            else:
                new_text = " ".join(words[:9]) + f" {year}"
            query = query.model_copy(update={"query": new_text})
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
            "suffix": "trustpilot complaints review",
            "intent": "member sentiment",
            "target_fields": ["member_sentiment", "common_complaints"],
            "source_type": "forums",
        },
        {
            "suffix": "mobile app review rating",
            "intent": "digital experience and app ratings",
            "target_fields": ["app_ratings", "mobile_app", "personalization"],
            "source_type": "app_reviews",
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
                "suffix": "app reviews cashback value",
                "intent": "retail app and cashback value",
                "target_fields": ["app_store_rating", "cashback_value"],
                "source_type": "app_reviews",
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
    domain_lower = domain.lower()
    if "airline" in domain_lower:
        return ["award_chart", "alliance_partners", "elite_status", "mileage_valuation"]
    if "hotel" in domain_lower:
        return ["tier_structure", "elite_nights", "redemption_value", "transfer_partners"]
    if "bank" in domain_lower or "credit" in domain_lower:
        return ["transfer_partners", "lounge_access", "reward_rate", "points_value"]
    if "retail" in domain_lower or "commerce" in domain_lower:
        return ["cashback_value", "partner_ecosystem", "earn_mechanics", "expiry_policy"]
    return ["issuance_partners", "redemption_network", "partner_ecosystem", "earn_mechanics"]


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
