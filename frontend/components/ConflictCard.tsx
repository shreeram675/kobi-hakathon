import { GitMerge } from "lucide-react";
import { ResolutionBadge } from "./badges";
import { SourcePill } from "./SourcePill";
import { RESOLUTION_ACCENT, TOKENS } from "@/lib/colors";
import { fieldLabel } from "@/lib/schema";
import { cn, signed } from "@/lib/format";
import type { Claim, ConflictRecord } from "@/lib/types";

const FALLBACK_ACCENT = { hex: TOKENS.grey, soft: TOKENS.softGrey, fg: "grey", label: "Unknown" };

/** Per-conflict card, colour-coded by resolution_status, with a score_gap delta badge. */
export function ConflictCard({ conflict, claims = [] }: { conflict: ConflictRecord; claims?: Claim[] }) {
  const sourceUrls = Array.from(
    new Set(
      claims
        .filter((c) => c.field_path === conflict.field_path && c.source_url)
        .map((c) => c.source_url as string),
    ),
  );
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
      {(conflict.value_a || conflict.value_b) && (
        <div className="mt-2.5 grid grid-cols-[1fr_auto_1fr] items-start gap-1.5 rounded-md bg-soft-grey/50 px-2.5 py-2 text-xs">
          <div className="min-w-0">
            <p className="text-[9px] font-semibold uppercase tracking-wide text-teal mb-0.5">A</p>
            <p className="font-medium text-ink break-words leading-snug">{conflict.value_a || "—"}</p>
            {(conflict.url_a || sourceUrls[0]) && (
              <SourcePill url={(conflict.url_a || sourceUrls[0])!} />
            )}
          </div>
          <span className="text-[10px] font-bold text-ink/25 self-center mt-3">vs</span>
          <div className="min-w-0">
            <p className="text-[9px] font-semibold uppercase tracking-wide text-blue mb-0.5">B</p>
            <p className="font-medium text-ink break-words leading-snug">{conflict.value_b || "—"}</p>
            {(conflict.url_b || sourceUrls[1]) && (
              <SourcePill url={(conflict.url_b || sourceUrls[1])!} />
            )}
          </div>
        </div>
      )}
      <p className="mt-2 text-xs leading-relaxed text-ink/65">
        {conflict.judge_reason}
      </p>
    </div>
  );
}

export function ConflictGrid({ conflicts, claims = [] }: { conflicts: ConflictRecord[]; claims?: Claim[] }) {
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
        <ConflictCard key={c.conflict_id} conflict={c} claims={claims} />
      ))}
    </div>
  );
}
