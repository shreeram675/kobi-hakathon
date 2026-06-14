import type { StageId } from "./schema";
import { pct } from "./format";
import type { AgentState } from "./types";

/** A compact headline metric per pipeline stage, for the graph nodes. */
export function stageStat(
  state: AgentState,
  stage: StageId,
): { value: string; label: string } | null {
  const done = state.stage_status?.[stage] === "done";
  if (!done) return null;

  switch (stage) {
    case "input_validator":
      return state.validation_result
        ? { value: pct(state.validation_result.confidence), label: "confidence" }
        : null;
    case "query_generator":
      return { value: String(state.search_queries.length), label: "queries" };
    case "retrieval":
      return {
        value: String(state.retrieval_result?.unique_result_count ?? 0),
        label: "unique URLs",
      };
    case "firecrawl_scraper":
      return {
        value: String(state.firecrawl_result?.successful_scrapes ?? 0),
        label: "scraped",
      };
    case "chunking":
      return {
        value: String((state.extraction_chunks ?? []).length),
        label: "chunks",
      };
    case "extraction":
      return {
        value: String(state.field_report?.extracted_count ?? 0),
        label: "fields",
      };
    case "claims":
      return { value: String(state.extracted_claims.length), label: "claims" };
    case "adjudication":
      return {
        value: String((state.adjudicated ?? []).length),
        label: "debates",
      };
    case "output":
      return { value: pct(state.data_quality), label: "data quality" };
    default:
      return null;
  }
}
