/**
 * TypeScript mirror of the Python backend contracts in `schemas.py`.
 *
 * These types are the single source of truth for the frontend. They intentionally
 * mirror the pydantic models / TypedDict field-for-field so the polled
 * `AgentState` JSON deserialises with no surprises. Keep aligned with schemas.py.
 */

// ---- Enums (StrEnum in Python) ----

export type ClaimStatus =
  | "supported"
  | "conflicting"
  | "not_found/manual_review_needed"
  | "null"
  | "rejected_unsupported";

export type Volatility = "high" | "low";

export type RunMode = "single" | "compare" | "converse";

export type ValidationStatus = "resolved" | "needs_clarification" | "rejected";

export type ScrapeStatus = "success" | "failed" | "forbidden";

export type ExtractedFieldStatus = "EXTRACTED" | "NOT_FOUND" | "AMBIGUOUS";

export type FieldReportStatus =
  | "extracted"
  | "ambiguous"
  | "not_found"
  | "flagged";

export type ConflictResolution =
  | "auto_resolved"
  | "debate_required"
  | "manual_review_needed";

export type ComparisonOutcome =
  | "factual_mismatch"
  | "missing_in_a"
  | "missing_in_b"
  | "manual_review_needed"
  | "null"
  | "match";

// ---- Node / stage runtime status (UI-only, drives the pipeline graph) ----

export type StageStatus = "idle" | "running" | "done" | "error";

// ---- Identity & validation ----

export interface ProgramIdentity {
  identity_id: string;
  raw_input: string;
  program_name: string;
  brand: string;
  domain: string;
  country_or_region: string | null;
  confidence: number; // 0..1
  status: "resolved";
}

export interface ClarificationOption {
  program_name: string;
  brand: string;
  domain: string;
}

export interface ValidationResult {
  status: ValidationStatus;
  confidence: number; // 0..1
  identity: ProgramIdentity | null;
  possible_matches: ClarificationOption[];
  follow_up_questions: string[];
  reason: string | null;
}

// ---- Query generation ----

export interface SearchQuery {
  query_id: string;
  external_query_id: string | null;
  query: string;
  source_type: string;
  intent: string | null;
  target_fields: string[];
}

export interface QueryGenerationOutput {
  detected_category: string;
  resolved_corporate_parent: string | null;
  geography: string | null;
  query_strategy_summary: string;
  priority_fields: string[];
  estimated_web_coverage: number; // 0..1
  field_query_map: Record<string, string[]>;
  queries: SearchQuery[];
}

// ---- Retrieval ----

export interface RetrievedUrl {
  url: string;
  canonical_url: string;
  title: string | null;
  score: number; // 0..1
  query: string;
  query_id: string | null;
  external_query_id: string | null;
  source_type: string;
}

export interface RetrievalOutput {
  total_queries: number;
  requested_results_per_query: number;
  raw_result_count: number;
  unique_result_count: number;
  urls: RetrievedUrl[];
}

// ---- Scraping ----

export interface ScrapedUrlBlock {
  url: string;
  canonical_url: string;
  content: string | null;
  title: string | null;
  scrape_status: ScrapeStatus;
  error: string | null;
  is_fallback: boolean;
}

export interface FirecrawlScrapeOutput {
  total_urls: number;
  successful_scrapes: number;
  failed_scrapes: number;
  fallback_scrapes: number;
  blocks: ScrapedUrlBlock[];
}

// ---- Documents & chunking ----

export interface RawDocument {
  url: string;
  url_hash: string;
  content: string;
  word_count: number;
  query_id: string | null;
  entity_name: string | null;
  domain: string | null;
  retrieved_at: string;
  source_authority: number | null;
  metadata: Record<string, unknown>;
}

export interface SemanticChunk {
  chunk_id: string;
  chunk_text: string;
  source_url: string;
  target_fields: string[];
  source_type: string | null;
  /** Not in the pydantic model; populated by the chunker for token accounting. */
  token_count?: number;
}

// ---- Extraction ----

export interface ExtractedField {
  value: unknown | null;
  status: ExtractedFieldStatus;
  source_url: string | null;
  source_snippet: string | null;
  confidence: number | null;
}

export interface ExtractedObjectPacket {
  object_type: string;
  fields: Record<string, ExtractedField>;
  source_url: string;
  chunk_id: string;
  scope: Record<string, unknown>;
}

