/**
 * Schema constants mirrored from `schemas.py` and `pipeline/schema_config.py`.
 *
 * SCHEMA_FIELD_PATHS is the authoritative full schema (drives SchemaCoverage.total_fields).
 * FOCUSED_SCHEMA_FIELD_PATHS is the narrower runtime extraction subset.
 */

export const SCHEMA_FIELD_PATHS = [
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
] as const;

export type FieldPath = (typeof SCHEMA_FIELD_PATHS)[number];

/** Narrow runtime extraction subset (schema_config.FOCUSED_SCHEMA_FIELD_PATHS). */
export const FOCUSED_SCHEMA_FIELD_PATHS: ReadonlySet<string> = new Set([
  "program_basics.program_name",
  "program_basics.brand",
  "program_basics.industry",
  "program_basics.program_type",
  "program_basics.geography",
  "program_basics.membership_count",
  "earn_mechanics.base_earn_rate",
  "earn_mechanics.bonus_categories",
  "earn_mechanics.non_transactional_earn",
  "burn_mechanics.redemption_options",
  "burn_mechanics.redemption_thresholds",
  "burn_mechanics.point_value_cpp",
  "burn_mechanics.expiry_policy",
  "tier_system.tier_names",
  "tier_system.qualification_criteria",
  "tier_system.tier_benefits",
  "tier_system.qualification_period",
  "partnerships.partner_names",
  "partnerships.partnership_type",
  "partnerships.details",
  "digital_experience.mobile_app_available",
  "digital_experience.app_ratings",
  "digital_experience.personalization_features",
  "digital_experience.gamification_features",
  "member_sentiment.ratings",
  "member_sentiment.common_praise",
  "member_sentiment.common_complaints",
  "member_sentiment.sources_checked",
  "competitive_position.key_differentiators",
  "competitive_position.weaknesses",
  "competitive_position.closest_competitors",
]);

export const HIGH_VOLATILITY_FIELDS: ReadonlySet<string> = new Set([
  "earn_mechanics.base_earn_rate",
  "earn_mechanics.earn_rate_unit",
  "tier_system.tier_thresholds",
  "burn_mechanics.point_value_cpp",
  "partnerships.partner_names",
  "digital_experience.app_ratings",
  "digital_experience.app_store_rating",
  "digital_experience.play_store_rating",
  "competitive_position.recent_changes_last_6_months",
]);

export const CATEGORY_ORDER = [
  "program_basics",
  "earn_mechanics",
  "burn_mechanics",
  "tier_system",
  "partnerships",
  "digital_experience",
  "member_sentiment",
  "competitive_position",
] as const;

export type Category = (typeof CATEGORY_ORDER)[number];

export const CATEGORY_LABELS: Record<Category, string> = {
  program_basics: "Program Basics",
  earn_mechanics: "Earn Mechanics",
  burn_mechanics: "Burn Mechanics",
  tier_system: "Tier System",
  partnerships: "Partnerships",
  digital_experience: "Digital Experience",
  member_sentiment: "Member Sentiment",
  competitive_position: "Competitive Position",
};

export function categoryOf(fieldPath: string): Category {
  return ((fieldPath ?? "").split(".")[0] || "") as Category;
}

export function leafOf(fieldPath: string): string {
  if (!fieldPath) return "";
  return fieldPath.split(".").slice(1).join(".");
}

/** Human-friendly label for a field path's leaf, e.g. "base_earn_rate" -> "Base earn rate". */
export function fieldLabel(fieldPath: string): string {
  if (!fieldPath) return "";
  const leaf = leafOf(fieldPath);
  if (!leaf) return fieldPath;
  const spaced = leaf.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function isHighVolatility(fieldPath: string): boolean {
  return HIGH_VOLATILITY_FIELDS.has(fieldPath);
}

export function volatilityFor(fieldPath: string): "high" | "low" {
  return isHighVolatility(fieldPath) ? "high" : "low";
}

export const FIELDS_BY_CATEGORY: Record<Category, string[]> = CATEGORY_ORDER.reduce(
  (acc, category) => {
    acc[category] = SCHEMA_FIELD_PATHS.filter(
      (path) => categoryOf(path) === category,
    );
    return acc;
  },
  {} as Record<Category, string[]>,
);

export const TOTAL_FIELDS = SCHEMA_FIELD_PATHS.length; // 59

/** The 9 UI pipeline stages (richer breakdown of the 7 backend LangGraph nodes). */
export const PIPELINE_STAGES = [
  { id: "input_validator", index: 1, label: "Input Validation", short: "Validate" },
  { id: "query_generator", index: 2, label: "Query Generation", short: "Queries" },
  { id: "retrieval", index: 3, label: "Retrieval", short: "Retrieve" },
  { id: "firecrawl_scraper", index: 4, label: "Scraping", short: "Scrape" },
  { id: "chunking", index: 5, label: "Chunking", short: "Chunk" },
  { id: "extraction", index: 6, label: "Extraction", short: "Extract" },
  { id: "claims", index: 7, label: "Claims & Conflicts", short: "Claims" },
  { id: "adjudication", index: 8, label: "Adjudication / Debate", short: "Debate" },
  { id: "output", index: 9, label: "Output", short: "Output" },
] as const;

export type StageId = (typeof PIPELINE_STAGES)[number]["id"];

export const STAGE_IDS = PIPELINE_STAGES.map((s) => s.id) as StageId[];

export function stageMeta(id: string) {
  return PIPELINE_STAGES.find((s) => s.id === id);
}
