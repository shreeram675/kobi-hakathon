"use client";

import {
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
} from "recharts";
import { TOKENS } from "@/lib/colors";
import { cn } from "@/lib/format";
import type { SchemaCoverage } from "@/lib/types";

/** RadialBarChart for the 5 coverage buckets (supported/manual/null/rejected vs total). */
export function CoverageRing({
  coverage,
  size = 200,
  className,
}: {
  coverage: SchemaCoverage;
  size?: number;
  className?: string;
}) {
  const total = coverage.total_fields || 1;
  const rows = [
    { key: "Supported", value: coverage.supported_fields, fill: TOKENS.green },
    { key: "Manual review", value: coverage.manual_review_fields, fill: TOKENS.red },
    { key: "Rejected", value: coverage.rejected_fields, fill: TOKENS.amber },
    { key: "Null / N/A", value: coverage.null_fields, fill: TOKENS.grey },
  ];
  // recharts stacks rings outer->inner in array order; show as % of total
  const data = rows.map((r) => ({ ...r, pct: (r.value / total) * 100 }));

  return (
    <div className={cn("flex items-center gap-4", className)}>
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            innerRadius="38%"
            outerRadius="100%"
            data={data}
            startAngle={90}
            endAngle={-270}
            barSize={11}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar
              dataKey="pct"
              background={{ fill: "#eef2f6" }}
              cornerRadius={6}
            />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="stat-num text-2xl font-semibold text-navy">
            {coverage.supported_fields}
            <span className="text-sm font-medium text-ink/40">/{coverage.total_fields}</span>
          </span>
          <span className="mt-0.5 text-[10px] uppercase tracking-wide text-ink/45">
            Fields covered
          </span>
        </div>
      </div>
      <ul className="min-w-0 space-y-1.5">
        {data.map((r) => (
          <li key={r.key} className="flex items-center gap-2 text-xs">
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: r.fill }} />
            <span className="truncate text-ink/70">{r.key}</span>
            <span className="stat-num ml-auto pl-2 font-semibold text-ink tabular-nums">
              {r.value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
