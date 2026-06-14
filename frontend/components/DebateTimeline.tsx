"use client";

import { Gavel, Scale, Swords, Trophy } from "lucide-react";
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

function DebateBlock({
  claim,
  labels,
  defaultOpen,
}: {
  claim: AdjudicatedClaim;
  labels?: { a: string; b: string };
  defaultOpen: boolean;
}) {
  return (
    <Collapsible
      defaultOpen={defaultOpen}
      className="rounded-card border border-line bg-soft-grey/30 p-3"
      headerClassName="px-1 py-1"
      header={
        <div className="flex flex-wrap items-center gap-2">
          <Trophy className="h-4 w-4 text-amber" />
          <span className="text-sm font-semibold text-navy">
            {fieldLabel(claim.field_path)}
          </span>
          <span className="font-mono text-[10px] text-ink/40">{claim.field_path}</span>
          <span className="ml-auto flex items-center gap-2">
            <span className="stat-num text-[11px] text-ink/55">
              decision conf. {pct(claim.confidence)}
            </span>
            <ResolutionBadge status={claim.resolution_status} />
          </span>
        </div>
      }
    >
      <div className="mt-3 space-y-2 border-l border-dashed border-line pl-1">
        {(claim.rounds ?? []).map((r) => (
          <RoundCard key={r.round} round={r} labels={labels} />
        ))}
      </div>
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
