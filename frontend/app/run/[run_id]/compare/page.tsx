"use client";

import React from "react";
import Link from "next/link";
import { useEffect, useMemo } from "react";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Crown,
  History,
  Loader2,
  Minus,
  MoveRight,
  ShieldAlert,
  ShieldCheck,
  Star,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import { Topbar } from "@/components/Topbar";
import { Button } from "@/components/ui/button";
import { ComparisonTable } from "@/components/ComparisonTable";
import { SourcePillRow } from "@/components/SourcePill";
import { DataQualityGauge } from "@/components/charts/DataQualityGauge";
import { useRun, useGenerateBrief } from "@/lib/hooks";
import { DownloadPDFButton } from "@/components/DownloadPDFButton";
import { ConverseThread } from "@/components/ConverseThread";
import { cn, signed, renderValue } from "@/lib/format";
import {
  CATEGORY_ORDER,
  CATEGORY_LABELS,
  FIELDS_BY_CATEGORY,
  FOCUSED_SCHEMA_FIELD_PATHS,
  fieldLabel,
  isHighVolatility,
  type Category,
} from "@/lib/schema";
import type {
  AgentState,
  ComparisonBrief,
  ComparisonRunInfo,
  FieldReportEntry,
  FieldReportStatus,
  ProgramStrategicProfile,
} from "@/lib/types";

// ── Color palettes per program slot ──────────────────────────────────────────
const PROGRAM_COLORS = [
  { header: "bg-teal/15 text-teal border-teal/25", accent: "text-teal", dot: "bg-teal", label: "A", ring: "ring-teal/30" },
  { header: "bg-blue/15 text-blue border-blue/25", accent: "text-blue", dot: "bg-blue", label: "B", ring: "ring-blue/30" },
  { header: "bg-navy/15 text-navy border-navy/25", accent: "text-navy", dot: "bg-navy", label: "C", ring: "ring-navy/30" },
  { header: "bg-green/15 text-green border-green/25", accent: "text-green", dot: "bg-green", label: "D", ring: "ring-green/30" },
  { header: "bg-amber/15 text-amber border-amber/25", accent: "text-amber", dot: "bg-amber", label: "E", ring: "ring-amber/30" },
];

const STATUS_CELL: Record<FieldReportStatus, { bg: string; text: string }> = {
  extracted: { bg: "bg-green/8", text: "text-navy" },
  ambiguous: { bg: "bg-amber/8", text: "text-amber" },
  not_found: { bg: "bg-soft-grey", text: "text-ink/40" },
  flagged: { bg: "bg-red/8", text: "text-red" },
};

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ComparePage({ params }: { params: { run_id: string } }) {
  const runId = params.run_id;
  const { data: state, isLoading } = useRun(runId);

  if (isLoading) {
    return (
      <Frame runId={runId}>
        <Centered><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…</Centered>
      </Frame>
    );
  }

  if (!state || state.mode !== "compare") {
    return (
      <Frame runId={runId}>
        <Centered>
          <div className="text-center text-ink/50">
            <p>Comparison not ready yet.</p>
            <Link href={`/run/${runId}`} className="mt-3 inline-block">
              <Button variant="outline" size="sm"><ArrowLeft className="h-4 w-4" /> Back to run</Button>
            </Link>
          </div>
        </Centered>
      </Frame>
    );
  }

  const compRun = state.comparison_run;
  const nPrograms = compRun?.total_programs ?? 2;

  // N>2 programs: render multi-program view
  if (compRun && nPrograms > 2) {
    return (
      <Frame runId={runId}>
        <MultiProgramView runId={runId} state={state} compRun={compRun} />
      </Frame>
    );
  }

  // 2-program: keep existing rich view
  if (!state.compare_b) {
    if (state.comparison_brief) {
      return (
        <Frame runId={runId}>
          <div className="mx-auto max-w-[1500px] space-y-4 px-5 py-7">
            <div className="rounded-card border border-amber/30 bg-amber/5 px-4 py-3 text-sm text-ink/70">
              This archived comparison was loaded from history. The detailed second-program snapshot was not
              persisted, so the side-by-side table is unavailable for this older run.
            </div>
            <ComparisonBriefPanel brief={state.comparison_brief} />
          </div>
        </Frame>
      );
    }

    return (
      <Frame runId={runId}>
        <Centered>
          <div className="text-center text-ink/50">
            <p>Comparison output not ready.</p>
            <p className="mt-1 text-sm">The pipeline is still processing both programs.</p>
            <Link href={`/run/${runId}`} className="mt-3 inline-block">
              <Button variant="outline" size="sm"><ArrowLeft className="h-4 w-4" /> Back to run</Button>
            </Link>
          </div>
        </Centered>
      </Frame>
    );
  }

  return (
    <Frame runId={runId}>
      <TwoProgramView runId={runId} state={state} />
    </Frame>
  );
}

