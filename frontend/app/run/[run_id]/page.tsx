"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Clock,
  GitCompareArrows,
  Hash,
  Loader2,
  CheckCircle2,
  CircleDot,
} from "lucide-react";
import { Topbar } from "@/components/Topbar";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PipelineGraph } from "@/components/PipelineGraph";
import { StageDetailPanel } from "@/components/StageDetailPanel";
import { ErrorRail } from "@/components/ErrorRail";
import { ConverseThread } from "@/components/ConverseThread";
import { ClarificationPanel } from "@/components/ClarificationPanel";
import { useRun } from "@/lib/hooks";
import { STAGE_IDS, type StageId } from "@/lib/schema";
import { cn, elapsed } from "@/lib/format";
import type { AgentState, RunMode } from "@/lib/types";

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

export default function RunPage({ params }: { params: { run_id: string } }) {
  const runId = params.run_id;
  const { data: state, isLoading, isError } = useRun(runId);
  const [focused, setFocused] = useState<StageId | null>(null);
  const [, setTick] = useState(0);

  useEffect(() => {
    if (state?.status !== "running" && state?.status !== "clarification_needed") return;
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

  return (
    <div className="flex h-screen flex-col bg-canvas">
      <Topbar>
        {state.mode === "compare" && state.status === "done" && (
          <Link href={`/run/${runId}/compare`}>
            <Button size="sm" variant="secondary">
              <GitCompareArrows className="h-4 w-4" /> View comparison
            </Button>
          </Link>
        )}
        <Link href="/">
          <Button size="sm" variant="outline">
            <ArrowLeft className="h-4 w-4" /> New analysis
          </Button>
        </Link>
      </Topbar>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(280px,34%)_1fr]">
        {/* LEFT: pipeline graph + status */}
        <div className="flex min-h-0 flex-col border-b border-line bg-white lg:border-b-0 lg:border-r lg:border-line">
          <StatusBar state={state} doneCount={doneCount} pct={pct} />

          {/* progress track */}
          <div className="progress-track mx-4 my-0 rounded-none" style={{ height: 2 }}>
            <div
              className="progress-fill"
              style={{ width: `${pct}%` }}
            />
          </div>

          <div className="relative min-h-[300px] flex-1 lg:min-h-[400px]">
            <PipelineGraph state={state} focused={focused} onFocus={setFocused} />
          </div>

          {state.errors.length > 0 && (
            <div className="border-t border-line p-3">
              <ErrorRail errors={state.errors} />
            </div>
          )}
        </div>

        {/* RIGHT: stage detail */}
        <div className="min-h-0 overflow-y-auto scroll-thin bg-canvas px-4 py-5 sm:px-5 lg:px-7 lg:py-6">
          <div className="mx-auto max-w-4xl space-y-5">
            {/* program header if resolved */}
            {state.program_name && (
              <div className="flex items-center gap-3 rounded-[10px] border border-line bg-white px-4 py-3 shadow-sm">
                <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-navy to-teal flex items-center justify-center shrink-0">
                  <span className="text-xs font-bold text-white">
                    {(state.program_name ?? "?")[0]}
                  </span>
                </div>
                <div>
                  <p className="text-sm font-semibold text-navy leading-tight">
                    {state.program_name}
                  </p>
                  {state.brand && state.brand !== state.program_name && (
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

            {state.status === "clarification_needed" &&
              state.validation_result?.status === "needs_clarification" && (
                <ClarificationPanel
                  runId={runId}
                  validationResult={state.validation_result}
                />
              )}

            <StageDetailPanel state={state} focusedStage={focused} />

            {state.mode === "converse" && (
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
          </div>
        </div>
      </div>
    </div>
  );
}

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

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-white px-4 py-2.5">
      {/* run id */}
      <span className="inline-flex items-center gap-1 rounded-md bg-soft-grey px-2 py-1 font-mono text-[10px] text-ink/45">
        <Hash className="h-3 w-3" />
        {state.run_id.replace(/^run_/, "").slice(0, 10)}
      </span>

      {/* mode */}
      <Badge tone={MODE_TONE[state.mode]} className="text-[10px]">
        {MODE_LABEL[state.mode]}
      </Badge>

      {/* elapsed */}
      <span className="inline-flex items-center gap-1 text-[11px] text-ink/45">
        <Clock className="h-3 w-3" />
        <span className="stat-num tabular-nums">
          {elapsed(state.created_at, isDone ? state.updated_at : undefined)}
        </span>
      </span>

      {/* spacer */}
      <div className="ml-auto flex items-center gap-2">
        {state.errors.length > 0 && (
          <Badge tone="red" dot>
            {state.errors.length} error{state.errors.length === 1 ? "" : "s"}
          </Badge>
        )}
        {state.status === "clarification_needed" ? (
          <Badge tone="blue" dot>Awaiting clarification</Badge>
        ) : isRunning ? (
          <Badge tone="teal" dot>
            <Loader2 className="h-3 w-3 animate-spin" />
            {doneCount}/{STAGE_IDS.length} · {pct}%
          </Badge>
        ) : isDone ? (
          <Badge tone="green" dot>
            <CheckCircle2 className="h-3 w-3" />
            Complete
          </Badge>
        ) : null}
      </div>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      <Topbar>
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
