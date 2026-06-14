"use client";

import { ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { OutcomeBadge } from "./badges";
import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  FIELDS_BY_CATEGORY,
  type Category,
  fieldLabel,
  isHighVolatility,
} from "@/lib/schema";
import { cn, renderValue } from "@/lib/format";
import type {
  AgentState,
  ComparisonOutcome,
  ComparisonOutput,
} from "@/lib/types";
import { AlertTriangle } from "lucide-react";

function valueMap(state: AgentState | null | undefined): Map<string, unknown> {
  const m = new Map<string, unknown>();
  (state?.field_report?.entries ?? []).forEach((e) => m.set(e.field_path, e.value));
  return m;
}

/** Side-by-side outcome table (compare mode), grouped by category. */
export function ComparisonTable({
  comparison,
  stateA,
  stateB,
}: {
  comparison: ComparisonOutput;
  stateA: AgentState;
  stateB: AgentState;
}) {
  const valsA = useMemo(() => valueMap(stateA), [stateA]);
  const valsB = useMemo(() => valueMap(stateB), [stateB]);
  const outcomeByField = useMemo(() => {
    const m = new Map<string, ComparisonOutcome>();
    comparison.items.forEach((it) => m.set(it.field_path, it.outcome));
    return m;
  }, [comparison]);

  return (
    <div className="overflow-hidden rounded-card border border-line bg-white shadow-panel">
      <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1.4fr)_minmax(0,1.4fr)_170px] gap-3 border-b border-line bg-navy px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-white/80">
        <span>Comparison field</span>
        <span className="truncate text-teal-100">{comparison.program_a}</span>
        <span className="truncate">{comparison.program_b}</span>
        <span>Outcome</span>
      </div>
      <div className="divide-y divide-line">
        {CATEGORY_ORDER.map((category) => (
          <CategoryBlock
            key={category}
            category={category}
            valsA={valsA}
            valsB={valsB}
            outcomeByField={outcomeByField}
          />
        ))}
      </div>
    </div>
  );
}

function CategoryBlock({
  category,
  valsA,
  valsB,
  outcomeByField,
}: {
  category: Category;
  valsA: Map<string, unknown>;
  valsB: Map<string, unknown>;
  outcomeByField: Map<string, ComparisonOutcome>;
}) {
  const [open, setOpen] = useState(true);
  const fields = FIELDS_BY_CATEGORY[category];
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
        fields.map((fp) => {
          const outcome = outcomeByField.get(fp) ?? "null";
          return (
            <div
              key={fp}
              className="grid grid-cols-1 gap-2 px-4 py-2.5 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1.4fr)_minmax(0,1.4fr)_170px] sm:items-center sm:gap-3"
            >
              <div className="flex items-center gap-1.5">
                {isHighVolatility(fp) && (
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber" />
                )}
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">{fieldLabel(fp)}</p>
                  <p className="truncate font-mono text-[10px] text-ink/40">{fp}</p>
                </div>
              </div>
              <ValueCell value={valsA.get(fp)} />
              <ValueCell value={valsB.get(fp)} />
              <div>
                <OutcomeBadge outcome={outcome} />
              </div>
            </div>
          );
        })}
    </div>
  );
}

function ValueCell({ value }: { value: unknown }) {
  if (value == null) return <span className="text-sm text-ink/30">—</span>;
  return <span className="line-clamp-2 text-sm text-ink/80">{renderValue(value)}</span>;
}
