"use client";

import { useMemo } from "react";
import { Crown, Minus, ShieldQuestion } from "lucide-react";
import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  FIELDS_BY_CATEGORY,
  type Category,
} from "@/lib/schema";
import { cn, pct } from "@/lib/format";
import type { AgentState } from "@/lib/types";

type Winner = "A" | "B" | "Tie" | "Review";

interface CatResult {
  category: Category;
  avgA: number | null;
  avgB: number | null;
  coverA: number;
  coverB: number;
  winner: Winner;
}

function avgConfidence(state: AgentState, fields: string[]): { avg: number | null; cover: number } {
  const byField = new Map((state.field_report?.entries ?? []).map((e) => [e.field_path, e]));
  const vals: number[] = [];
  fields.forEach((fp) => {
    const e = byField.get(fp);
    if (e && e.confidence != null && (e.status === "extracted" || e.status === "ambiguous")) {
      vals.push(e.confidence);
    }
  });
  if (!vals.length) return { avg: null, cover: 0 };
  return { avg: vals.reduce((s, v) => s + v, 0) / vals.length, cover: vals.length };
}

/** 8-card grid: which program scored higher on avg confidence per category. */
export function CategoryWinnerGrid({
  stateA,
  stateB,
  nameA,
  nameB,
}: {
  stateA: AgentState;
  stateB: AgentState;
  nameA: string;
  nameB: string;
}) {
  const results = useMemo<CatResult[]>(() => {
    return CATEGORY_ORDER.map((category) => {
      const fields = FIELDS_BY_CATEGORY[category];
      const a = avgConfidence(stateA, fields);
      const b = avgConfidence(stateB, fields);
      let winner: Winner;
      if (a.cover < 2 && b.cover < 2) winner = "Review";
      else if (a.avg == null) winner = "B";
      else if (b.avg == null) winner = "A";
      else if (Math.abs(a.avg - b.avg) < 0.03) winner = "Tie";
      else winner = a.avg > b.avg ? "A" : "B";
      return { category, avgA: a.avg, avgB: b.avg, coverA: a.cover, coverB: b.cover, winner };
    });
  }, [stateA, stateB]);

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {results.map((r) => (
        <WinnerCard key={r.category} result={r} nameA={nameA} nameB={nameB} />
      ))}
    </div>
  );
}

function WinnerCard({
  result,
  nameA,
  nameB,
}: {
  result: CatResult;
  nameA: string;
  nameB: string;
}) {
  const { winner } = result;
  const label =
    winner === "A" ? nameA : winner === "B" ? nameB : winner === "Tie" ? "Tie" : "Needs review";
  const tone =
    winner === "A"
      ? "teal"
      : winner === "B"
        ? "blue"
        : winner === "Tie"
          ? "grey"
          : "red";

  return (
    <div className="rounded-card border border-line bg-white p-3 shadow-sm">
      <p className="text-[11px] font-medium uppercase tracking-wide text-ink/45">
        {CATEGORY_LABELS[result.category]}
      </p>
      <div className="mt-1.5 flex items-center gap-1.5">
        {winner === "Review" ? (
          <ShieldQuestion className="h-4 w-4 text-red" />
        ) : winner === "Tie" ? (
          <Minus className="h-4 w-4 text-ink/40" />
        ) : (
          <Crown
            className={cn("h-4 w-4", winner === "A" ? "text-teal" : "text-blue")}
          />
        )}
        <span
          className={cn(
            "truncate text-sm font-semibold",
            tone === "teal" && "text-teal",
            tone === "blue" && "text-blue",
            tone === "grey" && "text-ink/60",
            tone === "red" && "text-red",
          )}
        >
          {label}
        </span>
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] text-ink/50">
        <span className="stat-num">
          A {result.avgA != null ? pct(result.avgA) : "—"}
        </span>
        <span className="stat-num">
          B {result.avgB != null ? pct(result.avgB) : "—"}
        </span>
      </div>
    </div>
  );
}
