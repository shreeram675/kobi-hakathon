"use client";

import {
  CheckCircle2,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { cn, renderValue } from "@/lib/format";
import {
  CATEGORY_ORDER,
  CATEGORY_LABELS,
  FOCUSED_SCHEMA_FIELD_PATHS,
  fieldLabel,
  type Category,
} from "@/lib/schema";
import type { FieldReport, FieldReportEntry } from "@/lib/types";
import { SourcePillRow } from "@/components/SourcePill";

interface Props {
  programName: string | null;
  fieldReport?: FieldReport | null;
}

export function SingleProgramBriefPanel({ programName, fieldReport }: Props) {
  const entries: FieldReportEntry[] = fieldReport?.entries ?? [];

  // Per-category coverage stats (focused schema fields only)
  const categoryStats = CATEGORY_ORDER.map((cat) => {
    const focused = entries.filter(
      (e) => e.field_path.startsWith(cat + ".") && FOCUSED_SCHEMA_FIELD_PATHS.has(e.field_path),
    );
    const extracted = focused.filter((e) => e.status === "extracted").length;
    const total = focused.length;
    const pct = total > 0 ? Math.round((extracted / total) * 100) : 0;
    return { cat, label: CATEGORY_LABELS[cat as Category], extracted, total, pct };
  }).filter((s) => s.total > 0);

  // High-confidence extracted fields for strengths
  const strengths = entries
    .filter(
      (e) =>
        e.status === "extracted" &&
        FOCUSED_SCHEMA_FIELD_PATHS.has(e.field_path) &&
        (e.confidence ?? 0) >= 0.80 &&
        e.value != null,
    )
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    .slice(0, 6);

  // Fields not found
  const gaps = entries
    .filter((e) => e.status === "not_found" && FOCUSED_SCHEMA_FIELD_PATHS.has(e.field_path))
    .slice(0, 5);

  // Key facts table — top extracted fields sorted by confidence
  const keyFacts = entries
    .filter(
      (e) =>
        e.status === "extracted" &&
        FOCUSED_SCHEMA_FIELD_PATHS.has(e.field_path) &&
        e.value != null,
    )
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    .slice(0, 10);

  return (
    <div className="space-y-4">
      {/* ── Category coverage grid ───────────────────────────────────────────── */}
      {categoryStats.length > 0 && (
        <div>
          <h2 className="mb-3 text-base font-semibold text-navy">Coverage by category</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {categoryStats.map(({ cat, label, extracted, total, pct }) => (
              <div key={cat} className="rounded-card border border-line bg-white p-3 shadow-sm">
                <p className="text-[10px] font-medium uppercase tracking-wide text-ink/45 truncate">
                  {label}
                </p>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-soft-grey">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all duration-500",
                      pct >= 80 ? "bg-green" : pct >= 50 ? "bg-teal" : "bg-amber",
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <div className="mt-1.5 flex items-center justify-between">
                  <span className="text-[11px] text-ink/50 tabular-nums">
                    {extracted}/{total}
                  </span>
                  <span
                    className={cn(
                      "text-[11px] font-semibold tabular-nums",
                      pct >= 80 ? "text-green" : pct >= 50 ? "text-teal" : "text-amber",
                    )}
                  >
                    {pct}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Strengths & Gaps ────────────────────────────────────────────────── */}
      {(strengths.length > 0 || gaps.length > 0) && (
        <div>
          <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-navy">
            <ShieldCheck className="h-4 w-4 text-teal" />
            Extracted intelligence
          </h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {strengths.length > 0 && (
              <div className="rounded-card border border-line bg-white p-4 shadow-sm">
                <p className="mb-2 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-green">
                  <CheckCircle2 className="h-3 w-3" /> High-confidence findings
                </p>
                <ul className="space-y-1.5">
                  {strengths.map((e, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-1.5 text-[11px] text-ink/75 leading-snug"
                    >
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-green/60" />
                      <span>
                        <span className="font-medium text-navy">{fieldLabel(e.field_path)}:</span>{" "}
                        {String(renderValue(e.value) ?? "").slice(0, 90)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {gaps.length > 0 && (
              <div className="rounded-card border border-line bg-white p-4 shadow-sm">
                <p className="mb-2 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-amber">
                  <ShieldAlert className="h-3 w-3" /> Data not found
                </p>
                <ul className="space-y-1.5">
                  {gaps.map((e, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-1.5 text-[11px] text-ink/75 leading-snug"
                    >
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber/60" />
                      {fieldLabel(e.field_path)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Key facts table ──────────────────────────────────────────────────── */}
      {keyFacts.length > 0 && (
        <div>
          <h2 className="mb-3 text-base font-semibold text-navy">Key extracted facts</h2>
          <div className="overflow-hidden rounded-card border border-line bg-white shadow-sm">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-line bg-navy text-white/80">
                  <th className="px-4 py-2.5 text-left font-semibold uppercase tracking-wide text-[10px]">
                    Field
                  </th>
                  <th className="px-4 py-2.5 text-left font-semibold uppercase tracking-wide text-[10px]">
                    Value
                  </th>
                  <th className="px-3 py-2.5 text-right font-semibold uppercase tracking-wide text-[10px]">
                    Conf
                  </th>
                  <th className="px-3 py-2.5 text-left font-semibold uppercase tracking-wide text-[10px]">
                    Sources
                  </th>
                </tr>
              </thead>
              <tbody>
                {keyFacts.map((e, i) => (
                  <tr
                    key={e.field_path}
                    className={cn(
                      "border-b border-line/50 transition-colors hover:bg-soft-grey/20",
                      i % 2 === 1 && "bg-soft-grey/10",
                    )}
                  >
                    <td className="px-4 py-2.5">
                      <p className="font-medium text-navy leading-snug">
                        {fieldLabel(e.field_path)}
                      </p>
                      <p className="text-[9px] text-ink/35 uppercase tracking-wide">
                        {e.field_path.split(".")[0].replace(/_/g, " ")}
                      </p>
                    </td>
                    <td className="px-4 py-2.5 text-ink/75 leading-snug max-w-[260px]">
                      <span className="line-clamp-2">
                        {String(renderValue(e.value) ?? "—")}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      <span
                        className={cn(
                          "font-semibold",
                          (e.confidence ?? 0) >= 0.80
                            ? "text-green"
                            : (e.confidence ?? 0) >= 0.60
                              ? "text-teal"
                              : "text-amber",
                        )}
                      >
                        {Math.round((e.confidence ?? 0) * 100)}%
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-col gap-1">
                        <SourcePillRow urls={e.source_urls ?? []} />
                        {e.corroboration_count > 1 && (
                          <span className="text-[9px] text-ink/35 tabular-nums">
                            {e.corroboration_count}× corroborated
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