// ── Two-program view ──────────────────────────────────────────────────────────

function TwoProgramView({ runId, state }: { runId: string; state: AgentState }) {
  const stateB = state.compare_b!;
  const qa = state.data_quality;
  const qb = stateB.data_quality;
  const delta = qa - qb;
  const brief = state.comparison_brief ?? null;
  const isDone = state.status === "done";
  const generateBrief = useGenerateBrief(runId);

  // Auto-generate brief for existing runs that never had one
  useEffect(() => {
    if (isDone && !brief && !generateBrief.isPending && !generateBrief.isSuccess && !generateBrief.isError) {
      generateBrief.mutate();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDone, brief]);

  const programA = state.comparison_output?.program_a ?? state.program_name ?? state.user_input;
  const programB = state.comparison_output?.program_b ?? stateB.program_name ?? stateB.user_input ?? "";
  const syntheticComparison = state.comparison_output ?? {
    comparison_id: "",
    run_id: runId,
    program_a: programA,
    program_b: programB,
    items: [],
  };

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 px-5 py-7">
      <CompareHeader
        programs={[programA, programB]}
        runId={runId}
        actions={<DownloadPDFButton state={state} variant="compare" />}
      />

      {/* quality cards */}
      <div className="grid gap-4 lg:grid-cols-[1fr_auto_1fr]">
        <QualityCard name={programA} value={qa} colorIdx={0} slotLabel="Program A" />
        <div className="flex flex-col items-center justify-center gap-1 rounded-card border border-line bg-white px-5 py-4 shadow-sm">
          <span className="text-[10px] font-medium uppercase tracking-wide text-ink/45">Quality delta</span>
          <span className={cn("stat-num flex items-center gap-1 text-xl font-semibold", delta >= 0 ? "text-teal" : "text-blue")}>
            {delta >= 0 ? <TrendingUp className="h-5 w-5" /> : <TrendingDown className="h-5 w-5" />}
            {signed(delta)}
          </span>
          <span className="text-[10px] text-ink/45">A − B</span>
        </div>
        <QualityCard name={programB} value={qb} colorIdx={1} slotLabel="Program B" />
      </div>

      {brief ? (
        <ComparisonBriefPanel brief={brief} />
      ) : generateBrief.isPending || (!isDone) ? (
        <div className="flex items-center gap-2 rounded-card border border-line bg-white px-5 py-4 text-sm text-ink/50 shadow-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {generateBrief.isPending ? "Generating competitive intelligence brief…" : "Generating competitive intelligence brief…"}
        </div>
      ) : generateBrief.isError ? (
        <div className="flex items-center gap-2 rounded-card border border-amber/30 bg-amber/5 px-5 py-4 text-sm text-ink/55 shadow-sm">
          <AlertCircle className="h-4 w-4 shrink-0 text-amber" />
          Brief generation failed — the field-by-field comparison is still available below.
        </div>
      ) : null}

      {/* Comparison chat — grounded strictly in the comparison brief and per-program field data */}
      <section id="compare-converse" className="scroll-mt-4">
        <h2 className="mb-2.5 flex items-center gap-2 text-[13px] font-semibold text-navy">
          Ask about this comparison
          <span className="text-[11px] font-normal text-ink/40">
            grounded strictly in {programA} vs {programB} extracted data
          </span>
        </h2>
        <div className="rounded-[10px] border border-line bg-white shadow-sm">
          <ConverseThread
            runId={runId}
            conversation={state.comparison_conversation ?? []}
            disabled={!brief}
            compare={true}
          />
        </div>
      </section>

      <h2 className="text-base font-semibold text-navy">Field-by-field data</h2>
      <ComparisonTable comparison={syntheticComparison} stateA={state} stateB={stateB} />
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _domain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// ── Comparison brief panel ────────────────────────────────────────────────────

function ComparisonBriefPanel({ brief }: { brief: ComparisonBrief }) {
  const winnerColor = (name: string) => {
    const idx = brief.programs.indexOf(name);
    return idx === 0 ? "text-teal" : idx === 1 ? "text-blue" : "text-navy";
  };

  return (
    <div className="space-y-4">
      {/* Executive summary + overall winner */}
      <div className="relative overflow-hidden rounded-card border border-teal/30 bg-gradient-to-br from-[#e2f3f3] to-white p-5 shadow-panel">
        <span className="absolute inset-y-0 left-0 w-1 bg-teal" aria-hidden />
        <div className="flex items-start gap-3">
          <Zap className="mt-0.5 h-5 w-5 shrink-0 text-teal" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3 mb-2">
              <p className="text-sm font-semibold text-navy">Competitive Intelligence Brief</p>
              {brief.overall_winner && (
                <span className={cn("flex items-center gap-1 text-xs font-semibold", winnerColor(brief.overall_winner))}>
                  <Crown className="h-3.5 w-3.5" /> Overall: {brief.overall_winner}
                </span>
              )}
              {!brief.overall_winner && (
                <span className="flex items-center gap-1 text-xs font-medium text-ink/50">
                  <Minus className="h-3.5 w-3.5" /> Evenly matched
                </span>
              )}
            </div>
            <p className="text-sm leading-relaxed text-ink/75">{brief.executive_summary}</p>
          </div>
        </div>
      </div>

      {/* Category verdicts grid */}
      {brief.category_verdicts.length > 0 && (
        <div>
          <h2 className="mb-3 text-base font-semibold text-navy">Category verdicts</h2>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {brief.category_verdicts.map((v) => {
              const isTie = v.winner === "Tie";
              const noData = v.winner === "Insufficient data";
              const color = noData ? "text-ink/40" : isTie ? "text-ink/60" : winnerColor(v.winner);
              return (
                <div key={v.category} className="rounded-card border border-line bg-white p-3 shadow-sm">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-ink/45">{v.label}</p>
                  <div className="mt-1.5 flex items-center gap-1.5">
                    {noData ? null : isTie ? (
                      <Minus className="h-4 w-4 text-ink/40" />
                    ) : (
                      <Crown className={cn("h-4 w-4", color)} />
                    )}
                    <span className={cn("truncate text-sm font-semibold", color)}>{v.winner}</span>
                  </div>
                  <p className="mt-1.5 text-[11px] leading-snug text-ink/55">{v.insight}</p>
                  {v.source_urls && v.source_urls.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {v.source_urls.map((url, i) => (
                        <a
                          key={i}
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-block max-w-[160px] truncate rounded bg-soft-grey px-1.5 py-0.5 text-[9px] text-ink/50 hover:text-teal hover:underline"
                          title={url}
                        >
                          {_domain(url)}
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Key differentiators */}
      {brief.key_differentiators.length > 0 && (
        <div>
          <h2 className="mb-3 text-base font-semibold text-navy">Key differentiators</h2>
          <div className="divide-y divide-line overflow-hidden rounded-card border border-line bg-white shadow-sm">
            {brief.key_differentiators.map((d, i) => (
              <div key={i} className="flex items-start gap-4 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-navy">{d.topic}</p>
                  <p className="mt-0.5 text-sm text-ink/65 leading-relaxed">{d.insight}</p>
                  {d.rejected_note && (
                    <p className="mt-1.5 text-[11px] leading-snug text-amber/80 italic border-l-2 border-amber/30 pl-2">
                      {d.rejected_note}
                    </p>
                  )}
                  {d.source_urls && d.source_urls.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {d.source_urls.map((url, j) => (
                        <a
                          key={j}
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-block max-w-[200px] truncate rounded bg-soft-grey px-1.5 py-0.5 text-[9px] text-ink/50 hover:text-teal hover:underline"
                          title={url}
                        >
                          {_domain(url)}
                        </a>
                      ))}
                    </div>
                  )}
                </div>
                <span className={cn("shrink-0 text-xs font-semibold mt-0.5", winnerColor(d.advantage))}>
                  {d.advantage} ↑
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Strategic advantages & gaps */}
      {brief.strategic_profiles && brief.strategic_profiles.length > 0 && (
        <StrategicProfilesSection profiles={brief.strategic_profiles} winnerColor={winnerColor} />
      )}


      {/* Target Audience */}
      {brief.personas.length > 0 && (
        <div>
          <h2 className="mb-3 text-base font-semibold text-navy">Target Audience</h2>
          <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.min(brief.personas.length, 3)}, minmax(0, 1fr))` }}>
            {brief.personas.map((p, i) => {
              const c = PROGRAM_COLORS[i % PROGRAM_COLORS.length];
              return (
                <div key={i} className={cn("rounded-card border p-4", i === 0 ? "border-teal/30 bg-teal/5" : i === 1 ? "border-blue/30 bg-blue/5" : "border-navy/30 bg-navy/5")}>
                  <p className={cn("text-xs font-bold uppercase tracking-wide mb-1", c.accent)}>{p.program}</p>
                  <p className="text-sm text-ink/75 leading-relaxed">{p.best_for}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Strategic profiles section ────────────────────────────────────────────────

function StrategicProfilesSection({
  profiles,
  winnerColor,
}: {
  profiles: ProgramStrategicProfile[];
  winnerColor: (name: string) => string;
}) {
  const n = profiles.length;
  return (
    <div>
      <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-navy">
        <ShieldCheck className="h-4 w-4 text-teal" />
        Strategic advantages &amp; gaps
      </h2>
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: `repeat(${Math.min(n, 3)}, minmax(0, 1fr))` }}
      >
        {profiles.map((profile, i) => {
          const c = PROGRAM_COLORS[i % PROGRAM_COLORS.length];
          return (
            <div key={i} className="rounded-card border border-line bg-white shadow-sm overflow-hidden">
              {/* Header */}
              <div className={cn("flex items-center gap-2 border-b border-line px-4 py-2.5", c.header)}>
                <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold border", c.header)}>
                  {String.fromCharCode(65 + i)}
                </span>
                <span className="truncate text-[12px] font-semibold">{profile.program}</span>
              </div>

              <div className="grid grid-cols-2 divide-x divide-line">
                {/* Advantages */}
                <div className="p-3">
                  <p className="mb-2 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-green">
                    <CheckCircle2 className="h-3 w-3" /> Strengths
                  </p>
                  {profile.advantages.length > 0 ? (
                    <ul className="space-y-1.5">
                      {profile.advantages.map((adv, j) => (
                        <li key={j} className="flex items-start gap-1.5 text-[11px] text-ink/75 leading-snug">
                          <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-green/60" />
                          {adv}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-[11px] italic text-ink/30">No data</p>
                  )}
                </div>

                {/* Gaps */}
                <div className="p-3">
                  <p className="mb-2 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-amber">
                    <ShieldAlert className="h-3 w-3" /> Gaps
                  </p>
                  {profile.gaps.length > 0 ? (
                    <ul className="space-y-1.5">
                      {profile.gaps.map((gap, j) => (
                        <li key={j} className="flex items-start gap-1.5 text-[11px] text-ink/75 leading-snug">
                          <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber/60" />
                          {gap}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-[11px] italic text-ink/30">No data</p>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Differentiation section ───────────────────────────────────────────────────


// ── Multi-program view (N ≥ 3) ────────────────────────────────────────────────

function MultiProgramView({
  runId,
  state,
  compRun,
}: {
  runId: string;
  state: AgentState;
  compRun: ComparisonRunInfo;
}) {
  const generateBrief = useGenerateBrief(runId);
  const isDone = state.status === "done";

  useEffect(() => {
    if (isDone && !state.comparison_brief && !generateBrief.isPending && !generateBrief.isSuccess && !generateBrief.isError) {
      generateBrief.mutate();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDone, state.comparison_brief]);
  const { programs, program_states, program_statuses } = compRun;

  // Only consider completed program states
  const completedEntries = programs
    .map((prog, idx) => ({
      prog,
      idx,
      st: program_states[idx] as AgentState | null,
      status: program_statuses[idx],
    }))
    .filter((e) => e.status === "done" && e.st !== null);

  const nCompleted = completedEntries.length;

  // Build per-program field-value maps from field_report entries
  const fieldMaps = useMemo(
    () =>
      completedEntries.map(({ st }) => {
        const m = new Map<string, FieldReportEntry>();
        (st?.field_report?.entries ?? []).forEach((e) => m.set(e.field_path, e));
        return m;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [compRun],
  );

  // Summary stats per program
  const qualityScores = completedEntries.map(({ st }) => st?.data_quality ?? 0);
  const bestQuality = Math.max(...qualityScores);
  const bestIdx = qualityScores.indexOf(bestQuality);
  const bestProgram = completedEntries[bestIdx]?.prog ?? programs[0];

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 px-5 py-7">
      <CompareHeader
        programs={programs}
        runId={runId}
        actions={<DownloadPDFButton state={state} variant="compare" />}
      />

      {/* Quality gauges row */}
      <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${Math.min(nCompleted, 4)}, minmax(0, 1fr))` }}>
        {completedEntries.map(({ prog, idx, st }) => (
          <QualityCard
            key={idx}
            name={prog}
            value={st?.data_quality ?? 0}
            colorIdx={idx}
            slotLabel={`Program ${String.fromCharCode(65 + idx)}`}
            isBest={idx === completedEntries[bestIdx]?.idx}
          />
        ))}
      </div>

      {/* Coverage summary chips */}
      <div className="grid gap-3 sm:grid-cols-3">
        {completedEntries.map(({ prog, idx, st }) => {
          const fr = st?.field_report;
          return (
            <CoverageChip
              key={idx}
              prog={prog}
              colorIdx={idx}
              extracted={fr?.extracted_count ?? 0}
              ambiguous={fr?.ambiguous_count ?? 0}
              notFound={fr?.not_found_count ?? 0}
            />
          );
        })}
      </div>

      {/* AI brief — shown when available */}
      {state.comparison_brief ? (
        <ComparisonBriefPanel brief={state.comparison_brief} />
      ) : generateBrief.isPending || !isDone ? (
        <div className="flex items-center gap-2 rounded-card border border-line bg-white px-5 py-4 text-sm text-ink/50 shadow-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          Generating competitive intelligence brief…
        </div>
      ) : generateBrief.isError ? (
        <div className="flex items-center gap-2 rounded-card border border-amber/30 bg-amber/5 px-5 py-4 text-sm text-ink/55 shadow-sm">
          <AlertCircle className="h-4 w-4 shrink-0 text-amber" />
          Brief generation failed — the field-by-field comparison is still available below.
        </div>
      ) : null}

      {/* Multi-column field comparison table */}
      <section>
        <h2 className="mb-3 text-base font-semibold text-navy">Field-by-field comparison</h2>
        <MultiFieldTable
          programs={completedEntries.map((e) => e.prog)}
          colorIndices={completedEntries.map((e) => e.idx)}
          fieldMaps={fieldMaps}
        />
      </section>

      {/* Comparison chat */}
      <section id="compare-converse" className="scroll-mt-4">
        <h2 className="mb-2.5 flex items-center gap-2 text-[13px] font-semibold text-navy">
          Ask about this comparison
          <span className="text-[11px] font-normal text-ink/40">
            grounded strictly in the {nCompleted} programs&#39; extracted data
          </span>
        </h2>
        <div className="rounded-[10px] border border-line bg-white shadow-sm">
          <ConverseThread
            runId={runId}
            conversation={state.comparison_conversation ?? []}
            disabled={false}
            compare={true}
          />
        </div>
      </section>
    </div>
  );
}

// ── Multi-program field table ─────────────────────────────────────────────────

function MultiFieldTable({
  programs,
  colorIndices,
  fieldMaps,
}: {
  programs: string[];
  colorIndices: number[];
  fieldMaps: Map<string, FieldReportEntry>[];
}) {
  const n = programs.length;

  // Grid template: field name column + one column per program
  const gridCols = `minmax(140px,1.2fr) ${Array(n).fill("minmax(0,1fr)").join(" ")}`;

  return (
    <div className="overflow-x-auto rounded-[12px] border border-line bg-white shadow-sm">
      {/* Column headers */}
      <div
        className="grid gap-0 border-b border-line bg-navy px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-white/80"
        style={{ gridTemplateColumns: gridCols }}
      >
        <span>Field</span>
        {programs.map((prog, i) => {
          const c = PROGRAM_COLORS[colorIndices[i] % PROGRAM_COLORS.length];
          return (
            <span key={i} className={cn("truncate px-2", c.accent)}>
              {String.fromCharCode(65 + colorIndices[i])}: {prog}
            </span>
          );
        })}
      </div>

      {/* Category blocks */}
      {CATEGORY_ORDER.map((cat) => {
        const fields = FIELDS_BY_CATEGORY[cat].filter((f) =>
          FOCUSED_SCHEMA_FIELD_PATHS.has(f),
        );
        if (fields.length === 0) return null;

        return (
          <div key={cat}>
            {/* Category header */}
            <div
              className="grid border-b border-line bg-soft-grey/60 px-4 py-1.5"
              style={{ gridTemplateColumns: gridCols }}
            >
              <span className="col-span-full text-[10px] font-bold uppercase tracking-widest text-ink/50">
                {CATEGORY_LABELS[cat]}
              </span>
            </div>

            {/* Field rows */}
            {fields.map((fieldPath, rowIdx) => {
              const entries = fieldMaps.map((m) => m.get(fieldPath) ?? null);
              const extractedCount = entries.filter((e) => e?.status === "extracted").length;
              const isVolatile = isHighVolatility(fieldPath);

              return (
                <div
                  key={fieldPath}
                  className={cn(
                    "grid items-start gap-0 border-b border-line/50 px-4 py-2.5 transition-colors hover:bg-soft-grey/20",
                    rowIdx % 2 === 1 && "bg-soft-grey/10",
                  )}
                  style={{ gridTemplateColumns: gridCols }}
                >
                  {/* Field name */}
                  <div className="pr-3 py-0.5">
                    <p className="text-[12px] font-medium text-navy leading-snug">
                      {fieldLabel(fieldPath)}
                    </p>
                    {isVolatile && (
                      <span className="mt-0.5 inline-block rounded-sm bg-amber/10 px-1 py-0 text-[9px] font-semibold uppercase tracking-wide text-amber">
                        volatile
                      </span>
                    )}
                  </div>

                  {/* Value cells */}
                  {entries.map((entry, progIdx) => {
                    const colConfig = PROGRAM_COLORS[colorIndices[progIdx] % PROGRAM_COLORS.length];
                    if (!entry || entry.status === "not_found") {
                      return (
                        <div key={progIdx} className="px-2 py-0.5">
                          <span className="text-[11px] italic text-ink/30">—</span>
                        </div>
                      );
                    }
                    const cellStyle = STATUS_CELL[entry.status] ?? STATUS_CELL.not_found;
                    const isBest = entry.status === "extracted" && extractedCount < n;

                    return (
                      <div
                        key={progIdx}
                        className={cn(
                          "rounded-md px-2 py-1.5 text-[11px] leading-relaxed",
                          cellStyle.bg,
                          cellStyle.text,
                          isBest && "ring-1 " + colConfig.ring,
                        )}
                      >
                        <span className="line-clamp-3">
                          {renderValue(entry.value) || "—"}
                        </span>
                        {entry.confidence !== null && (
                          <span className="mt-0.5 block text-[9px] text-ink/30 tabular-nums">
                            {Math.round((entry.confidence ?? 0) * 100)}% conf
                            {entry.corroboration_count > 1 && ` · ${entry.corroboration_count}×`}
                          </span>
                        )}
                        {entry.source_urls?.length > 0 && (
                          <div className="mt-1.5">
                            <SourcePillRow urls={entry.source_urls} />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

// ── Coverage chip ─────────────────────────────────────────────────────────────

function CoverageChip({
  prog,
  colorIdx,
  extracted,
  ambiguous,
  notFound,
}: {
  prog: string;
  colorIdx: number;
  extracted: number;
  ambiguous: number;
  notFound: number;
}) {
  const total = extracted + ambiguous + notFound;
  const pctExtracted = total > 0 ? Math.round((extracted / total) * 100) : 0;
  const c = PROGRAM_COLORS[colorIdx % PROGRAM_COLORS.length];

  return (
    <div className="rounded-[10px] border border-line bg-white px-4 py-3 shadow-sm">
      <div className="flex items-start gap-2.5 mb-2">
        <span
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold border",
            c.header,
          )}
        >
          {c.label}
        </span>
        <p className="text-[12px] font-semibold text-navy leading-snug truncate">{prog}</p>
      </div>
      {/* Bar */}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-soft-grey">
        <div
          className="h-full rounded-full bg-green transition-all duration-500"
          style={{ width: `${pctExtracted}%` }}
        />
      </div>
      <div className="mt-1.5 flex items-center gap-3 text-[10px] text-ink/50">
        <span className="text-green font-medium">{extracted} extracted</span>
        {ambiguous > 0 && <span className="text-amber">{ambiguous} ambiguous</span>}
        {notFound > 0 && <span>{notFound} not found</span>}
        <span className="ml-auto font-semibold text-navy tabular-nums">{pctExtracted}%</span>
      </div>
    </div>
  );
}

// ── Shared layout helpers ─────────────────────────────────────────────────────

function CompareHeader({
  programs,
  runId,
  actions,
}: {
  programs: string[];
  runId: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-ink/45">Comparison</p>
        <h1 className="mt-0.5 flex flex-wrap items-center gap-2 text-2xl font-semibold text-navy">
          {programs.map((p, i) => (
            <span key={i} className="flex items-center gap-2">
              {i > 0 && <MoveRight className="h-5 w-5 text-ink/30 shrink-0" />}
              <span>{p}</span>
            </span>
          ))}
        </h1>
      </div>
      <div className="flex items-center gap-2">
        {actions}
        <Link href={`/run/${runId}`}>
          <Button variant="outline" size="sm">
            <ArrowLeft className="h-4 w-4" /> Back to run
          </Button>
        </Link>
      </div>
    </div>
  );
}

function QualityCard({
  name,
  value,
  colorIdx,
  slotLabel,
  isBest,
}: {
  name: string;
  value: number;
  colorIdx: number;
  slotLabel: string;
  isBest?: boolean;
}) {
  const c = PROGRAM_COLORS[colorIdx % PROGRAM_COLORS.length];
  return (
    <div
      className={cn(
        "flex items-center gap-4 rounded-card border bg-white px-5 py-4 shadow-sm transition-all",
        isBest && "border-green/30 ring-2 ring-green/20",
        !isBest && "border-line",
      )}
    >
      <DataQualityGauge value={value} label="Content Extracted" size={140} />
      <div className="min-w-0">
        {isBest && (
          <span className="mb-1 inline-flex items-center gap-1 rounded-pill bg-green/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-green">
            <Star className="h-2.5 w-2.5" /> Best
          </span>
        )}
        <span className={cn("block text-[10px] font-semibold uppercase tracking-wide", c.accent)}>
          {slotLabel}
        </span>
        <p className="text-base font-semibold leading-tight text-navy truncate">{name}</p>
      </div>
    </div>
  );
}


// ── Frames & layout ───────────────────────────────────────────────────────────

function Frame({ runId, children }: { runId: string; children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <Topbar>
        <Link href="/history">
          <Button size="sm" variant="ghost" className="text-white hover:bg-white/10">
            <History className="h-4 w-4" /> History
          </Button>
        </Link>
        <Link href={`/run/${runId}`}>
          <Button size="sm" variant="outline">
            <ArrowLeft className="h-4 w-4" /> Run
          </Button>
        </Link>
        <Link href="/">
          <Button size="sm" variant="ghost" className="text-white hover:bg-white/10">
            New <ArrowRight className="h-4 w-4" />
          </Button>
        </Link>
      </Topbar>
      {children}
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-[70vh] items-center justify-center text-ink/40">{children}</div>
  );
}
