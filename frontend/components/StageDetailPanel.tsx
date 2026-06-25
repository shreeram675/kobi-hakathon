"use client";

import { useEffect } from "react";
import { BadgeCheck, FileText, Quote } from "lucide-react";
import { StageSection } from "./StageSection";
import { StatRow } from "./StatRow";
import { MetricCard } from "./MetricCard";
import { Badge } from "@/components/ui/badge";
import { AlertBanner } from "./AlertBanner";
import { QueryList } from "./QueryList";
import { SchemaFieldTable } from "./SchemaFieldTable";
import { ClaimsTable } from "./ClaimsTable";
import { ConflictGrid } from "./ConflictCard";
import { DebateTimeline } from "./DebateTimeline";
import { HumanReviewQueue } from "./HumanReviewQueue";
import { SourcePill } from "./SourcePill";
import { CoverageRing } from "./charts/CoverageRing";
import { DataQualityGauge } from "./charts/DataQualityGauge";
import { Donut } from "./charts/Donut";
import { SourceTypePie } from "./charts/SourceTypePie";
import { UrlScoreHistogram } from "./charts/UrlScoreHistogram";
import { TokenBarChart } from "./charts/TokenBarChart";
import { FieldCoverageStackedBar } from "./charts/FieldCoverageStackedBar";
import { ComparisonBars } from "./charts/ComparisonBars";
import { TOKENS } from "@/lib/colors";
import { compact, estimateTokens, renderValue, truncate } from "@/lib/format";
import type { StageId } from "@/lib/schema";
import type { AgentState, StageStatus } from "@/lib/types";

function status(state: AgentState, id: StageId): StageStatus {
  return (state.stage_status?.[id] ?? "idle") as StageStatus;
}

function KeyVal({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-[8px] border border-line bg-gradient-to-b from-soft-grey/40 to-white px-3 py-2.5">
      <p className="text-[9.5px] font-bold uppercase tracking-[0.1em] text-ink/35">
        {label}
      </p>
      <p className="mt-1 text-[13px] font-semibold text-ink leading-tight">{value ?? <span className="text-ink/30 font-normal">—</span>}</p>
    </div>
  );
}

