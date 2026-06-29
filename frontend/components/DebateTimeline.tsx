"use client";

import { ExternalLink, Gavel, GitMerge, Layers, Scale, Swords, Trophy } from "lucide-react";
import { Collapsible } from "@/components/ui/collapsible";
import { ResolutionBadge } from "./badges";
import { Badge } from "@/components/ui/badge";
import { fieldLabel } from "@/lib/schema";
import { cn, pct } from "@/lib/format";
import type { AdjudicatedClaim, DebateRound } from "@/lib/types";

const PHASE_LABEL: Record<DebateRound["phase"], string> = {
  opening: "Opening statement",
  opening_b: "Opening statement",
  cross: "Cross-examination",
  cross_b: "Cross-examination",
  evidence: "Evidence weighing",
  final_decision: "Final decision",
};

function agentTone(phase: DebateRound["phase"]): "teal" | "blue" | "amber" | "navy" {
  if (phase === "opening" || phase === "cross") return "teal";
  if (phase === "opening_b" || phase === "cross_b") return "blue";
  if (phase === "evidence") return "amber";
  return "navy";
}

function PhaseIcon({ phase }: { phase: DebateRound["phase"] }) {
  if (phase === "evidence") return <Scale className="h-3.5 w-3.5" />;
  if (phase === "final_decision") return <Gavel className="h-3.5 w-3.5" />;
  return <Swords className="h-3.5 w-3.5" />;
}

/** Relabel A/B advocates (e.g. with program names in compare mode). */
function displayAgent(
  round: DebateRound,
  labels?: { a: string; b: string },
): string {
  if (!labels) return round.agent;
  if (round.phase === "opening" || round.phase === "cross") return `${labels.a} Advocate`;
  if (round.phase === "opening_b" || round.phase === "cross_b") return `${labels.b} Advocate`;
  return round.agent;
}

function RoundCard({
  round,
  labels,
}: {
  round: DebateRound;
  labels?: { a: string; b: string };
}) {
  const tone = agentTone(round.phase);
  return (
    <div className="relative pl-6">
      <span
        className={cn(
          "absolute left-[7px] top-2 h-2 w-2 -translate-x-1/2 rounded-full ring-4 ring-white",
          tone === "teal" && "bg-teal",
          tone === "blue" && "bg-blue",
          tone === "amber" && "bg-amber",
          tone === "navy" && "bg-navy",
        )}
      />
      <Collapsible
        defaultOpen
        className="rounded-card border border-line bg-white"
        headerClassName="px-3 py-2"
        header={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={tone}>
              <PhaseIcon phase={round.phase} />
              Round {round.round}
            </Badge>
            <span className="text-xs font-semibold text-ink">
              {displayAgent(round, labels)}
            </span>
            <span className="text-[11px] text-ink/45">{PHASE_LABEL[round.phase]}</span>
          </div>
        }
      >
        <p className="px-3 pb-3 pt-0.5 text-xs leading-relaxed text-ink/70">
          {round.argument}
        </p>
      </Collapsible>
    </div>
  );
}

const CONFLICT_TYPE_LABEL: Record<string, string> = {
  complementary: "Complementary — both valid in different contexts",
  range: "Range — values span different categories/conditions",
  union: "Union — combined from multiple sources",
  recency: "Recency — most recent value kept",
  majority_vote: "Majority vote — most-common value selected",
  contradictory: "Contradictory — one value overruled",
};

