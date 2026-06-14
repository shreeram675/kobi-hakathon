"use client";

import Link from "next/link";
import { useMemo } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Award,
  Loader2,
  MoveRight,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { Topbar } from "@/components/Topbar";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ComparisonTable } from "@/components/ComparisonTable";
import { CategoryWinnerGrid } from "@/components/CategoryWinnerGrid";
import { DebateTimeline } from "@/components/DebateTimeline";
import { DataQualityGauge } from "@/components/charts/DataQualityGauge";
import { useRun } from "@/lib/hooks";
import { cn, pct, signed } from "@/lib/format";
import type { ComparisonOutcome } from "@/lib/types";

export default function ComparePage({
  params,
}: {
  params: { run_id: string };
}) {
  const runId = params.run_id;
  const { data: state, isLoading } = useRun(runId);

  const counts = useMemo(() => {
    const c: Record<ComparisonOutcome, number> = {
      match: 0,
      factual_mismatch: 0,
      missing_in_a: 0,
      missing_in_b: 0,
      manual_review_needed: 0,
      null: 0,
    };
    state?.comparison_output?.items.forEach((it) => (c[it.outcome] += 1));
    return c;
  }, [state]);

  if (isLoading) {
    return (
      <Frame runId={runId}>
        <Centered>
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…
        </Centered>
      </Frame>
    );
  }

  if (!state || state.mode !== "compare" || !state.comparison_output || !state.compare_b) {
    return (
      <Frame runId={runId}>
        <Centered>
          <div className="text-center text-ink/50">
            <p>Comparison not ready yet.</p>
            <p className="mt-1 text-sm">
              {state && state.mode !== "compare"
                ? "This run is not a comparison."
                : "The pipeline is still processing both programs."}
            </p>
            <Link href={`/run/${runId}`} className="mt-3 inline-block">
              <Button variant="outline" size="sm">
                <ArrowLeft className="h-4 w-4" /> Back to run
              </Button>
            </Link>
          </div>
        </Centered>
      </Frame>
    );
  }

  const comparison = state.comparison_output;
  const stateB = state.compare_b;
  const qa = state.data_quality;
  const qb = stateB.data_quality;
  const delta = qa - qb;
  const dataGap = counts.missing_in_a + counts.missing_in_b + counts.null;

  const leader =
    Math.abs(delta) < 0.02
      ? null
      : delta > 0
        ? comparison.program_a
        : comparison.program_b;
  const verdict =
    counts.manual_review_needed > 5
      ? `High number of review-flagged fields (${counts.manual_review_needed}) — resolve human-review items before a confident verdict.`
      : leader
        ? `${leader} leads on overall data completeness (${pct(Math.max(qa, qb))} vs ${pct(Math.min(qa, qb))}). ${counts.factual_mismatch} factual mismatches and ${dataGap} data gaps remain for analyst attention.`
        : `Both programs are evenly matched on data quality (${pct(qa)}). Differentiation comes down to ${counts.factual_mismatch} factual mismatches across the schema.`;

  return (
    <Frame runId={runId}>
      <div className="mx-auto max-w-[1500px] space-y-6 px-5 py-7">
        {/* title */}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-ink/45">
              Comparison
            </p>
            <h1 className="mt-0.5 flex items-center gap-2 text-2xl font-semibold text-navy">
              {comparison.program_a}
              <MoveRight className="h-5 w-5 text-ink/30" />
              {comparison.program_b}
            </h1>
          </div>
          <Link href={`/run/${runId}`}>
            <Button variant="outline" size="sm">
              <ArrowLeft className="h-4 w-4" /> Back to run
            </Button>
          </Link>
        </div>

        {/* quality cards + delta */}
        <div className="grid gap-4 lg:grid-cols-[1fr_auto_1fr]">
          <QualityCard name={comparison.program_a} value={qa} tone="teal" />
          <div className="flex flex-col items-center justify-center gap-1 rounded-card border border-line bg-white px-5 py-4 shadow-sm">
            <span className="text-[10px] font-medium uppercase tracking-wide text-ink/45">
              Quality delta
            </span>
            <span
              className={cn(
                "stat-num flex items-center gap-1 text-xl font-semibold",
                delta >= 0 ? "text-teal" : "text-blue",
              )}
            >
              {delta >= 0 ? (
                <TrendingUp className="h-5 w-5" />
              ) : (
                <TrendingDown className="h-5 w-5" />
              )}
              {signed(delta)}
            </span>
            <span className="text-[10px] text-ink/45">A − B</span>
          </div>
          <QualityCard name={comparison.program_b} value={qb} tone="blue" />
        </div>

        {/* metric chips */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Chip label="Matches" value={counts.match} tone="green" />
          <Chip label="Factual mismatches" value={counts.factual_mismatch} tone="amber" />
          <Chip label="Data gaps" value={dataGap} tone="grey" />
          <Chip label="Review flags" value={counts.manual_review_needed} tone="red" />
        </div>

        {/* comparison table */}
        <ComparisonTable comparison={comparison} stateA={state} stateB={stateB} />

        {/* category winners */}
        <div>
          <h2 className="mb-3 text-base font-semibold text-navy">
            Category winners
          </h2>
          <CategoryWinnerGrid
            stateA={state}
            stateB={stateB}
            nameA={comparison.program_a}
            nameB={comparison.program_b}
          />
        </div>

        {/* recommendation */}
        <div className="relative overflow-hidden rounded-card border border-teal/30 bg-gradient-to-br from-[#e2f3f3] to-white p-5 shadow-panel">
          <span className="absolute inset-y-0 left-0 w-1 bg-teal" aria-hidden />
          <div className="flex items-start gap-3">
            <Award className="mt-0.5 h-5 w-5 shrink-0 text-teal" />
            <div>
              <p className="text-sm font-semibold text-navy">
                Final recommendation
              </p>
              <p className="mt-1 text-sm leading-relaxed text-ink/75">{verdict}</p>
            </div>
          </div>
        </div>

        {/* debate timeline with advocate labels */}
        <div>
          <h2 className="mb-3 text-base font-semibold text-navy">
            Adversarial debate
          </h2>
          <DebateTimeline
            adjudicated={state.adjudicated ?? []}
            labels={{ a: comparison.program_a, b: comparison.program_b }}
          />
        </div>
      </div>
    </Frame>
  );
}

function QualityCard({
  name,
  value,
  tone,
}: {
  name: string;
  value: number;
  tone: "teal" | "blue";
}) {
  return (
    <div className="flex items-center gap-4 rounded-card border border-line bg-white px-5 py-4 shadow-sm">
      <DataQualityGauge value={value} label="Data quality" size={150} />
      <div>
        <span
          className={cn(
            "text-[10px] font-semibold uppercase tracking-wide",
            tone === "teal" ? "text-teal" : "text-blue",
          )}
        >
          {tone === "teal" ? "Program A" : "Program B"}
        </span>
        <p className="text-lg font-semibold leading-tight text-navy">{name}</p>
      </div>
    </div>
  );
}

function Chip({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "green" | "amber" | "grey" | "red";
}) {
  return (
    <div className="rounded-card border border-line bg-white px-4 py-3 shadow-sm">
      <p className="text-[11px] font-medium uppercase tracking-wide text-ink/45">
        {label}
      </p>
      <p
        className={cn(
          "stat-num mt-1 text-2xl font-semibold",
          tone === "green" && "text-green",
          tone === "amber" && "text-amber",
          tone === "grey" && "text-ink",
          tone === "red" && "text-red",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function Frame({
  runId,
  children,
}: {
  runId: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen">
      <Topbar>
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
    <div className="flex h-[70vh] items-center justify-center text-ink/40">
      {children}
    </div>
  );
}