export interface NormalizedObjectPacket extends ExtractedObjectPacket {
  identity_hash: string;
  normalized_at: string;
}

export interface FieldReportEntry {
  field_path: string;
  category: string;
  status: FieldReportStatus;
  value: unknown | null;
  source_urls: string[];
  source_snippet: string | null;
  confidence: number | null;
  corroboration_count: number;
  rejected_alternatives?: Array<{ value: unknown; source_urls: string[]; reason: string }>;
}

export interface FieldReport {
  entity_name: string | null;
  generated_at: string;
  entries: FieldReportEntry[];
  extracted_count: number;
  ambiguous_count: number;
  not_found_count: number;
  flagged_count: number;
}

// ---- Claims & conflicts ----

export interface Claim {
  claim_id: string;
  run_id: string;
  field_path: string;
  value_json: unknown | null;
  status: ClaimStatus;
  source_url: string | null;
  access_date: string | null;
  quote: string | null;
  confidence: number; // 0..1
  volatility: Volatility;
}

export interface ConflictRecord {
  conflict_id: string;
  run_id: string;
  field_path: string;
  claim_ids: string[];
  score_gap: number; // >= 0
  resolution_status: ConflictResolution;
  judge_reason: string;
  value_a?: string | null;
  value_b?: string | null;
  url_a?: string | null;
  url_b?: string | null;
}

// ---- Adjudication / debate ----

export interface DebateRound {
  round: number;
  phase:
    | "opening"
    | "opening_b"
    | "cross"
    | "cross_b"
    | "evidence"
    | "final_decision";
  agent: string;
  argument: string;
}

export interface AdjudicatedClaim {
  conflict_id: string;
  field_path: string;
  resolution_status: ConflictResolution;
  winning_claim_id: string | null;
  decision: string;
  rounds: DebateRound[];
  confidence: number;
  value_a?: string | null;
  value_b?: string | null;
  url_a?: string | null;
  url_b?: string | null;
}

export interface HumanReviewItem {
  field_path: string;
  reason: string;
  claim_ids: string[];
  score_gap: number;
  flagged_at: string;
}

// ---- Output ----

export interface SchemaCoverage {
  total_fields: number;
  supported_fields: number;
  manual_review_fields: number;
  null_fields: number;
  rejected_fields: number;
}

export interface BriefOutput {
  brief_id: string;
  run_id: string;
  brief_text: string;
  cited_claim_ids: string[];
  word_count: number;
  entailment_passed: boolean;
  unsupported_sentences: string[];
}

export interface ComparisonItem {
  field_path: string;
  outcome: ComparisonOutcome;
  summary: string;
  claim_ids: string[];
}

export interface ComparisonOutput {
  comparison_id: string;
  run_id: string;
  program_a: string;
  program_b: string;
  items: ComparisonItem[];
}

export interface CategoryVerdict {
  category: string;
  label: string;
  winner: string;
  insight: string;
  source_urls?: string[];
}

export interface KeyDifferentiator {
  topic: string;
  insight: string;
  advantage: string;
  source_urls?: string[];
  rejected_note?: string | null;
}

export interface ProgramPersona {
  program: string;
  best_for: string;
}

export interface ProgramStrategicProfile {
  program: string;
  advantages: string[];
  gaps: string[];
}

export interface DifferentiationTheme {
  theme: string;
  summary: string;
  leader: string | null;
}

export interface ComparisonBrief {
  brief_id: string;
  run_id: string;
  programs: string[];
  overall_winner: string | null;
  executive_summary: string;
  category_verdicts: CategoryVerdict[];
  key_differentiators: KeyDifferentiator[];
  personas: ProgramPersona[];
  strategic_profiles: ProgramStrategicProfile[];
  differentiation_themes: DifferentiationTheme[];
  generated_at: string;
}

export interface ConverseAnswer {
  answer: string;
  status: ClaimStatus;
  cited_claim_ids: string[];
  missing_field_paths: string[];
  source_urls?: string[];
}

export interface PipelineError {
  stage: string;
  message: string;
  created_at: string;
}

// ---- Conversation turn (UI helper for converse thread) ----

export interface ConverseTurn {
  role: "user" | "assistant";
  message: string;
  answer?: ConverseAnswer;
  created_at: string;
}

// ---- The polled run state ----

export interface AgentState {
  run_id: string;
  mode: RunMode;
  user_input: string;

