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

export default function RunPage({ params }: { params: { run_id: string } }) {
  const runId = params.run_id;
  const { data: state, isLoading, isError } = useRun(runId);
  const [focused, setFocused] = useState<StageId | null>(null);
  const [, setTick] = useState(0);

  // live elapsed ticker while running or awaiting clarification
  useEffect(() => {
    if (state?.status !== "running" && state?.status !== "clarification_needed") return;
    const t = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, [state?.status]);

  if (isLoading) {
    return (
      <Shell>
        <div className="flex h-[60vh] items-center justify-center text-ink/40">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading run…
        </div>
      </Shell>
    );
  }
  if (isError || !state) {
    return (
      <Shell>
        <div className="flex h-[60vh] flex-col items-center justify-center gap-3 text-ink/50">
          <AlertTriangle className="h-6 w-6 text-red" />
          <p>Run not found.</p>
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

  return (
    <div className="flex h-screen flex-col">
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

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(300px,36%)_1fr]">
        {/* LEFT: pipeline graph */}
        <div className="flex min-h-0 flex-col border-b border-line bg-paper lg:border-b-0 lg:border-r">
          <StatusBar state={state} doneCount={doneCount} />
          <div className="relative min-h-[320px] flex-1 lg:min-h-[420px]">
            <PipelineGraph state={state} focused={focused} onFocus={setFocused} />
          </div>
          {state.errors.length > 0 && (
            <div className="border-t border-line p-3">
              <ErrorRail errors={state.errors} />
            </div>
          )}
        </div>

        {/* RIGHT: stage detail + final output */}
        <div className="min-h-0 overflow-y-auto scroll-thin bg-paper px-4 py-5 sm:px-5 sm:py-6 lg:px-7">
          <div className="mx-auto max-w-4xl space-y-7">
            {state.status === "clarification_needed" &&
              state.validation_result?.status === "needs_clarification" && (
                <ClarificationPanel
                  runId={runId}
                  validationResult={state.validation_result}
                />
              )}
            {state.mode === "converse" && (
              <section id="converse" className="scroll-mt-4">
                <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-navy">
                  Follow-up conversation
                  <span className="text-xs font-normal text-ink/45">
                    grounded in {state.extracted_claims.length} extracted claims
                  </span>
                </h2>
                <div className="rounded-card border border-line bg-white shadow-panel">
                  <ConverseThread
                    runId={runId}
                    conversation={state.conversation ?? []}
                    disabled={state.status !== "done"}
                  />
                </div>
              </section>
            )}
            <StageDetailPanel state={state} focusedStage={focused} />
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusBar({
  state,
  doneCount,
}: {
  state: AgentState;
  doneCount: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-white px-4 py-3">
      <Badge tone="grey" className="font-mono">
        <Hash className="h-3 w-3" />
        {state.run_id.replace(/^run_/, "").slice(0, 12)}
      </Badge>
      <Badge tone={MODE_TONE[state.mode]} className="capitalize">
        {state.mode}
      </Badge>
      <span className="inline-flex items-center gap-1 text-xs text-ink/55">
        <Clock className="h-3.5 w-3.5" />
        <span className="stat-num tabular-nums">
          {elapsed(
            state.created_at,
            state.status === "done" ? state.updated_at : undefined,
          )}
        </span>
      </span>
      <div className="ml-auto flex items-center gap-2">
        {state.errors.length > 0 && (
          <Badge tone="red" dot>
            {state.errors.length} error{state.errors.length === 1 ? "" : "s"}
          </Badge>
        )}
        {state.status === "clarification_needed" ? (
          <Badge tone="blue" dot>
            Awaiting clarification
          </Badge>
        ) : state.status === "running" ? (
          <Badge tone="teal" dot>
            <Loader2 className="h-3 w-3 animate-spin" />
            {doneCount}/{STAGE_IDS.length} stages
          </Badge>
        ) : (
          <Badge tone="green" dot>
            Complete · {doneCount}/{STAGE_IDS.length}
          </Badge>
        )}
      </div>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
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
