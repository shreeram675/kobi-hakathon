"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useCallback } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Clock,
  DollarSign,
  GitCompareArrows,
  History,
  Hash,
  Loader2,
  CheckCircle2,
  CircleDot,
  Square,
  ChevronRight,
  RotateCcw,
  OctagonX,
} from "lucide-react";
import { Topbar } from "@/components/Topbar";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PipelineGraph } from "@/components/PipelineGraph";
import { StageDetailPanel } from "@/components/StageDetailPanel";
import { ErrorRail } from "@/components/ErrorRail";
import { ConverseThread } from "@/components/ConverseThread";
import { SingleProgramBriefPanel } from "@/components/SingleProgramBriefPanel";
import { ClarificationPanel } from "@/components/ClarificationPanel";
import { CacheDecisionModal } from "@/components/CacheDecisionModal";
import { ProgramQueuePanel } from "@/components/ProgramQueuePanel";
import { useRun, useStopRun, useRetryRun, useCacheDecision } from "@/lib/hooks";
import { DownloadPDFButton } from "@/components/DownloadPDFButton";
import { STAGE_IDS, PIPELINE_STAGES, type StageId } from "@/lib/schema";
import { cn, elapsed } from "@/lib/format";
import type { AgentState, CostReport, RunMode } from "@/lib/types";

const MODE_TONE: Record<RunMode, Tone> = {
  single: "teal",
  compare: "blue",
  converse: "navy",
};

const MODE_LABEL: Record<RunMode, string> = {
  single: "Single Analysis",
  compare: "Comparison",
  converse: "Analyse & Chat",
};

const PROGRAM_ACCENT = ["text-teal", "text-blue", "text-navy", "text-green", "text-amber"];
const PROGRAM_BG = [
  "from-teal to-navy",
  "from-blue to-navy",
  "from-navy to-ink",
  "from-green to-teal",
  "from-amber to-orange",
];

