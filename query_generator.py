"""Gemini-powered Tavily query generation."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Protocol

import requests

from providers import provider_for_stage
from schemas import ProgramIdentity, QueryGenerationOutput, SearchQuery


QUERY_GENERATOR_SYSTEM_PROMPT = """
You are an expert Loyalty Program Research Query Generator.

Your objective is to generate the most effective Tavily search queries for
extracting information about a loyalty program while maximizing coverage of the
required schema.

INPUT
You receive a validated loyalty program identity:
{
  "program_name": "...",
  "brand": "...",
  "domain": "...",
  "country_or_region": "..."
}

REQUIRED SCHEMA
1. Program Basics: Name, Brand, Industry, Type, Geography, Membership Count
2. Earn Mechanics: Base Earn Rate, Bonus Categories, Non-Transactional Earn
3. Burn Mechanics: Redemption Options, Redemption Thresholds, Point Value, Expiry Policy
4. Tier System: Tier Names, Qualification Criteria, Benefits, Qualification Period
5. Partnerships: Partner Names, Partnership Type, Partnership Details
6. Digital Experience: Mobile App, App Ratings, Personalization, Gamification
7. Member Sentiment: Ratings, Common Praise, Common Complaints, Sources Checked
8. Competitive Position: Key Differentiators, Weaknesses, Closest Competitors

FIELD DIFFICULTY
Easy fields: Name, Brand, Industry, Type, Geography, Tier Names, Benefits,
Mobile App, Redemption Options, Expiry Policy.

Difficult fields: Membership Count, Base Earn Rate, Bonus Categories,
Qualification Criteria, Qualification Period, Redemption Thresholds, App
Ratings, Partner Names.

Very difficult fields: Point Value, Non-Transactional Earn, Partnership Type,
Partnership Details, Personalization, Gamification, Member Sentiment, Common
Praise, Common Complaints, Key Differentiators, Weaknesses, Closest Competitors.

QUERY RULES
1. Generate at most 15 Tavily search queries.
2. Prioritize difficult and very difficult fields.
3. Every query should target multiple schema fields whenever possible.
4. Use category-specific terminology from the validated domain.
5. Prefer official sources for factual information.
6. Prefer community and review sources for sentiment analysis.
7. Generate discovery-style queries for fields that are rarely published directly.
8. Minimize overlap and redundancy.
9. Queries should uncover hidden rules, valuation data, partner ecosystems, user
   sentiment, and competitive positioning.
10. Do not generate unsupported facts. Queries are search strings only.

SOURCE PREFERENCES
For factual information: official website, program FAQ, terms and conditions,
benefits pages, partner pages, annual reports, investor presentations.

For sentiment and competitive analysis: Reddit, FlyerTalk, Trustpilot, Google
Play, Apple App Store, loyalty blogs, comparison articles, industry reports.

OUTPUT FORMAT
Return ONLY valid JSON:
{
  "detected_category": "<category>",
  "query_strategy_summary": "<brief explanation>",
  "priority_fields": ["<field>", "<field>"],
  "queries": [
    {"query": "...", "source_type": "official"},
    {"query": "...", "source_type": "terms"},
    {"query": "...", "source_type": "partners"}
  ]
}

Allowed source_type values: official, terms, faq, partners, app_reviews, news,
forums, sentiment, competitors, valuation, reports.
""".strip()


class QueryGeneratorClient(Protocol):
    def complete_json(self, prompt: str) -> dict[str, Any]:
        """Return the query generator response parsed as JSON."""


class GeminiQueryGeneratorClient:
    """Google Gemini generateContent REST client."""

    def __init__(self, max_retries: int = 3, retry_sleep_seconds: float = 1.0) -> None:
        provider = provider_for_stage("query_generator")
        self.api_base = (provider.api_base or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.api_key = provider.api_key
        self.model = provider.resolved_model or "gemini-2.5-flash"
        self.max_retries = max_retries
        self.retry_sleep_seconds = retry_sleep_seconds

    def complete_json(self, prompt: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("Query generator is not configured. Set GEMINI_API_KEY.")

        response = self._post_with_retries(prompt)
        payload = response.json()
        content = payload["candidates"][0]["content"]["parts"][0]["text"]
        return parse_json_content(content)

    def _post_with_retries(self, prompt: str) -> requests.Response:
        last_error: requests.HTTPError | None = None
        for attempt in range(self.max_retries + 1):
            response = requests.post(
                f"{self.api_base}/models/{self.model}:generateContent",
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=60,
            )
            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                return response

            last_error = requests.HTTPError(
                f"Gemini query generator is temporarily unavailable "
                f"({response.status_code}). Try again in a moment.",
                response=response,
            )
            if attempt < self.max_retries:
                time.sleep(self.retry_sleep_seconds * (attempt + 1))

        if last_error:
            raise last_error
        raise RuntimeError("Gemini query generator request failed.")


def generate_queries(
    identity: ProgramIdentity,
    client: QueryGeneratorClient | None = None,
) -> QueryGenerationOutput:
    generator = client or GeminiQueryGeneratorClient()
    payload = generator.complete_json(build_query_generator_prompt(identity))
    return parse_query_generation_output(payload)


def build_query_generator_prompt(identity: ProgramIdentity) -> str:
    return (
        f"{QUERY_GENERATOR_SYSTEM_PROMPT}\n\n"
        "VALIDATED PROGRAM IDENTITY\n"
        f"{json.dumps(identity.model_dump(), indent=2, ensure_ascii=True)}"
    )


def parse_query_generation_output(payload: dict[str, Any]) -> QueryGenerationOutput:
    queries: list[SearchQuery] = []
    for item in payload.get("queries", [])[:15]:
        if isinstance(item, str):
            query = item.strip()
            source_type = infer_source_type(query)
        elif isinstance(item, dict):
            query = str(item.get("query") or "").strip()
            source_type = str(item.get("source_type") or infer_source_type(query)).strip()
        else:
            continue

        if query:
            queries.append(SearchQuery(query=query, source_type=source_type or "official"))

    return QueryGenerationOutput(
        detected_category=str(payload.get("detected_category") or "Other"),
        query_strategy_summary=str(payload.get("query_strategy_summary") or "Generated Tavily query plan."),
        priority_fields=[str(field) for field in payload.get("priority_fields", [])],
        queries=queries,
    )


def parse_json_content(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def infer_source_type(query: str) -> str:
    lowered = query.lower()
    if "terms" in lowered or "conditions" in lowered:
        return "terms"
    if "faq" in lowered:
        return "faq"
    if "partner" in lowered or "transfer" in lowered:
        return "partners"
    if "app" in lowered or "rating" in lowered or "play store" in lowered:
        return "app_reviews"
    if "reddit" in lowered or "forum" in lowered or "complaint" in lowered:
        return "forums"
    if "competitor" in lowered or "comparison" in lowered:
        return "competitors"
    if "value" in lowered or "valuation" in lowered:
        return "valuation"
    if "news" in lowered or "recent" in lowered:
        return "news"
    return "official"
