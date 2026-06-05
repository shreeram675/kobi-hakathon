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
    "partnerships.partner_category",
    "partnerships.earn_details",
    "partnerships.burn_details",
    "partnerships.transfer_ratios",
    "partnerships.discontinued_partners",
    "digital_experience.mobile_app_available",
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
        "digital_experience.app_store_rating",
        "digital_experience.play_store_rating",
        "competitive_position.recent_changes_last_6_months",
    }
)


class KobieModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class ProgramIdentity(KobieModel):
    identity_id: str = Field(default_factory=lambda: new_id("identity"))
    raw_input: str
    program_name: str
    brand: str
    domain: str
    country_or_region: str | None = None
    confidence: float = Field(ge=0, le=1)
    status: Literal["resolved"] = "resolved"


class ClarificationOption(KobieModel):
    program_name: str
    brand: str
    domain: str


class ValidationResult(KobieModel):
    status: Literal["resolved", "needs_clarification", "rejected"]
    confidence: float = Field(ge=0, le=1)
    identity: ProgramIdentity | None = None
    possible_matches: list[ClarificationOption] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=3)
    reason: str | None = None

    @model_validator(mode="after")
    def resolved_requires_identity(self) -> "ValidationResult":
        if self.status == "resolved" and self.identity is None:
            raise ValueError("resolved validation requires identity")
        if self.status != "resolved" and self.identity is not None:
            raise ValueError("only resolved validation can include identity")
        return self


class SearchQuery(KobieModel):
    query_id: str = Field(default_factory=lambda: new_id("query"))
    query: str
    source_type: str


class QueryGenerationOutput(KobieModel):
    detected_category: str
    query_strategy_summary: str
    priority_fields: list[str] = Field(default_factory=list)
    queries: list[SearchQuery] = Field(default_factory=list, max_length=15)


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


class ConverseAnswer(KobieModel):
    answer: str
    status: ClaimStatus
    cited_claim_ids: list[str] = Field(default_factory=list)
    missing_field_paths: list[str] = Field(default_factory=list)


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
    query_generation_result: QueryGenerationOutput | None
    search_queries: list[SearchQuery]
    retrieved_pages: list[PageRef]
    sanitized_chunks: list[ChunkRef]
    extracted_claims: list[Claim]
    conflicts: list[ConflictRecord]
    adjudicated_claims: list[Claim]
    schema_coverage: SchemaCoverage
    data_quality: float
    final_brief: BriefOutput | None
    comparison_output: ComparisonOutput | None
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
        "query_generation_result": None,
        "search_queries": [],
        "retrieved_pages": [],
        "sanitized_chunks": [],
        "extracted_claims": [],
        "conflicts": [],
        "adjudicated_claims": [],
        "schema_coverage": SchemaCoverage(),
        "data_quality": 0.0,
        "final_brief": None,
        "comparison_output": None,
        "conversation_answer": None,
        "errors": [],
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def volatility_for_field(field_path: str) -> Volatility:
    return Volatility.HIGH if field_path in HIGH_VOLATILITY_FIELDS else Volatility.LOW
