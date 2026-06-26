import { GitMerge, Scale } from "lucide-react";
import { ResolutionBadge } from "./badges";
import { SourcePill } from "./SourcePill";
import { RESOLUTION_ACCENT, TOKENS } from "@/lib/colors";
import { fieldLabel } from "@/lib/schema";
import { cn, signed } from "@/lib/format";
import type { ConflictRecord } from "@/lib/types";

const FALLBACK_ACCENT = { hex: TOKENS.grey, soft: TOKENS.softGrey, fg: "grey", label: "Unknown" };

export function ConflictCard({ conflict }: { conflict: ConflictRecord }) {
  const accent = RESOLUTION_ACCENT[conflict.resolution_status] ?? FALLBACK_ACCENT;
  const gap = conflict.score_gap;
  const gapHigh = Math.abs(gap) >= 0.4;

  return (
    <div
      className="relative overflow-hidden rounded-[10px] border bg-white shadow-sm analyst-card"
      style={{ borderColor: accent.hex + "40" }}
    >
      {/* top accent strip */}
      <div
        className="h-[3px] w-full"
        style={{ background: `linear-gradient(90deg, ${accent.hex}, ${accent.hex}55)` }}
      />

      <div className="p-3.5">
        {/* header row */}
        <div className="mb-2.5 flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 mb-0.5">
              <GitMerge className="h-3.5 w-3.5 shrink-0 text-ink/35" />
              <p className="truncate text-[13px] font-semibold text-ink">
                {fieldLabel(conflict.field_path)}
              </p>
            </div>
            <p className="font-mono text-[10px] text-ink/35">{conflict.field_path}</p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <ResolutionBadge status={conflict.resolution_status} />
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-[10px] font-bold tabular-nums",
                gapHigh ? "ring-1" : "",
              )}
              style={{
                background: accent.soft,
                color: accent.hex,
              }}
              title="Confidence score gap"
            >
              <Scale className="h-3 w-3" />Δ {signed(gap)}
            </span>
          </div>
        </div>

        {/* A vs B */}
        {(conflict.value_a || conflict.value_b) && (
          <div className="grid grid-cols-[1fr_16px_1fr] items-start gap-1.5 rounded-lg bg-soft-grey/60 px-3 py-2.5 text-xs mb-2.5">
            <div className="min-w-0">
              <p className="mb-1 text-[9px] font-bold uppercase tracking-[0.1em] text-teal">Source A</p>
              <p className="font-medium text-ink leading-snug break-words">{conflict.value_a || "—"}</p>
              {conflict.url_a && <div className="mt-1"><SourcePill url={conflict.url_a} /></div>}
            </div>
            <span className="text-[10px] font-bold text-ink/20 self-center text-center">↔</span>
            <div className="min-w-0">
              <p className="mb-1 text-[9px] font-bold uppercase tracking-[0.1em] text-blue">Source B</p>
              <p className="font-medium text-ink leading-snug break-words">{conflict.value_b || "—"}</p>
              {conflict.url_b && <div className="mt-1"><SourcePill url={conflict.url_b} /></div>}
            </div>
          </div>
        )}

        {/* judge reasoning */}
        {conflict.judge_reason && (
          <p className="text-[11.5px] leading-relaxed text-ink/60 border-l-2 border-line pl-2.5 italic">
            {conflict.judge_reason}
          </p>
        )}
      </div>
    </div>
  );
}

export function ConflictGrid({ conflicts }: { conflicts: ConflictRecord[] }) {
  if (!conflicts.length) {
    return (
      <div className="rounded-[10px] border border-dashed border-line bg-soft-grey/30 px-4 py-8 text-center">
        <p className="text-sm font-medium text-ink/40">No conflicts detected</p>
        <p className="mt-1 text-xs text-ink/30">All claims corroborated cleanly across sources.</p>
      </div>
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
