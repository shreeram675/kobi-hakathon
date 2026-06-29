"use client";

import { AlertTriangle, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { ConfidenceBar } from "./ConfidenceBar";
import { StatusBadge, VolatilityChip } from "./badges";
import { SourcePillRow } from "./SourcePill";
import { Progress } from "@/components/ui/progress";
import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  FIELDS_BY_CATEGORY,
  FOCUSED_SCHEMA_FIELD_PATHS,
  type Category,
  fieldLabel,
  isHighVolatility,
  leafOf,
  volatilityFor,
} from "@/lib/schema";
import { TOKENS } from "@/lib/colors";
import { cn, renderValue } from "@/lib/format";
import type { Claim, ClaimStatus, FieldReport } from "@/lib/types";

interface Row {
  field_path: string;
  value: unknown;
  confidence: number | null;
  status: ClaimStatus;
  sources: string[];
  all_values?: Array<{ value: string; source_url: string | null; context: string | null }>;
  conflict_type?: string;
}

function buildRows(report: FieldReport | null, claims: Claim[]): Map<string, Row> {
  const claimByField = new Map(claims.map((c) => [c.field_path, c]));
  const entryByField = new Map((report?.entries ?? []).map((e) => [e.field_path, e]));
  const rows = new Map<string, Row>();
  for (const category of CATEGORY_ORDER) {
    for (const fp of FIELDS_BY_CATEGORY[category].filter((f) => FOCUSED_SCHEMA_FIELD_PATHS.has(f))) {
      const claim = claimByField.get(fp);
      const entry = entryByField.get(fp);
      rows.set(fp, {
        field_path: fp,
        value: entry?.value ?? claim?.value_json ?? null,
        confidence: entry?.confidence ?? claim?.confidence ?? null,
        status: claim?.status ?? "null",
        sources: entry?.source_urls ?? (claim?.source_url ? [claim.source_url] : []),
        all_values: entry?.all_values,
        conflict_type: entry?.conflict_type,
      });
    }
  }
  return rows;
}

const COVERED: ClaimStatus[] = ["supported", "conflicting"];

export function SchemaFieldTable({
  report,
  claims,
}: {
  report: FieldReport | null;
  claims: Claim[];
}) {
  const rows = useMemo(() => buildRows(report, claims), [report, claims]);
  const [openAll, setOpenAll] = useState(true);

  return (
    <div className="overflow-hidden rounded-card border border-line bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-line bg-soft-grey/40 px-4 py-2.5">
        <p className="text-xs font-medium text-ink/60">
          {rows.size} schema fields across {CATEGORY_ORDER.length} categories
        </p>
        <button
          onClick={() => setOpenAll((v) => !v)}
          className="text-xs font-medium text-teal hover:underline"
        >
          {openAll ? "Collapse all" : "Expand all"}
        </button>
      </div>
      <div className="hidden grid-cols-[minmax(0,1.6fr)_minmax(0,1.6fr)_120px_84px_150px_minmax(0,1.1fr)] gap-3 border-b border-line px-4 py-2 text-[10px] font-semibold uppercase tracking-wide text-ink/45 lg:grid">
        <span>Field</span>
        <span>Value</span>
        <span>Confidence</span>
        <span>Volatility</span>
        <span>Status</span>
        <span>Sources</span>
      </div>
      <div className="divide-y divide-line">
        {CATEGORY_ORDER.map((category) => (
          <CategoryGroup
            key={category}
            category={category}
            rows={rows}
            open={openAll}
          />
        ))}
      </div>
    </div>
  );
}

function CategoryGroup({
  category,
  rows,
  open: openAll,
}: {
  category: Category;
  rows: Map<string, Row>;
  open: boolean;
}) {
  const [open, setOpen] = useState(true);
  const fields = FIELDS_BY_CATEGORY[category].filter((f) => FOCUSED_SCHEMA_FIELD_PATHS.has(f));
  const effectiveOpen = openAll && open;

  const covered = fields.filter((fp) => COVERED.includes(rows.get(fp)!.status)).length;
  const total = fields.length;

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 bg-white px-4 py-2.5 text-left transition-colors hover:bg-soft-grey/40"
        aria-expanded={effectiveOpen}
      >
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 text-ink/40 transition-transform",
            effectiveOpen && "rotate-90",
          )}
        />
        <span className="text-sm font-semibold text-navy">
          {CATEGORY_LABELS[category]}
        </span>
        <span className="stat-num text-xs text-ink/50 tabular-nums">
          {covered}/{total}
        </span>
        <div className="ml-auto w-28">
          <Progress
            value={covered / total}
            color={covered / total >= 0.6 ? TOKENS.green : covered / total >= 0.3 ? TOKENS.amber : TOKENS.red}
          />
        </div>
      </button>
      {effectiveOpen && (
        <div className="divide-y divide-line/70 bg-soft-grey/20">
          {fields.map((fp) => (
            <FieldRow key={fp} row={rows.get(fp)!} />
          ))}
        </div>
      )}
    </div>
  );
}

function FieldRow({ row }: { row: Row }) {
  const high = isHighVolatility(row.field_path);
  return (
    <div className="grid grid-cols-1 gap-2 px-4 py-2.5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1.6fr)_120px_84px_150px_minmax(0,1.1fr)] lg:items-center lg:gap-3">
      {/* Field */}
      <div className="flex items-start gap-1.5">
        {high && (
          <AlertTriangle
            className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber"
            aria-label="High-volatility field"
          />
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-ink">
            {fieldLabel(row.field_path)}
          </p>
          <p className="truncate font-mono text-[10px] text-ink/40">
            {row.field_path}
          </p>
        </div>
      </div>
      {/* Value */}
      <div className="text-sm text-ink/80">
        {row.value == null ? (
          <span className="text-ink/30">—</span>
        ) : (
          <div>
            <span className="line-clamp-2">{renderValue(row.value)}</span>
            {row.conflict_type && row.conflict_type !== "contradictory" && row.all_values && row.all_values.length > 1 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {row.all_values.map((av, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1 rounded bg-teal/10 px-1.5 py-0.5 text-[10px] text-teal"
                    title={av.source_url ?? undefined}
                  >
                    {av.context ? `${av.context}: ` : ""}{av.value}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      {/* Confidence */}
      <div className="lg:px-0">
        <ConfidenceBar value={row.confidence} width={70} />
      </div>
      {/* Volatility */}
      <div>
        <VolatilityChip volatility={volatilityFor(row.field_path)} />
      </div>
      {/* Status */}
      <div>
        <StatusBadge status={row.status} />
      </div>
      {/* Sources */}
      <div>
        <SourcePillRow urls={row.sources} />
      </div>
    </div>
  );
}