function AllValuesRow({ claim }: { claim: AdjudicatedClaim }) {
  if (!claim.all_values?.length || claim.conflict_type === "contradictory") return null;
  return (
    <div className="mt-3 rounded-md border border-teal/30 bg-teal/5 px-3 py-2.5">
      <div className="mb-1.5 flex items-center gap-1.5">
        <Layers className="h-3.5 w-3.5 text-teal" />
        <span className="text-[10px] font-semibold uppercase tracking-wide text-teal">
          {CONFLICT_TYPE_LABEL[claim.conflict_type ?? ""] ?? "All values"}
        </span>
      </div>
      <div className="space-y-1.5">
        {claim.all_values.map((av, i) => (
          <div key={i} className="flex flex-wrap items-baseline gap-2">
            <span className="text-sm font-semibold text-ink">{av.value}</span>
            {av.context && (
              <span className="rounded bg-teal/10 px-1.5 py-0.5 text-[10px] font-medium text-teal">
                {av.context}
              </span>
            )}
            {av.source_url && (
              <a
                href={av.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-0.5 text-[10px] text-ink/40 hover:text-teal"
              >
                <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                <span className="truncate max-w-[160px]">{av.source_url.replace(/^https?:\/\//, "")}</span>
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ClaimVsRow({ claim }: { claim: AdjudicatedClaim }) {
  const isMerged = claim.winner === "MERGE" || claim.resolution_status === "merged" || claim.resolution_status === "field_type_resolved";

  // For merged/complementary, show AllValuesRow instead of the vs layout
  if (isMerged) return <AllValuesRow claim={claim} />;

  if (!claim.value_a && !claim.value_b) return null;
  return (
    <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-start gap-2 rounded-md border border-line bg-white px-3 py-2.5">
      <div className="min-w-0">
        <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-teal">Claim A</p>
        <p className="text-sm font-semibold text-ink break-words">{claim.value_a || "—"}</p>
        {claim.url_a && (
          <a
            href={claim.url_a}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 flex items-center gap-1 text-[10px] text-ink/40 hover:text-teal truncate"
          >
            <ExternalLink className="h-2.5 w-2.5 shrink-0" />
            <span className="truncate">{claim.url_a.replace(/^https?:\/\//, "")}</span>
          </a>
        )}
      </div>
      <span className="mt-1 text-xs font-bold text-ink/30 self-center">vs</span>
      <div className="min-w-0">
        <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue">Claim B</p>
        <p className="text-sm font-semibold text-ink break-words">{claim.value_b || "—"}</p>
        {claim.url_b && (
          <a
            href={claim.url_b}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 flex items-center gap-1 text-[10px] text-ink/40 hover:text-blue truncate"
          >
            <ExternalLink className="h-2.5 w-2.5 shrink-0" />
            <span className="truncate">{claim.url_b.replace(/^https?:\/\//, "")}</span>
          </a>
        )}
      </div>
    </div>
  );
}

function DebateBlock({
  claim,
  labels,
  defaultOpen,
}: {
  claim: AdjudicatedClaim;
  labels?: { a: string; b: string };
  defaultOpen: boolean;
}) {
  const fp = claim.field_path || claim.field_name || "";
  const isMerged = claim.winner === "MERGE" || claim.resolution_status === "merged" || claim.resolution_status === "field_type_resolved";
  const rounds = claim.rounds ?? [];

  return (
    <Collapsible
      defaultOpen={defaultOpen}
      className={cn(
        "rounded-card border p-3",
        isMerged ? "border-teal/30 bg-teal/5" : "border-line bg-soft-grey/30",
      )}
      headerClassName="px-1 py-1"
      header={
        <div className="flex flex-wrap items-center gap-2">
          {isMerged
            ? <GitMerge className="h-4 w-4 text-teal" />
            : <Trophy className="h-4 w-4 text-amber" />
          }
          <span className="text-sm font-semibold text-navy">
            {fp ? fieldLabel(fp) : "Unknown field"}
          </span>
          {fp && <span className="font-mono text-[10px] text-ink/40">{fp}</span>}
          <span className="ml-auto flex items-center gap-2">
            <span className="stat-num text-[11px] text-ink/55">
              conf. {pct(claim.confidence)}
            </span>
            <ResolutionBadge status={claim.resolution_status} />
          </span>
        </div>
      }
    >
      <ClaimVsRow claim={claim} />
      {rounds.length > 0 && (
        <div className="mt-3 space-y-2 border-l border-dashed border-line pl-1">
          {rounds.map((r) => (
            <RoundCard key={r.round} round={r} labels={labels} />
          ))}
        </div>
      )}
    </Collapsible>
  );
}

/** 6-round collapsible debate sequence, one block per adjudicated conflict. */
export function DebateTimeline({
  adjudicated,
  labels,
}: {
  adjudicated: AdjudicatedClaim[];
  labels?: { a: string; b: string };
}) {
  if (!(adjudicated ?? []).length) {
    return (
      <p className="rounded-card border border-dashed border-line bg-soft-grey/30 px-4 py-6 text-center text-sm text-ink/45">
        No debates were required — no conflicts reached the adversarial stage.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {adjudicated.map((claim, i) => (
        <DebateBlock
          key={claim.conflict_id}
          claim={claim}
          labels={labels}
          defaultOpen={i === 0}
        />
      ))}
    </div>
  );
}