export default function RunPage({ params }: { params: { run_id: string } }) {
  const runId = params.run_id;
  const { data: state, isLoading, isError } = useRun(runId);
  const stop = useStopRun(runId);
  const retry = useRetryRun();
  const cacheDecision = useCacheDecision(runId);
  const [focused, setFocused] = useState<StageId | null>(null);
  const [selectedProgramIdx, setSelectedProgramIdx] = useState(0);
  const [, setTick] = useState(0);
  const [leftPct, setLeftPct] = useState(34);
  const [isDesktop, setIsDesktop] = useState(false);
  const isDragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    setIsDesktop(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsDesktop(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const onDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const raw = ((e.clientX - rect.left) / rect.width) * 100;
      setLeftPct(Math.min(65, Math.max(18, raw)));
    };
    const onUp = () => {
      if (!isDragging.current) return;
      isDragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  useEffect(() => {
    if (state?.status !== "running" && state?.status !== "clarification_needed" && state?.status !== "cache_hit_pending") return;
    const t = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, [state?.status]);

  if (isLoading) {
    return (
      <Shell>
        <div className="flex h-[60vh] items-center justify-center gap-2 text-ink/40">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading run…</span>
        </div>
      </Shell>
    );
  }
  if (isError || !state) {
    return (
      <Shell>
        <div className="flex h-[60vh] flex-col items-center justify-center gap-3 text-ink/50">
          <AlertTriangle className="h-6 w-6 text-red" />
          <p className="text-sm">Run not found.</p>
          <Link href="/">
            <Button variant="outline" size="sm">
              <ArrowLeft className="h-4 w-4" /> Back home
            </Button>
          </Link>
        </div>
      </Shell>
    );
  }

  const doneCount = STAGE_IDS.filter((id) => state.stage_status?.[id] === "done").length;
  const pct = Math.round((doneCount / STAGE_IDS.length) * 100);

  const isComparison = state.mode === "compare";
  const compRun = state.comparison_run;

  // Current program info for comparison header
  const currentProgramIdx = compRun?.current_program_index ?? 0;
  const currentProgramName =
    compRun?.programs[currentProgramIdx] ?? state.program_name ?? null;
  const resolvedProgramName = state.program_name ?? currentProgramName;

  return (
    <div className="flex h-screen flex-col bg-canvas">
      <Topbar>
        {isComparison && state.status === "done" && (
          <Link href={`/run/${runId}/compare`}>
            <Button size="sm" variant="secondary">
              <GitCompareArrows className="h-4 w-4" /> View comparison
            </Button>
          </Link>
        )}
        {!isComparison && state.status === "done" && (
          <DownloadPDFButton state={state} variant="single" />
        )}
        {(state.status === "running" || state.status === "clarification_needed") && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => stop.mutate()}
            disabled={stop.isPending}
            className="border-red/40 text-red hover:bg-red/10 hover:border-red/60 transition-all"
          >
            {stop.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Square className="h-4 w-4 fill-current" />
            )}
            {stop.isPending ? "Stopping…" : "Stop"}
          </Button>
        )}
        {(state.status === "cancelled" || state.status === "error") && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              const body =
                isComparison && compRun
                  ? { user_input: state.user_input, mode: state.mode, programs: compRun.programs }
                  : { user_input: state.user_input, mode: state.mode };
              retry.mutate(body);
            }}
            disabled={retry.isPending}
            className="border-teal/40 text-teal hover:bg-teal/10 hover:border-teal/60 transition-all"
          >
            {retry.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RotateCcw className="h-4 w-4" />
            )}
            Retry
          </Button>
        )}
        <Link href="/history">
          <Button size="sm" variant="ghost" className="text-white hover:bg-white/10">
            <History className="h-4 w-4" /> History
          </Button>
        </Link>
        <Link href="/">
          <Button size="sm" variant="outline">
            <ArrowLeft className="h-4 w-4" /> New analysis
          </Button>
        </Link>
      </Topbar>

      <div ref={containerRef} className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* LEFT: pipeline graph + status */}
        <div
          className="flex min-h-0 flex-col border-b border-line bg-white lg:border-b-0 flex-shrink-0"
          style={isDesktop ? { width: `${leftPct}%` } : undefined}
        >
          <StatusBar state={state} doneCount={doneCount} pct={pct} />

          {/* progress track */}
          <div className="progress-track mx-4 my-0 rounded-none" style={{ height: 2 }}>
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>

          {/* In compare mode: show both programs' pipelines stacked */}
          {isComparison && compRun && compRun.total_programs >= 2 ? (
            <div className="flex min-h-0 flex-1 flex-col divide-y divide-line overflow-y-auto scroll-thin">
              {compRun.programs.map((prog, idx) => {
                const progStatus = compRun.program_statuses[idx] as "pending" | "running" | "done" | "error";
                const isActive = progStatus === "running";
                const isDone = progStatus === "done";
                const progState = compRun.program_states[idx] as AgentState | null;
                const effectiveState = isActive ? state : progState;
                const isSelected = state.status === "done" && idx === selectedProgramIdx;
                const isClickable = isDone && state.status === "done";

                return (
                  <div
                    key={idx}
                    className={cn(
                      "relative flex-1 min-h-[280px] transition-colors duration-200",
                      isActive && "bg-[#f8fdfd]",
                      isSelected && "ring-2 ring-inset ring-teal/30",
                      isClickable && !isSelected && "cursor-pointer hover:bg-soft-grey/20",
                    )}
                    onClick={isClickable ? () => { setSelectedProgramIdx(idx); setFocused(null); } : undefined}
                  >
                    {/* Program label banner */}
                    <div className={cn(
                      "flex items-center gap-2 px-3 py-1.5 border-b border-line/50 text-[10px] font-semibold",
                      isSelected ? "bg-teal/10 text-teal" : isActive ? "bg-teal/8 text-teal" : isDone ? "bg-green/8 text-green" : "bg-soft-grey/50 text-ink/40"
                    )}>
                      <span className={cn(
                        "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold border",
                        isSelected ? "bg-teal/30 border-teal/50 text-teal" : isActive ? "bg-teal/20 border-teal/30 text-teal" : isDone ? "bg-green/20 border-green/30 text-green" : "bg-ink/8 border-ink/15 text-ink/40"
                      )}>
                        {String.fromCharCode(65 + idx)}
                      </span>
                      <span className="truncate max-w-[160px]">{prog}</span>
                      {isActive && <Loader2 className="h-3 w-3 animate-spin ml-auto" />}
                      {isDone && !isSelected && <Check className="h-3 w-3 ml-auto" />}
                      {isSelected && <span className="ml-auto text-[9px] font-semibold bg-teal/15 text-teal px-1.5 py-0.5 rounded">Viewing</span>}
                      {progStatus === "pending" && <span className="ml-auto text-ink/30">Waiting…</span>}
                    </div>

                    {effectiveState ? (
                      <PipelineGraph
                        state={effectiveState}
                        focused={isSelected ? focused : null}
                        onFocus={isSelected ? setFocused : () => { setSelectedProgramIdx(idx); setFocused(null); }}
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center text-[11px] text-ink/25 py-10">
                        {progStatus === "pending" ? "Queued — will start after previous program completes" : "No data"}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="relative min-h-[300px] flex-1 lg:min-h-[400px]">
              <PipelineGraph state={state} focused={focused} onFocus={setFocused} />
            </div>
          )}

          {state.errors.length > 0 && (
            <div className="border-t border-line p-3">
              <ErrorRail errors={state.errors} />
            </div>
          )}
        </div>

        {/* Drag handle — desktop only */}
        <div
          className="hidden lg:flex items-center justify-center w-[5px] shrink-0 cursor-col-resize group relative z-10 bg-line hover:bg-teal/40 active:bg-teal/60 transition-colors"
          onMouseDown={onDividerMouseDown}
        >
          <div className="absolute inset-y-0 -left-1.5 -right-1.5" />
          <div className="h-8 w-[3px] rounded-full bg-ink/20 group-hover:bg-teal/60 transition-colors" />
        </div>

        {/* RIGHT: stage detail */}
        <div className="min-h-0 flex-1 overflow-y-auto scroll-thin bg-canvas px-4 py-5 sm:px-5 lg:px-7 lg:py-6">
          <div className="mx-auto max-w-4xl space-y-5">

            {/* ── Comparison queue panel ── */}
            {isComparison && compRun && (
              <ProgramQueuePanel
                info={compRun}
                currentStageStatus={state.stage_status ?? {}}
                overallStatus={state.status}
              />
            )}

            {/* ── Current program header (comparison) ── */}
            {isComparison && compRun && state.status === "running" && (
              <ComparisonProgramHeader
                programs={compRun.programs}
                currentIndex={currentProgramIdx}
                resolvedName={resolvedProgramName}
                totalPrograms={compRun.total_programs}
              />
            )}

            {/* ── Single program header (single / converse) ── */}
            {!isComparison && resolvedProgramName && (
              <div className="flex items-center gap-3 rounded-[10px] border border-line bg-white px-4 py-3 shadow-sm">
                <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-navy to-teal flex items-center justify-center shrink-0">
                  <span className="text-xs font-bold text-white">
                    {(resolvedProgramName ?? "?")[0]}
                  </span>
                </div>
                <div>
                  <p className="text-sm font-semibold text-navy leading-tight">
                    {resolvedProgramName}
                  </p>
                  {state.brand && state.brand !== resolvedProgramName && (
                    <p className="text-[11px] text-ink/45">{state.brand}</p>
                  )}
                </div>
                <div className="ml-auto">
                  {state.status === "done" ? (
                    <CheckCircle2 className="h-5 w-5 text-green" />
                  ) : state.status === "running" ? (
                    <CircleDot className="h-5 w-5 text-teal animate-pulse" />
                  ) : null}
                </div>
              </div>
            )}

            {state.status === "cancelled" && (
              <CancelledBanner
                onRetry={() => {
                  const body =
                    isComparison && compRun
                      ? { user_input: state.user_input, mode: state.mode, programs: compRun.programs }
                      : { user_input: state.user_input, mode: state.mode };
                  retry.mutate(body);
                }}
                isPending={retry.isPending}
              />
            )}

            {state.status === "clarification_needed" &&
              state.validation_result?.status === "needs_clarification" && (
                <ClarificationPanel
                  runId={runId}
                  validationResult={state.validation_result}
                />
              )}

            {/* ── Program switcher (comparison + done) ── */}
            {isComparison && compRun && state.status === "done" && (
              <ProgramSwitcher
                programs={compRun.programs}
                programStatuses={compRun.program_statuses as string[]}
                selectedIdx={selectedProgramIdx}
                onSelect={(idx) => { setSelectedProgramIdx(idx); setFocused(null); }}
              />
            )}

            {/* ── Single-program intelligence brief ── */}
            {!isComparison && state.status === "done" && state.final_brief && (
              <SingleProgramBriefPanel
                programName={state.program_name}
                fieldReport={state.field_report}
              />
            )}

            <StageDetailPanel
              state={
                isComparison && compRun && state.status === "done"
                  ? (compRun.program_states[selectedProgramIdx] as AgentState ?? state)
                  : state
              }
              focusedStage={focused}
            />

            {(state.mode === "single" || state.mode === "converse") && (
              <section id="converse" className="scroll-mt-4">
                <h2 className="mb-2.5 flex items-center gap-2 text-[13px] font-semibold text-navy">
                  Follow-up conversation
                  <span className="text-[11px] font-normal text-ink/40">
                    grounded in {state.extracted_claims.length} extracted claims
                  </span>
                </h2>
                <div className="rounded-[10px] border border-line bg-white shadow-sm">
                  <ConverseThread
                    runId={runId}
                    conversation={state.conversation ?? []}
                    disabled={state.status !== "done"}
                  />
                </div>
              </section>
            )}

            {/* ── Comparison complete CTA ── */}
            {isComparison && state.status === "done" && compRun && (
              <ComparisonCompleteCTA
                runId={runId}
                programs={compRun.programs}
                programStatuses={compRun.program_statuses as string[]}
              />
            )}

            {state.cost_report && state.cost_report.lines.length > 0 && (
              <CostPanel report={state.cost_report} />
            )}
          </div>
        </div>
      </div>

      {state.status === "cache_hit_pending" && state.cache_hit && (
        <CacheDecisionModal
          open
          programQuery={state.user_input}
          result={{
            found: true,
            program_name: state.cache_hit.program_name,
            brand: state.cache_hit.brand ?? undefined,
            age_days: state.cache_hit.age_days ?? undefined,
            run_datetime: state.cache_hit.run_date ?? undefined,
          }}
          onDecision={(choice) => {
            if (choice === "cancel") {
              stop.mutate();
              return;
            }
            cacheDecision.mutate(choice === "view" ? "use_cache" : "fresh");
          }}
        />
      )}
    </div>
  );
}

// ── Comparison program transition header ──────────────────────────────────────

function ComparisonProgramHeader({
  programs,
  currentIndex,
  resolvedName,
  totalPrograms,
}: {
  programs: string[];
  currentIndex: number;
  resolvedName: string | null;
  totalPrograms: number;
}) {
  return (
    <div className="flex items-center gap-3 rounded-[10px] border border-teal/30 bg-gradient-to-r from-[#e8f8f8] to-white px-4 py-3 shadow-sm">
      {/* Animated program letter badge */}
      <div className="relative shrink-0">
        <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-teal to-navy flex items-center justify-center shadow-sm">
          <span className="text-sm font-bold text-white">
            {String.fromCharCode(65 + currentIndex)}
          </span>
        </div>
        <span className="absolute -bottom-1 -right-1 h-3.5 w-3.5 rounded-full bg-teal border-2 border-white flex items-center justify-center">
          <span className="h-1.5 w-1.5 rounded-full bg-white animate-ping" />
        </span>
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-0.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-teal">
            Running now
          </span>
          <span className="text-[10px] text-ink/30">·</span>
          <span className="text-[10px] text-ink/40">
            {currentIndex + 1} of {totalPrograms}
          </span>
        </div>
        <p className="text-sm font-semibold text-navy truncate">
          {resolvedName ?? programs[currentIndex]}
        </p>
      </div>

      {/* Mini breadcrumb of all programs */}
      <div className="hidden sm:flex items-center gap-1 shrink-0">
        {programs.map((p, i) => (
          <div key={i} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="h-3 w-3 text-ink/25" />}
            <span
              className={cn(
                "text-[10px] font-medium rounded px-1.5 py-0.5",
                i === currentIndex
                  ? "bg-teal/15 text-teal font-semibold"
                  : i < currentIndex
                    ? "text-green/70"
                    : "text-ink/30",
              )}
            >
              {p.split(" ")[0]}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Comparison complete CTA ───────────────────────────────────────────────────

function ComparisonCompleteCTA({
  runId,
  programs,
  programStatuses,
}: {
  runId: string;
  programs: string[];
  programStatuses: string[];
}) {
  const doneCount = programStatuses.filter((s) => s === "done").length;

  return (
    <div className="relative overflow-hidden rounded-[12px] border border-teal/30 bg-gradient-to-br from-[#e2f3f3] to-white p-5 shadow-sm">
      <span className="absolute inset-y-0 left-0 w-1 bg-teal" />
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-navy flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-green shrink-0" />
            All {doneCount} programs analysed
          </p>
          <p className="mt-0.5 text-[12px] text-ink/55">
            {programs.slice(0, doneCount).join(", ")} — ready for comparison
          </p>
        </div>
        <Link href={`/run/${runId}/compare`}>
          <Button size="sm">
            <GitCompareArrows className="h-4 w-4" />
            View full comparison
          </Button>
        </Link>
      </div>
    </div>
  );
}

// ── Status bar ────────────────────────────────────────────────────────────────

function StatusBar({
  state,
  doneCount,
  pct,
}: {
  state: AgentState;
  doneCount: number;
  pct: number;
}) {
  const isRunning = state.status === "running";
  const isDone = state.status === "done";
  const isCancelled = state.status === "cancelled";
  const compRun = state.comparison_run;

  const progressLabel =
    compRun
      ? `${compRun.program_statuses.filter((s) => s === "done").length}/${compRun.total_programs} programs`
      : `${doneCount}/${PIPELINE_STAGES.length} · ${pct}%`;

  return (
    <div className={cn(
      "flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5 transition-colors duration-500",
      isCancelled ? "bg-amber/5" : "bg-white"
    )}>
      <span className="inline-flex items-center gap-1 rounded-md bg-soft-grey px-2 py-1 font-mono text-[10px] text-ink/45">
        <Hash className="h-3 w-3" />
        {state.run_id.replace(/^run_/, "").slice(0, 10)}
      </span>

      <Badge tone={MODE_TONE[state.mode]} className="text-[10px]">
        {MODE_LABEL[state.mode]}
      </Badge>

      <span className="inline-flex items-center gap-1 text-[11px] text-ink/45">
        <Clock className="h-3 w-3" />
        <span className="stat-num tabular-nums">
          {elapsed(state.created_at, (isDone || isCancelled) ? state.updated_at : undefined)}
        </span>
      </span>

      <div className="ml-auto flex items-center gap-2">
        {state.errors.length > 0 && !isCancelled && (
          <Badge tone="red" dot>
            {state.errors.length} error{state.errors.length === 1 ? "" : "s"}
          </Badge>
        )}
        {state.status === "clarification_needed" ? (
          <Badge tone="blue" dot>Awaiting clarification</Badge>
        ) : state.status === "cache_hit_pending" ? (
          <Badge tone="blue" dot>Previous analysis found</Badge>
        ) : isRunning ? (
          <Badge tone="teal" dot>
            <Loader2 className="h-3 w-3 animate-spin" />
            {progressLabel}
          </Badge>
        ) : isDone ? (
          <Badge tone="green" dot>
            <CheckCircle2 className="h-3 w-3" />
            Complete
          </Badge>
        ) : isCancelled ? (
          <Badge tone="amber" dot>
            <OctagonX className="h-3 w-3" />
            Stopped
          </Badge>
        ) : null}
      </div>
    </div>
  );
}

// ── Cost panel ────────────────────────────────────────────────────────────────

const PROVIDER_COLORS: Record<string, string> = {
  gemini: "bg-blue/10 text-blue",
  groq: "bg-teal/10 text-teal",
  tavily: "bg-navy/10 text-navy",
  firecrawl: "bg-green/10 text-green",
};

function CostPanel({ report }: { report: CostReport }) {
  const fmtTokens = (n: number) =>
    n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
  const fmtUsd = (n: number) =>
    n < 0.001 ? `<$0.001` : `$${n.toFixed(4)}`;

  return (
    <section className="scroll-mt-4">
      <h2 className="mb-2.5 flex items-center gap-2 text-[13px] font-semibold text-navy">
        <DollarSign className="h-3.5 w-3.5 text-green" />
        API Cost Report
        <span className="ml-auto font-mono text-[12px] font-semibold text-green">
          {report.total_usd_cost < 0.001
            ? "<$0.001"
            : `$${report.total_usd_cost.toFixed(4)}`}
        </span>
      </h2>

      <div className="rounded-[10px] border border-line bg-white shadow-sm overflow-hidden">
        <div className="grid grid-cols-4 gap-3 border-b border-line px-4 py-3">
          {[
            { label: "Total calls", value: String(report.total_calls) },
            { label: "Prompt tokens", value: fmtTokens(report.total_prompt_tokens) },
            { label: "Output tokens", value: fmtTokens(report.total_completion_tokens) },
            { label: "Est. cost", value: fmtUsd(report.total_usd_cost) },
          ].map(({ label, value }) => (
            <div key={label} className="text-center">
              <p className="font-mono text-[13px] font-semibold text-navy tabular-nums">{value}</p>
              <p className="text-[10px] text-ink/45 mt-0.5">{label}</p>
            </div>
          ))}
        </div>

        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-line bg-soft-grey/50">
              <th className="px-4 py-2 text-left text-ink/50 font-medium">Provider</th>
              <th className="px-3 py-2 text-left text-ink/50 font-medium">Stage</th>
              <th className="px-3 py-2 text-right text-ink/50 font-medium">Calls</th>
              <th className="px-3 py-2 text-right text-ink/50 font-medium">In tokens</th>
              <th className="px-3 py-2 text-right text-ink/50 font-medium">Out tokens</th>
              <th className="px-4 py-2 text-right text-ink/50 font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {report.lines.map((line, i) => (
              <tr
                key={`${line.provider}-${line.stage}`}
                className={i % 2 === 0 ? "bg-white" : "bg-soft-grey/20"}
              >
                <td className="px-4 py-2">
                  <span
                    className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${
                      PROVIDER_COLORS[line.provider] ?? "bg-soft-grey text-ink/60"
                    }`}
                  >
                    {line.provider}
                  </span>
                </td>
                <td className="px-3 py-2 text-ink/70">{line.stage}</td>
                <td className="px-3 py-2 text-right tabular-nums text-ink/60">{line.calls}</td>
                <td className="px-3 py-2 text-right tabular-nums text-ink/60">
                  {line.prompt_tokens > 0 ? fmtTokens(line.prompt_tokens) : "—"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink/60">
                  {line.completion_tokens > 0 ? fmtTokens(line.completion_tokens) : "—"}
                </td>
                <td className="px-4 py-2 text-right tabular-nums font-mono text-ink/80">
                  {fmtUsd(line.usd_cost)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <p className="px-4 py-2 text-[10px] text-ink/30 border-t border-line">
          Estimates based on published list prices. Tavily/Firecrawl costs are approximate per-call rates.
        </p>
      </div>
    </section>
  );
}

// ── Cancelled banner ──────────────────────────────────────────────────────────

function CancelledBanner({
  onRetry,
  isPending,
}: {
  onRetry: () => void;
  isPending: boolean;
}) {
  return (
    <div className="relative overflow-hidden rounded-[12px] border border-amber/30 bg-gradient-to-br from-amber/8 to-white p-5 shadow-sm animate-in fade-in slide-in-from-top-2 duration-500">
      <span className="absolute inset-y-0 left-0 w-1 bg-amber rounded-l-[12px]" />
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div className="h-9 w-9 rounded-xl bg-amber/15 border border-amber/25 flex items-center justify-center shrink-0">
            <OctagonX className="h-4 w-4 text-amber" />
          </div>
          <div>
            <p className="text-sm font-semibold text-ink leading-tight">Run stopped mid-way</p>
            <p className="text-[11px] text-ink/50 mt-0.5">
              The pipeline was cancelled before it could complete. Partial results may be shown below.
            </p>
          </div>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={onRetry}
          disabled={isPending}
          className="border-teal/40 text-teal hover:bg-teal/10 hover:border-teal/60 shrink-0"
        >
          {isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RotateCcw className="h-4 w-4" />
          )}
          {isPending ? "Starting…" : "Retry from start"}
        </Button>
      </div>
    </div>
  );
}

// ── Program switcher tabs ─────────────────────────────────────────────────────

const SWITCHER_ACCENT = [
  { bg: "bg-teal/15 border-teal/35 text-teal", dot: "bg-teal", ring: "ring-teal/30" },
  { bg: "bg-blue/15 border-blue/35 text-blue", dot: "bg-blue", ring: "ring-blue/30" },
  { bg: "bg-navy/15 border-navy/35 text-navy", dot: "bg-navy", ring: "ring-navy/30" },
  { bg: "bg-green/15 border-green/35 text-green", dot: "bg-green", ring: "ring-green/30" },
  { bg: "bg-amber/15 border-amber/35 text-amber", dot: "bg-amber", ring: "ring-amber/30" },
];

function ProgramSwitcher({
  programs,
  programStatuses,
  selectedIdx,
  onSelect,
}: {
  programs: string[];
  programStatuses: string[];
  selectedIdx: number;
  onSelect: (idx: number) => void;
}) {
  return (
    <div className="rounded-[10px] border border-line bg-white shadow-sm overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-line bg-soft-grey/30">
        <span className="text-[10px] font-bold uppercase tracking-wider text-ink/45">
          View pipeline results for
        </span>
      </div>
      <div className="flex divide-x divide-line">
        {programs.map((prog, idx) => {
          const c = SWITCHER_ACCENT[idx % SWITCHER_ACCENT.length];
          const isSelected = idx === selectedIdx;
          const isDone = programStatuses[idx] === "done";
          return (
            <button
              key={idx}
              onClick={() => onSelect(idx)}
              className={cn(
                "flex-1 flex items-center gap-2.5 px-4 py-3 text-left transition-all duration-150",
                isSelected ? cn("bg-white", c.bg.replace("bg-", "bg-").replace("/15", "/8")) : "hover:bg-soft-grey/40",
              )}
            >
              <span
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold transition-all",
                  isSelected ? cn(c.bg, "ring-2", c.ring) : "bg-ink/6 border-ink/15 text-ink/40",
                )}
              >
                {String.fromCharCode(65 + idx)}
              </span>
              <div className="min-w-0 flex-1">
                <p
                  className={cn(
                    "truncate text-[12px] font-semibold leading-tight",
                    isSelected ? "text-navy" : "text-ink/50",
                  )}
                >
                  {prog}
                </p>
                {isDone && (
                  <p className="text-[10px] text-ink/35 mt-0.5">
                    {isSelected ? "Showing pipeline" : "Click to view"}
                  </p>
                )}
              </div>
              {isSelected && (
                <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", c.dot)} />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      <Topbar>
        <Link href="/history">
          <Button size="sm" variant="ghost" className="text-white hover:bg-white/10">
            <History className="h-4 w-4" /> History
          </Button>
        </Link>
        <Link href="/">
          <Button size="sm" variant="outline">
            <ArrowLeft className="h-4 w-4" /> Home
          </Button>
        </Link>
      </Topbar>
      <div className="mx-auto max-w-5xl px-5">{children}</div>
    </div>
  );
}
