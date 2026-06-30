"use client";

import { ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  FIELDS_BY_CATEGORY,
  FOCUSED_SCHEMA_FIELD_PATHS,
  type Category,
  fieldLabel,
  isHighVolatility,
} from "@/lib/schema";
import { cn, renderValue } from "@/lib/format";
import type {
  AgentState,
  ComparisonOutput,
  FieldReportEntry,
} from "@/lib/types";
import { AlertTriangle } from "lucide-react";
import { SourcePillRow } from "@/components/SourcePill";

function entryMap(state: AgentState | null | undefined): Map<string, FieldReportEntry> {
  const m = new Map<string, FieldReportEntry>();
  (state?.field_report?.entries ?? []).forEach((e) => m.set(e.field_path, e));
  return m;
}

/** Side-by-side comparison table (compare mode), grouped by category. */
export function ComparisonTable({
  comparison,
  stateA,
  stateB,
}: {
  comparison: ComparisonOutput;
  stateA: AgentState;
  stateB: AgentState;
}) {
  const entriesA = useMemo(() => entryMap(stateA), [stateA]);
  const entriesB = useMemo(() => entryMap(stateB), [stateB]);

  return (
    <div className="overflow-hidden rounded-card border border-line bg-white shadow-panel">
      <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1.4fr)_minmax(0,1.4fr)] gap-3 border-b border-line bg-navy px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-white/80">
        <span>Field</span>
        <span className="truncate">{comparison.program_a}</span>
        <span className="truncate">{comparison.program_b}</span>
      </div>
      <div className="divide-y divide-line">
        {CATEGORY_ORDER.map((category) => (
          <CategoryBlock
            key={category}
            category={category}
            entriesA={entriesA}
            entriesB={entriesB}
          />
        ))}
      </div>
    </div>
  );
}

function CategoryBlock({
  category,
  entriesA,
  entriesB,
}: {
  category: Category;
  entriesA: Map<string, FieldReportEntry>;
  entriesB: Map<string, FieldReportEntry>;
}) {
  const [open, setOpen] = useState(true);
  const fields = FIELDS_BY_CATEGORY[category].filter((f) => FOCUSED_SCHEMA_FIELD_PATHS.has(f));
  if (fields.length === 0) return null;
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 bg-soft-grey/40 px-4 py-2 text-left hover:bg-soft-grey/70"
        aria-expanded={open}
      >
        <ChevronRight
          className={cn("h-4 w-4 text-ink/40 transition-transform", open && "rotate-90")}
        />
        <span className="text-sm font-semibold text-navy">
          {CATEGORY_LABELS[category]}
        </span>
      </button>
      {open &&
        fields.map((fp) => (
          <div
            key={fp}
            className="grid grid-cols-1 gap-2 px-4 py-2.5 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1.4fr)_minmax(0,1.4fr)] sm:items-start sm:gap-3"
          >
            <div className="flex items-center gap-1.5 pt-0.5">
              {isHighVolatility(fp) && (
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber" />
              )}
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink">{fieldLabel(fp)}</p>
                <p className="truncate font-mono text-[10px] text-ink/40">{fp}</p>
              </div>
            </div>
            <ValueCell entry={entriesA.get(fp)} />
            <ValueCell entry={entriesB.get(fp)} />
          </div>
        ))}
    </div>
  );
}

function ValueCell({ entry }: { entry: FieldReportEntry | undefined }) {
  if (!entry || entry.value == null) return <span className="text-sm text-ink/30">—</span>;
  return (
    <div className="space-y-1.5">
      <span className="line-clamp-2 text-sm text-ink/80">{renderValue(entry.value)}</span>
      {entry.source_urls?.length > 0 && (
        <SourcePillRow urls={entry.source_urls} />
      )}
    </div>
  );
}
