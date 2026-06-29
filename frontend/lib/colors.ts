/**
 * Raw hex tokens (matching tailwind.config + sample_output.html) for use in
 * contexts that can't take Tailwind classes — Recharts, inline SVG, ReactFlow.
 */

export const TOKENS = {
  ink: "#17202a",
  navy: "#17324d",
  teal: "#0f7c7d",
  green: "#16704a",
  amber: "#a66100",
  red: "#b83232",
  blue: "#1f65b7",
  softGreen: "#e8f6ef",
  softAmber: "#fff2d8",
  softRed: "#fde8e8",
  softGrey: "#eef2f6",
  paper: "#f6f8fb",
  line: "#d9e2ec",
  grey: "#64748b",
} as const;

import type {
  ClaimStatus,
  ComparisonOutcome,
  ConflictResolution,
  FieldReportStatus,
} from "./types";

export interface Accent {
  /** Tailwind text/border color class root, e.g. "green". */
  fg: string;
  /** solid hex for charts. */
  hex: string;
  /** soft background hex. */
  soft: string;
  /** human label. */
  label: string;
}

export const STATUS_ACCENT: Record<ClaimStatus, Accent> = {
  supported: { fg: "green", hex: TOKENS.green, soft: TOKENS.softGreen, label: "Accepted" },
  conflicting: { fg: "amber", hex: TOKENS.amber, soft: TOKENS.softAmber, label: "Debate resolved" },
  "not_found/manual_review_needed": {
    fg: "red",
    hex: TOKENS.red,
    soft: TOKENS.softRed,
    label: "Human review required",
  },
  null: { fg: "grey", hex: TOKENS.grey, soft: TOKENS.softGrey, label: "N/A / Not searched" },
  rejected_unsupported: { fg: "red", hex: TOKENS.red, soft: TOKENS.softRed, label: "Rejected" },
};

export const OUTCOME_ACCENT: Record<ComparisonOutcome, Accent> = {
  match: { fg: "green", hex: TOKENS.green, soft: TOKENS.softGreen, label: "Match" },
  factual_mismatch: { fg: "amber", hex: TOKENS.amber, soft: TOKENS.softAmber, label: "Factual mismatch" },
  missing_in_a: { fg: "grey", hex: TOKENS.grey, soft: TOKENS.softGrey, label: "Missing in A" },
  missing_in_b: { fg: "grey", hex: TOKENS.grey, soft: TOKENS.softGrey, label: "Missing in B" },
  manual_review_needed: { fg: "red", hex: TOKENS.red, soft: TOKENS.softRed, label: "Human review required" },
  null: { fg: "grey", hex: TOKENS.grey, soft: TOKENS.softGrey, label: "N/A" },
};

export const RESOLUTION_ACCENT: Record<ConflictResolution, Accent> = {
  auto_resolved: { fg: "green", hex: TOKENS.green, soft: TOKENS.softGreen, label: "Auto-resolved" },
  debate_required: { fg: "amber", hex: TOKENS.amber, soft: TOKENS.softAmber, label: "Debate required" },
  manual_review_needed: { fg: "red", hex: TOKENS.red, soft: TOKENS.softRed, label: "Manual review" },
  merged: { fg: "teal", hex: TOKENS.teal, soft: "#e0f4f4", label: "Merged" },
  field_type_resolved: { fg: "blue", hex: TOKENS.blue, soft: "#e6effb", label: "Strategy resolved" },
};

export const FIELD_REPORT_ACCENT: Record<FieldReportStatus, Accent> = {
  extracted: { fg: "green", hex: TOKENS.green, soft: TOKENS.softGreen, label: "Extracted" },
  ambiguous: { fg: "amber", hex: TOKENS.amber, soft: TOKENS.softAmber, label: "Ambiguous" },
  not_found: { fg: "red", hex: TOKENS.red, soft: TOKENS.softRed, label: "Not found" },
  flagged: { fg: "blue", hex: TOKENS.blue, soft: "#e6effb", label: "Flagged" },
};

/** Stable colour per source_type for pies / query grouping. */
const SOURCE_TYPE_PALETTE = [
  TOKENS.teal,
  TOKENS.blue,
  TOKENS.amber,
  TOKENS.green,
  "#7a5195",
  "#ef5675",
  TOKENS.navy,
  "#bc5090",
];

const sourceTypeColorCache = new Map<string, string>();
let sourceTypeCursor = 0;

export function colorForSourceType(sourceType: string): string {
  const key = sourceType.toLowerCase();
  if (!sourceTypeColorCache.has(key)) {
    sourceTypeColorCache.set(
      key,
      SOURCE_TYPE_PALETTE[sourceTypeCursor % SOURCE_TYPE_PALETTE.length],
    );
    sourceTypeCursor += 1;
  }
  return sourceTypeColorCache.get(key)!;
}

/** green >= 0.80, amber 0.50-0.79, red < 0.50 */
export function confidenceHex(confidence: number | null | undefined): string {
  if (confidence == null) return TOKENS.grey;
  if (confidence >= 0.8) return TOKENS.green;
  if (confidence >= 0.5) return TOKENS.amber;
  return TOKENS.red;
}

export function confidenceTone(
  confidence: number | null | undefined,
): "green" | "amber" | "red" | "grey" {
  if (confidence == null) return "grey";
  if (confidence >= 0.8) return "green";
  if (confidence >= 0.5) return "amber";
  return "red";
}
