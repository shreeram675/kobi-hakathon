"""Shared contracts for the Kobie Phase 2 agent.

The ArcGuide requires these models to stay aligned with SQLite persistence and
graph state. Keep this module dependency-free from other local modules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, NotRequired, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    CONFLICTING = "conflicting"
    NOT_FOUND = "not_found/manual_review_needed"
    NULL = "null"
    REJECTED_UNSUPPORTED = "rejected_unsupported"


class Volatility(StrEnum):
    HIGH = "high"
    LOW = "low"


class RunMode(StrEnum):
    SINGLE = "single"
    COMPARE = "compare"
    CONVERSE = "converse"


SCHEMA_FIELD_PATHS: tuple[str, ...] = (
    "program_basics.program_name",
    "program_basics.brand",
    "program_basics.industry",
    "program_basics.program_type",
    "program_basics.geography",
    "program_basics.membership_count",
    "program_basics.ownership_or_parent_company",
    "program_basics.launch_or_rebrand_history",
    "earn_mechanics.base_earn_rate",
    "earn_mechanics.earn_rate_unit",
    "earn_mechanics.bonus_categories",
    "earn_mechanics.co_brand_card_earn",
    "earn_mechanics.partner_earn",
    "earn_mechanics.non_transactional_earn",
    "earn_mechanics.earning_exclusions",
    "burn_mechanics.redemption_options",
    "burn_mechanics.redemption_thresholds",
    "burn_mechanics.point_value_cpp",
    "burn_mechanics.cash_equivalent_value",
    "burn_mechanics.expiry_policy",
    "burn_mechanics.blackout_or_capacity_rules",
    "burn_mechanics.transfer_options",
    "tier_system.tier_names",
    "tier_system.qualification_criteria",
    "tier_system.tier_thresholds",
    "tier_system.qualification_period",
    "tier_system.tier_benefits",
    "tier_system.soft_landing_or_status_match",
    "tier_system.elite_bonus",
    "partnerships.partner_names",
    "partnerships.partnership_type",
    "partnerships.details",
    "partnerships.partner_category",
    "partnerships.earn_details",
    "partnerships.burn_details",
    "partnerships.transfer_ratios",
    "partnerships.discontinued_partners",
    "digital_experience.mobile_app_available",
    "digital_experience.app_ratings",
    "digital_experience.app_store_rating",
    "digital_experience.play_store_rating",
    "digital_experience.personalization_features",
    "digital_experience.gamification_features",
    "digital_experience.digital_wallet_or_card_linking",
    "digital_experience.app_pain_points",
    "member_sentiment.ratings",
    "member_sentiment.common_praise",
    "member_sentiment.common_complaints",
    "member_sentiment.complaint_frequency",
    "member_sentiment.sources_checked",
    "member_sentiment.review_sources_checked",
    "member_sentiment.forum_sources_checked",
    "member_sentiment.sentiment_summary",
    "competitive_position.key_differentiators",
    "competitive_position.weaknesses",
    "competitive_position.closest_competitors",
    "competitive_position.value_positioning",
    "competitive_position.strategic_risks",
    "competitive_position.recent_changes_last_6_months",
)


HIGH_VOLATILITY_FIELDS = frozenset(
    {
        "earn_mechanics.base_earn_rate",
        "earn_mechanics.earn_rate_unit",
        "tier_system.tier_thresholds",
        "burn_mechanics.point_value_cpp",
        "partnerships.partner_names",
        "digital_experience.app_ratings",
        "digital_experience.app_store_rating",
        "digital_experience.play_store_rating",
        "competitive_position.recent_changes_last_6_months",
    }
)


class KobieModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class SearchContext(KobieModel):
    program_type: str | None = None
    entity_disambiguation: str | None = None


class ProgramIdentity(KobieModel):
    identity_id: str = Field(default_factory=lambda: new_id("identity"))
    raw_input: str
    program_name: str
    brand: str
    domain: str
    country_or_region: str | None = None
    program_subtype: str | None = None
    confidence: float = Field(ge=0, le=1)
    status: Literal["resolved"] = "resolved"
    official_domain: str | None = None
    noise_exclude_terms: list[str] = Field(default_factory=list)
    search_context: SearchContext | None = None


class ClarificationOption(KobieModel):
    program_name: str
    brand: str
    domain: str
    official_domain: str | None = None


class ValidationResult(KobieModel):
    status: Literal["resolved", "needs_clarification", "rejected"]
    confidence: float = Field(ge=0, le=1)
    identity: ProgramIdentity | None = None
    possible_matches: list[ClarificationOption] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=3)
    reason: str | None = None
    missing_info: str | None = None

    @model_validator(mode="after")
    def resolved_requires_identity(self) -> "ValidationResult":
        if self.status == "resolved" and self.identity is None:
            raise ValueError("resolved validation requires identity")
        if self.status != "resolved" and self.identity is not None:
            raise ValueError("only resolved validation can include identity")
        return self


class SearchQuery(KobieModel):
    query_id: str = Field(default_factory=lambda: new_id("query"))
    external_query_id: str | None = None
    query: str
    source_type: str
    intent: str | None = None
    target_fields: list[str] = Field(default_factory=list)


class QueryGenerationOutput(KobieModel):
    detected_category: str
    resolved_corporate_parent: str | None = None
    geography: str | None = None
    query_strategy_summary: str
    priority_fields: list[str] = Field(default_factory=list)
    estimated_web_coverage: float = Field(default=0.0, ge=0, le=1)
    field_query_map: dict[str, list[str]] = Field(default_factory=dict)
    queries: list[SearchQuery] = Field(default_factory=list, max_length=15)


class RetrievedUrl(KobieModel):
    url: str
    canonical_url: str
    title: str | None = None
    score: float = Field(ge=0, le=1)
    query: str
    query_id: str | None = None
    external_query_id: str | None = None
    source_type: str


class RetrievalOutput(KobieModel):
    total_queries: int
    requested_results_per_query: int = 5
    raw_result_count: int
    unique_result_count: int
    urls: list[RetrievedUrl] = Field(default_factory=list)


class ScrapedUrlBlock(KobieModel):
    url: str
    canonical_url: str
    content: str | None = None
    title: str | None = None
    published_date: str | None = None
    scrape_status: Literal["success", "failed", "forbidden"] = "success"
    error: str | None = None


class FirecrawlScrapeOutput(KobieModel):
    total_urls: int
    successful_scrapes: int
    failed_scrapes: int
    blocks: list[ScrapedUrlBlock] = Field(default_factory=list)


class RawDocument(KobieModel):
    """Raw post-Firecrawl document persisted before chunking."""

    url: str
    url_hash: str
    content: str
    word_count: int = Field(ge=0)
    query_id: str | None = None
    entity_name: str | None = None
    domain: str | None = None
    retrieved_at: str = Field(default_factory=now_iso)
    source_authority: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticChunk(KobieModel):
    """Domain-agnostic chunk prepared for structured extraction."""

    chunk_id: str
    chunk_text: str
    source_url: str
    target_fields: list[str] = Field(default_factory=list)
    source_type: str | None = None
    # Traceability: which search query produced the document this chunk came from,
    # and the ordinal position of this chunk within that document.
    query_id: str | None = None
    chunk_index: int | None = None


class ExtractedField(KobieModel):
    """Single schema field extracted from explicit source evidence."""

    value: Any | None = None
    status: Literal["EXTRACTED", "NOT_FOUND", "AMBIGUOUS"]
    source_url: str | None = None
    source_snippet: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ExtractedObjectPacket(KobieModel):
    """Runtime-schema object produced by the Gemini extraction stage."""

    object_type: str
    fields: dict[str, ExtractedField] = Field(default_factory=dict)
    source_url: str
    chunk_id: str
    scope: dict[str, Any] = Field(default_factory=dict)


class NormalizedObjectPacket(ExtractedObjectPacket):
    """Normalized object packet with deterministic or fallback identity hash."""

    identity_hash: str
    normalized_at: str = Field(default_factory=now_iso)


class FieldReportEntry(KobieModel):
    """Per-field aggregation of extracted evidence with source attribution."""

    field_path: str
    category: str
    status: Literal["extracted", "ambiguous", "not_found", "flagged"]
    value: Any | None = None
    source_urls: list[str] = Field(default_factory=list)
    source_snippet: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    corroboration_count: int = Field(default=0, ge=0)
    # Alternative values that were present in the data but overruled (lower confidence/corroboration
    # or lost in adjudication debate). Each entry: {value, source_urls, reason}.
    rejected_alternatives: list[dict[str, Any]] = Field(default_factory=list)
    # All simultaneously-valid values when conflict_type is not "contradictory".
    # Each entry: {value, source_url, context}.
    all_values: list[dict[str, Any]] | None = Field(default=None)
    # How the conflict was resolved: "contradictory" (one winner), "complementary" (both valid),
    # "range" (earn-rate span), "union" (partner-list merge), "recency" (latest date), "majority_vote".
    conflict_type: str | None = None


class FieldReport(KobieModel):
    """Final per-field output: every schema field with value, sources, and status."""

    entity_name: str | None = None
    generated_at: str = Field(default_factory=now_iso)
    entries: list[FieldReportEntry] = Field(default_factory=list)
    extracted_count: int = Field(default=0, ge=0)
    ambiguous_count: int = Field(default=0, ge=0)
    not_found_count: int = Field(default=0, ge=0)
    flagged_count: int = Field(default=0, ge=0)


class PageRef(KobieModel):
    page_id: str = Field(default_factory=lambda: new_id("page"))
    source_id: str | None = None
    source_url: str
    title: str | None = None
    cleaned_text: str
    token_count: int = Field(ge=0)
    fetched_at: str = Field(default_factory=now_iso)
    source_type: str = "unknown"


class ChunkRef(KobieModel):
    chunk_id: str = Field(default_factory=lambda: new_id("chunk"))
    page_id: str
    source_url: str
    chunk_index: int = Field(ge=0)
    text: str
    token_count: int = Field(ge=0)


class Claim(KobieModel):
    claim_id: str = Field(default_factory=lambda: new_id("claim"))
    run_id: str
    field_path: str
    value_json: Any | None = None
    status: ClaimStatus
    source_url: str | None = None
    access_date: str | None = None
    quote: str | None = None
    confidence: float = Field(ge=0, le=1)
    volatility: Volatility

    @field_validator("field_path")
    @classmethod
    def field_path_known(cls, value: str) -> str:
        if value not in SCHEMA_FIELD_PATHS:
            raise ValueError(f"unknown field_path: {value}")
        return value

    @model_validator(mode="after")
    def supported_requires_source(self) -> "Claim":
        if self.status == ClaimStatus.SUPPORTED:
            if not self.source_url or not self.access_date:
                raise ValueError("supported claims require source_url and access_date")
        if self.status == ClaimStatus.REJECTED_UNSUPPORTED and self.confidence > 0:
            raise ValueError("rejected unsupported claims must have zero confidence")
        return self


class ConflictRecord(KobieModel):
    conflict_id: str = Field(default_factory=lambda: new_id("conflict"))
    run_id: str
    field_path: str
    claim_ids: list[str]
    score_gap: float = Field(ge=0)
    resolution_status: Literal["auto_resolved", "debate_required", "manual_review_needed"]
    judge_reason: str


class SchemaCoverage(KobieModel):
    total_fields: int = len(SCHEMA_FIELD_PATHS)
    supported_fields: int = 0
    manual_review_fields: int = 0
    null_fields: int = 0
    rejected_fields: int = 0


class BriefOutput(KobieModel):
    brief_id: str = Field(default_factory=lambda: new_id("brief"))
    run_id: str
    brief_text: str
    cited_claim_ids: list[str] = Field(default_factory=list)
    word_count: int
    entailment_passed: bool = False
    unsupported_sentences: list[str] = Field(default_factory=list)


class ComparisonItem(KobieModel):
    field_path: str
    outcome: Literal["factual_mismatch", "missing_in_a", "missing_in_b", "manual_review_needed", "null", "match"]
    summary: str
    claim_ids: list[str] = Field(default_factory=list)


class ComparisonOutput(KobieModel):
    comparison_id: str = Field(default_factory=lambda: new_id("comparison"))
    run_id: str
    program_a: str
    program_b: str
    items: list[ComparisonItem] = Field(default_factory=list)


class CategoryVerdict(KobieModel):
    category: str
    label: str
    winner: str  # program name or "Tie" or "Insufficient data"
    insight: str
    source_urls: list[str] = Field(default_factory=list)


class KeyDifferentiator(KobieModel):
    topic: str
    insight: str
    advantage: str  # program name that wins here
    source_urls: list[str] = Field(default_factory=list)
    # Describes the value that was rejected/overruled for this differentiator, if applicable.
    rejected_note: str | None = None


class ProgramPersona(KobieModel):
    program: str
    best_for: str


class ProgramStrategicProfile(KobieModel):
    program: str
    advantages: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class DifferentiationTheme(KobieModel):
    theme: str
    summary: str
    leader: str | None = None


class ComparisonBrief(KobieModel):
    brief_id: str = Field(default_factory=lambda: new_id("compbrief"))
    run_id: str
    programs: list[str]
    overall_winner: str | None = None
    executive_summary: str
    category_verdicts: list[CategoryVerdict] = Field(default_factory=list)
    key_differentiators: list[KeyDifferentiator] = Field(default_factory=list)
    personas: list[ProgramPersona] = Field(default_factory=list)
    strategic_profiles: list[ProgramStrategicProfile] = Field(default_factory=list)
    differentiation_themes: list[DifferentiationTheme] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)


class ConverseAnswer(KobieModel):
    answer: str
    status: ClaimStatus
    cited_claim_ids: list[str] = Field(default_factory=list)
    missing_field_paths: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class PipelineError(KobieModel):
    stage: str
    message: str
    created_at: str = Field(default_factory=now_iso)


class AgentState(TypedDict):
    run_id: str
    mode: Literal["single", "compare", "converse"]
    user_input: str
    validation_messages: list[dict[str, str]]
    validation_result: NotRequired[ValidationResult | None]
    program_identity: ProgramIdentity | None
    program_name: str | None
    brand: str | None
    domain: str | None
    country_or_region: str | None
    program_subtype: NotRequired[str | None]
    query_generation_result: QueryGenerationOutput | None
    search_queries: list[SearchQuery]
    retrieval_result: RetrievalOutput | None
    retrieved_urls: list[RetrievedUrl]
    firecrawl_result: FirecrawlScrapeOutput | None
    scraped_blocks: list[ScrapedUrlBlock]
    additional_blocks: NotRequired[list[ScrapedUrlBlock]]
    raw_documents: NotRequired[list[RawDocument]]
    semantic_chunks: NotRequired[list[SemanticChunk]]
    extraction_chunks: NotRequired[list[SemanticChunk]]
    skipped_chunks: NotRequired[list[SemanticChunk]]
    schema_config: NotRequired[dict[str, Any] | None]
    extracted_packets: NotRequired[list[ExtractedObjectPacket]]
    normalized_packets: NotRequired[list[NormalizedObjectPacket]]
    prefetched_app_ratings: NotRequired[NormalizedObjectPacket | None]
    field_report: NotRequired[FieldReport | None]
    retrieved_pages: list[PageRef]
    sanitized_chunks: list[ChunkRef]
    extracted_claims: list[Claim]
    conflicts: list[ConflictRecord | dict[str, Any]]
    adjudicated: NotRequired[list[dict[str, Any]]]
    human_review_queue: NotRequired[list[dict[str, Any]]]
    adjudicated_claims: list[Claim]
    schema_coverage: SchemaCoverage
    data_quality: float
    final_brief: BriefOutput | None
    comparison_output: ComparisonOutput | None
    comparison_brief: ComparisonBrief | None
    conversation_answer: ConverseAnswer | None
    errors: list[PipelineError]
    created_at: str
    updated_at: str


def build_initial_state(user_input: str, mode: RunMode = RunMode.SINGLE) -> AgentState:
    timestamp = now_iso()
    return {
        "run_id": new_id("run"),
        "mode": mode.value,
        "user_input": user_input,
        "validation_messages": [],
        "validation_result": None,
        "program_identity": None,
        "program_name": None,
        "brand": None,
        "domain": None,
        "country_or_region": None,
        "program_subtype": None,
        "query_generation_result": None,
        "search_queries": [],
        "retrieval_result": None,
        "retrieved_urls": [],
        "firecrawl_result": None,
        "scraped_blocks": [],
        "raw_documents": [],
        "semantic_chunks": [],
        "extraction_chunks": [],
        "skipped_chunks": [],
        "schema_config": None,
        "extracted_packets": [],
        "normalized_packets": [],
        "field_report": None,
        "retrieved_pages": [],
        "sanitized_chunks": [],
        "extracted_claims": [],
        "conflicts": [],
        "adjudicated": [],
        "human_review_queue": [],
        "adjudicated_claims": [],
        "schema_coverage": SchemaCoverage(),
        "data_quality": 0.0,
        "final_brief": None,
        "comparison_output": None,
        "comparison_brief": None,
        "conversation_answer": None,
        "errors": [],
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def volatility_for_field(field_path: str) -> Volatility:
    return Volatility.HIGH if field_path in HIGH_VOLATILITY_FIELDS else Volatility.LOW