export function StageDetailPanel({
  state,
  focusedStage,
}: {
  state: AgentState;
  focusedStage: StageId | null;
}) {
  useEffect(() => {
    if (!focusedStage) return;
    const el = document.getElementById(`stage-${focusedStage}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focusedStage]);

  const tokensTotal = (state.semantic_chunks ?? []).reduce(
    (s, c) => s + (c.token_count ?? estimateTokens(c.chunk_text)),
    0,
  );
  const extractionChunks = state.extraction_chunks ?? [];
  const avgTokens = extractionChunks.length
    ? Math.round(
        extractionChunks.reduce(
          (s, c) => s + (c.token_count ?? estimateTokens(c.chunk_text)),
          0,
        ) / extractionChunks.length,
      )
    : 0;

  return (
    <div className="space-y-7">
      {/* ---- 1. INPUT VALIDATION ---- */}
      <StageSection stageId="input_validator" status={status(state, "input_validator")}>
        {state.validation_result && (
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
            <div className="min-w-0 flex-1 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  tone={
                    state.validation_result.status === "resolved"
                      ? "green"
                      : state.validation_result.status === "rejected"
                        ? "red"
                        : "amber"
                  }
                  dot
                >
                  {state.validation_result.status.replace(/_/g, " ")}
                </Badge>
                {state.program_identity && (
                  <span className="text-sm font-semibold text-navy">
                    {state.program_identity.program_name}
                  </span>
                )}
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <KeyVal label="Program name" value={state.program_name} />
                <KeyVal label="Brand" value={state.brand} />
                <KeyVal label="Domain" value={state.domain} />
                <KeyVal label="Country / region" value={state.country_or_region} />
              </div>
            </div>
            <div className="shrink-0 self-center">
              <DataQualityGauge
                value={state.validation_result.confidence}
                label="Identity confidence"
                size={160}
              />
            </div>
          </div>
        )}
      </StageSection>

      {/* ---- 2. QUERY GENERATION ---- */}
      <StageSection stageId="query_generator" status={status(state, "query_generator")}>
        {state.query_generation_result && (
          <div className="space-y-4">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
              <div className="min-w-0 flex-1 grid gap-2 sm:grid-cols-2">
                <KeyVal label="Detected category" value={state.query_generation_result.detected_category} />
                <KeyVal label="Corporate parent" value={state.query_generation_result.resolved_corporate_parent} />
                <KeyVal label="Geography" value={state.query_generation_result.geography} />
                <KeyVal
                  label="Priority fields"
                  value={(state.query_generation_result.priority_fields ?? []).length}
                />
              </div>
              <div className="shrink-0 self-center">
                <DataQualityGauge
                  value={state.query_generation_result.estimated_web_coverage}
                  label="Est. web coverage"
                  size={160}
                />
              </div>
            </div>
            <p className="rounded-md border border-line bg-soft-grey/30 px-3 py-2 text-xs leading-relaxed text-ink/70">
              {state.query_generation_result.query_strategy_summary}
            </p>
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink/45">
                {(state.search_queries ?? []).length} queries by source type
              </p>
              <QueryList queries={state.search_queries} />
            </div>
          </div>
        )}
      </StageSection>

      {/* ---- 3. RETRIEVAL ---- */}
      <StageSection stageId="retrieval" status={status(state, "retrieval")}>
        {state.retrieval_result && (
          <div className="space-y-4">
            <StatRow
              items={[
                { label: "Total queries", value: state.retrieval_result.total_queries, tone: "navy" },
                { label: "Results / query", value: state.retrieval_result.requested_results_per_query, tone: "teal", hint: "requested" },
                { label: "Raw results", value: state.retrieval_result.raw_result_count, tone: "blue" },
                { label: "Unique URLs", value: state.retrieval_result.unique_result_count, tone: "green", hint: "post-deduplication" },
              ]}
            />
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <div className="rounded-card border border-line p-3">
                <p className="mb-2 text-xs font-semibold text-ink/55">Raw vs unique</p>
                <ComparisonBars
                  rows={[
                    { label: "Raw results", value: state.retrieval_result.raw_result_count, color: TOKENS.blue },
                    { label: "Unique URLs", value: state.retrieval_result.unique_result_count, color: TOKENS.green },
                  ]}
                />
              </div>
              <div className="rounded-card border border-line p-3">
                <p className="mb-2 text-xs font-semibold text-ink/55">URL score histogram</p>
                <UrlScoreHistogram urls={state.retrieved_urls} />
              </div>
              <div className="rounded-card border border-line p-3 sm:col-span-2 xl:col-span-1">
                <p className="mb-2 text-xs font-semibold text-ink/55">Source-type mix</p>
                <SourceTypePie urls={state.retrieved_urls} />
              </div>
            </div>
          </div>
        )}
      </StageSection>

      {/* ---- 4. SCRAPING ---- */}
      <StageSection stageId="firecrawl_scraper" status={status(state, "firecrawl_scraper")}>
        {(() => {
          const blocks = state.scraped_blocks ?? [];
          const fc = state.firecrawl_result;
          const scrapeStatus = status(state, "firecrawl_scraper");
          const totalUrls = fc?.total_urls ?? (state.retrieved_urls ?? []).length;
          const successful = fc?.successful_scrapes ?? blocks.filter((b) => b.scrape_status === "success" && b.content).length;
          const failed = fc?.failed_scrapes ?? blocks.filter((b) => b.scrape_status !== "success").length;
          const fallbacks = fc?.fallback_scrapes ?? blocks.filter((b) => b.is_fallback).length;
          const pending = totalUrls - blocks.length;

          if (blocks.length === 0 && scrapeStatus !== "running") return null;

          const sorted = [...blocks].sort((a, b) => {
            const aFailed = a.scrape_status !== "success" ? 1 : 0;
            const bFailed = b.scrape_status !== "success" ? 1 : 0;
            return aFailed - bFailed;
          });

          const donutData = [
            { name: "Successful", value: successful, color: TOKENS.green },
            { name: "Failed", value: failed, color: TOKENS.red },
            ...(pending > 0 ? [{ name: "Pending", value: pending, color: "#D1D5DB" }] : []),
          ];

          return (
            <div className="space-y-4">
              {fallbacks > 0 && (
                <AlertBanner level="amber" title={`${fallbacks} fallback URL${fallbacks === 1 ? "" : "s"} used`}>
                  {fallbacks} original URL{fallbacks === 1 ? "" : "s"} failed to scrape and {fallbacks === 1 ? "was" : "were"} replaced with the next-best results from the retrieval pool.
                </AlertBanner>
              )}
              <div className="grid gap-4 lg:grid-cols-[auto_1fr] lg:items-center">
                <Donut
                  centerValue={totalUrls}
                  centerLabel="URLs"
                  data={donutData}
                />
                <div className="max-h-56 space-y-1 overflow-y-auto scroll-thin pr-1">
                  {sorted.map((b, i) => {
                    const isFailed = b.scrape_status !== "success";
                    return (
                      <div
                        key={i}
                        className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs ${isFailed ? "border-red/30 bg-red/5" : b.is_fallback ? "border-amber/30 bg-amber/5" : "border-line"}`}
                      >
                        <Badge tone={b.scrape_status === "success" ? "green" : "red"} dot>
                          {b.scrape_status}
                        </Badge>
                        {b.is_fallback && (
                          <Badge tone="amber">fallback</Badge>
                        )}
                        <span className="min-w-0 flex-1 truncate text-ink/70">
                          {truncate(b.title ?? b.url, 42)}
                        </span>
                        {isFailed && b.error && (
                          <span className="shrink-0 max-w-[140px] truncate text-[10px] text-red/80" title={b.error}>
                            {b.error}
                          </span>
                        )}
                      </div>
                    );
                  })}
                  {pending > 0 && (
                    <div className="flex items-center gap-2 rounded-md border border-line/50 px-2.5 py-1.5 text-xs text-ink/40 italic">
                      {pending} URL{pending === 1 ? "" : "s"} scraping…
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })()}
      </StageSection>

      {/* ---- 5. CHUNKING ---- */}
      <StageSection stageId="chunking" status={status(state, "chunking")}>
        <div className="space-y-4">
          <StatRow
            items={[
              { label: "Semantic chunks", value: (state.semantic_chunks ?? []).length, tone: "navy" },
              { label: "Extraction chunks", value: extractionChunks.length, tone: "teal" },
              { label: "Skipped chunks", value: (state.skipped_chunks ?? []).length, tone: "grey" },
              { label: "Total tokens", value: compact(tokensTotal), tone: "blue", hint: `~${avgTokens} avg / chunk` },
            ]}
          />
          <div className="rounded-card border border-line p-3">
            <p className="mb-2 text-xs font-semibold text-ink/55">
              Tokens per extraction chunk
            </p>
            <TokenBarChart chunks={extractionChunks} />
          </div>
        </div>
      </StageSection>

      {/* ---- 6. EXTRACTION ---- */}
      <StageSection stageId="extraction" status={status(state, "extraction")}>
        {state.field_report && (
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-card border border-line p-3">
                <p className="mb-2 text-xs font-semibold text-ink/55">
                  Field outcomes ({state.field_report.entries.length} fields)
                </p>
                <FieldCoverageStackedBar report={state.field_report} />
              </div>
              <StatRow
                columns={2}
                items={[
                  { label: "Extracted", value: state.field_report.extracted_count, tone: "green" },
                  { label: "Ambiguous", value: state.field_report.ambiguous_count, tone: "amber" },
                  { label: "Not found", value: state.field_report.not_found_count, tone: "red" },
                  { label: "Flagged", value: state.field_report.flagged_count, tone: "blue" },
                ]}
              />
            </div>
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink/45">
                Schema field report
              </p>
              <SchemaFieldTable report={state.field_report} claims={state.extracted_claims} />
            </div>
          </div>
        )}
      </StageSection>

      {/* ---- 7. CLAIMS & CONFLICTS ---- */}
      <StageSection
        stageId="claims"
        status={status(state, "claims")}
        aside={
          (state.conflicts ?? []).length > 0 ? (
            <Badge tone="amber" dot>
              {(state.conflicts ?? []).length} conflicts
            </Badge>
          ) : undefined
        }
      >
        {(() => {
          const conflicts = state.conflicts ?? [];
          const conflictFields = new Set(conflicts.map((c) => c.field_path));
          const conflictingClaims = (state.extracted_claims ?? []).filter((c) =>
            conflictFields.has(c.field_path),
          );
          return (
            <div className="space-y-4">
              {conflicts.length > 0 && (
                <AlertBanner level="amber" title={`${conflicts.length} field conflicts detected`}>
                  Conflicting claims are routed to adjudication; high score-gap items
                  escalate to human review.
                </AlertBanner>
              )}
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink/45">
                  {conflictingClaims.length} conflicting claims
                </p>
                <ClaimsTable claims={conflictingClaims} />
              </div>
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink/45">
                  Conflict records
                </p>
                <ConflictGrid conflicts={conflicts} />
              </div>
            </div>
          );
        })()}
      </StageSection>

      {/* ---- 8. ADJUDICATION / DEBATE ---- */}
      <StageSection stageId="adjudication" status={status(state, "adjudication")}>
        <div className="space-y-4">
          <HumanReviewQueue items={state.human_review_queue ?? []} />
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink/45">
              Adversarial debate timeline
            </p>
            <DebateTimeline adjudicated={state.adjudicated ?? []} />
          </div>
        </div>
      </StageSection>

      {/* ---- 9. OUTPUT ---- */}
      <StageSection stageId="output" status={status(state, "output")}>
        <OutputSection state={state} />
      </StageSection>
    </div>
  );
}

