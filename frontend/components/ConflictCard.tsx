import { GitMerge } from "lucide-react";
import { ResolutionBadge } from "./badges";
import { RESOLUTION_ACCENT, TOKENS } from "@/lib/colors";
import { fieldLabel } from "@/lib/schema";
import { cn, signed } from "@/lib/format";
import type { ConflictRecord } from "@/lib/types";

const FALLBACK_ACCENT = { hex: TOKENS.grey, soft: TOKENS.softGrey, fg: "grey", label: "Unknown" };

/** Per-conflict card, colour-coded by resolution_status, with a score_gap delta badge. */
export function ConflictCard({ conflict }: { conflict: ConflictRecord }) {
  const accent = RESOLUTION_ACCENT[conflict.resolution_status] ?? FALLBACK_ACCENT;
  return (
    <div
      className="relative overflow-hidden rounded-card border bg-white p-3.5 shadow-sm"
      style={{ borderColor: accent.hex + "55" }}
    >
      <span
        className="absolute inset-y-0 left-0 w-1"
        style={{ background: accent.hex }}
        aria-hidden
      />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <GitMerge className="h-3.5 w-3.5 text-ink/40" />
            <p className="truncate text-sm font-medium text-ink">
              {fieldLabel(conflict.field_path)}
            </p>
          </div>
          <p className="truncate font-mono text-[10px] text-ink/40">
            {conflict.field_path}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <ResolutionBadge status={conflict.resolution_status} />
          <span
            className="stat-num rounded-pill px-2 py-0.5 text-[11px] font-semibold tabular-nums"
            style={{ background: accent.soft, color: accent.hex }}
            title="Confidence score gap between conflicting claims"
          >
            Δ {signed(conflict.score_gap)}
          </span>
        </div>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-ink/65">
        {conflict.judge_reason}
      </p>
      <p className="mt-1.5 text-[10px] text-ink/40">
        {(conflict.claim_ids ?? []).length} competing claim
        {(conflict.claim_ids ?? []).length === 1 ? "" : "s"}
      </p>
    </div>
  );
}

export function ConflictGrid({ conflicts }: { conflicts: ConflictRecord[] }) {
  if (!conflicts.length) {
    return (
      <p className="rounded-card border border-dashed border-line bg-soft-grey/30 px-4 py-6 text-center text-sm text-ink/45">
        No conflicts detected — all claims corroborated cleanly.
      </p>
    );
  }
  return (
    <div className={cn("grid gap-3 sm:grid-cols-2")}>
      {conflicts.map((c) => (
        <ConflictCard key={c.conflict_id} conflict={c} />
      ))}
    </div>
  );
}