  validation_messages: Array<Record<string, string>>;
  validation_result?: ValidationResult | null;
  program_identity: ProgramIdentity | null;
  program_name: string | null;
  brand: string | null;
  domain: string | null;
  country_or_region: string | null;

  query_generation_result: QueryGenerationOutput | null;
  search_queries: SearchQuery[];

  retrieval_result: RetrievalOutput | null;
  retrieved_urls: RetrievedUrl[];

  firecrawl_result: FirecrawlScrapeOutput | null;
  scraped_blocks: ScrapedUrlBlock[];

  raw_documents?: RawDocument[];
  semantic_chunks?: SemanticChunk[];
  extraction_chunks?: SemanticChunk[];
  skipped_chunks?: SemanticChunk[];
  schema_config?: Record<string, unknown> | null;

  extracted_packets?: ExtractedObjectPacket[];
  normalized_packets?: NormalizedObjectPacket[];
  field_report?: FieldReport | null;

  extracted_claims: Claim[];
  conflicts: ConflictRecord[];
  adjudicated?: AdjudicatedClaim[];
  human_review_queue?: HumanReviewItem[];
  adjudicated_claims: Claim[];

  schema_coverage: SchemaCoverage;
  data_quality: number; // 0..1

  final_brief: BriefOutput | null;
  comparison_output: ComparisonOutput | null;
  comparison_brief: ComparisonBrief | null;
  conversation_answer: ConverseAnswer | null;

  errors: PipelineError[];
  created_at: string;
  updated_at: string;

  // ---- UI-runtime additions (not in the pydantic AgentState) ----
  /** Per-UI-stage status map, keyed by stage id. */
  stage_status: Record<string, StageStatus>;
  /** Whichever stage the pipeline is currently working. */
  active_stage: string | null;
  /** Coarse lifecycle of the whole run. */
  status: "running" | "done" | "error" | "clarification_needed" | "cancelled";
  /** Conversation history for single/converse mode (grounded in that run's data). */
  conversation?: ConverseTurn[];
  /** Conversation history for comparison runs (grounded in comparison brief + all program data). */
  comparison_conversation?: ConverseTurn[];
  /** compare mode: the second program's full state (UI-only convenience). */
  compare_b?: AgentState | null;
  /** compare mode: full multi-program queue info (available for all comparison runs). */
  comparison_run?: ComparisonRunInfo | null;
  /** Live API cost ledger for the run. */
  cost_report?: CostReport | null;
}

// ---- Multi-program comparison run tracking ----

export type ProgramStatus = "pending" | "running" | "done" | "error";

export interface ComparisonRunInfo {
  programs: string[];
  current_program_index: number;
  total_programs: number;
  program_statuses: ProgramStatus[];
  /** Serialised AgentState for each completed program (null while pending/running). */
  program_states: Array<AgentState | null>;
  /** Per-program stage status snapshot (available once program completes). */
  program_stage_statuses: Array<Record<string, StageStatus>>;
}

// ---- API payloads ----

export interface CreateRunBody {
  user_input: string;
  mode: RunMode;
  /** compare mode: optional explicit second program prompt (legacy 2-program). */
  user_input_b?: string;
  /** compare mode: explicit list of programs (supersedes user_input_b when provided). */
  programs?: string[];
  /** Skip cache lookup and always run the full pipeline. */
  force_fresh?: boolean;
}

export interface CacheCheckResult {
  found: boolean;
  program_name?: string;
  brand?: string;
  country_or_region?: string | null;
  run_date?: string;
  run_datetime?: string;
  run_timestamp?: string;
  age_days?: number;
}

export interface CompareCacheCheckItem extends CacheCheckResult {
  program: string;
}

export interface RunHistoryEntry {
  run_id: string;
  user_input: string;
  mode: RunMode;
  program_name?: string | null;
  data_quality: number;
  status: "running" | "done" | "error" | "clarification_needed" | "cancelled";
  created_at: string;
  source?: "db" | "live";
}

export interface CreateRunResponse {
  run_id: string;
}

export interface RunSummary {
  run_id: string;
  user_input: string;
  mode: RunMode;
  data_quality: number;
  status: "running" | "done" | "error" | "clarification_needed" | "cancelled";
  created_at: string;
}

export interface ConverseRequest {
  message: string;
}

// ---- Cost tracking ----

export interface CostReportLine {
  provider: string;
  stage: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  usd_cost: number;
}

export interface CostReport {
  lines: CostReportLine[];
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_usd_cost: number;
}
