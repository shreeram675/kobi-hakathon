import { AlertTriangle } from "lucide-react";
import { Badge, type Tone } from "@/components/ui/badge";
import {
  OUTCOME_ACCENT,
  RESOLUTION_ACCENT,
  STATUS_ACCENT,
  TOKENS,
} from "@/lib/colors";
import type {
  ClaimStatus,
  ComparisonOutcome,
  ConflictResolution,
  Volatility,
} from "@/lib/types";

const FALLBACK_ACCENT = { fg: "grey" as const, hex: TOKENS.grey, soft: TOKENS.softGrey, label: "Unknown" };

/** Maps ClaimStatus -> colour + label (supported/conflicting/not_found/null/rejected). */
export function StatusBadge({ status }: { status: ClaimStatus }) {
  const accent = STATUS_ACCENT[status] ?? FALLBACK_ACCENT;
  return (
    <Badge tone={accent.fg as Tone} dot>
      {accent.label}
    </Badge>
  );
}

/** Maps ComparisonItem.outcome -> colour + label (all 6 outcomes). */
export function OutcomeBadge({ outcome }: { outcome: ComparisonOutcome }) {
  const accent = OUTCOME_ACCENT[outcome] ?? FALLBACK_ACCENT;
  return (
    <Badge tone={accent.fg as Tone} dot>
      {accent.label}
    </Badge>
  );
}

export function ResolutionBadge({
  status,
}: {
  status: ConflictResolution;
}) {
  const accent = RESOLUTION_ACCENT[status] ?? FALLBACK_ACCENT;
  return (
    <Badge tone={accent.fg as Tone} dot>
      {accent.label}
    </Badge>
  );
}

/** HIGH in amber, LOW in grey. */
export function VolatilityChip({ volatility }: { volatility: Volatility }) {
  if (volatility === "high") {
    return (
      <Badge tone="amber">
        <AlertTriangle className="h-3 w-3" />
        HIGH
      </Badge>
    );
  }
  return <Badge tone="grey">LOW</Badge>;
}