export function OutputSection({ state }: { state: AgentState }) {
  const c = state.schema_coverage;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4 items-center">
        <div className="shrink-0"><CoverageRing coverage={c} size={160} /></div>
        <div className="shrink-0"><DataQualityGauge value={state.data_quality} label="Data quality" size={160} /></div>
        <div className="min-w-[240px] flex-1">
          <StatRow
            columns={2}
            items={[
              { label: "Total fields", value: c.total_fields, tone: "navy" },
              { label: "Supported", value: c.supported_fields, tone: "green" },
              { label: "Manual review", value: c.manual_review_fields, tone: "red" },
              { label: "Rejected", value: c.rejected_fields, tone: "amber" },
              { label: "Null / N/A", value: c.null_fields, tone: "grey" },
              {
                label: "Cited claims",
                value: state.final_brief?.cited_claim_ids.length ?? 0,
                tone: "blue",
              },
            ]}
          />
        </div>
      </div>

      {state.final_brief && (
        <div className="overflow-hidden rounded-card border border-line">
          <div className="flex items-center gap-2 border-b border-line bg-soft-grey/40 px-4 py-2.5">
            <FileText className="h-4 w-4 text-teal" />
            <span className="text-sm font-semibold text-navy">Analyst brief</span>
            {state.final_brief.entailment_passed && (
              <Badge tone="green" className="ml-auto">
                <BadgeCheck className="h-3 w-3" />
                Entailment passed
              </Badge>
            )}
          </div>
          <div className="brief max-h-[460px] overflow-y-auto scroll-thin px-5 py-4">
            <MarkdownBrief text={state.final_brief.brief_text} />
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t border-line bg-soft-grey/30 px-4 py-2 text-xs text-ink/55">
            <Quote className="h-3.5 w-3.5" />
            <span className="stat-num">{state.final_brief.word_count} words</span>
            <span>·</span>
            <span className="stat-num">
              {(state.final_brief.cited_claim_ids ?? []).length} cited claims
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

/** Minimal markdown renderer for the brief (headings / bold / italics / paragraphs). */
function MarkdownBrief({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => {
        if (!line.trim()) return null;
        if (line.startsWith("## ")) return <h2 key={i}>{inline(line.slice(3))}</h2>;
        if (line.startsWith("### ")) return <h3 key={i}>{inline(line.slice(4))}</h3>;
        return <p key={i}>{inline(line)}</p>;
      })}
    </>
  );
}

function inline(text: string): React.ReactNode {
  // split on **bold** and _italic_
  const parts = text.split(/(\*\*[^*]+\*\*|_[^_]+_)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**"))
      return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("_") && p.endsWith("_")) return <em key={i}>{p.slice(1, -1)}</em>;
    return <span key={i}>{p}</span>;
  });
}
