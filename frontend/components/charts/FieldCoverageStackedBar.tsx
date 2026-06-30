"use client";

import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { FIELD_REPORT_ACCENT } from "@/lib/colors";
import type { FieldReport } from "@/lib/types";
import { ChartTooltip } from "./ChartTooltip";

/** Horizontal stacked bar: extracted / ambiguous / not_found / flagged. */
export function FieldCoverageStackedBar({
  report,
  height = 84,
}: {
  report: FieldReport;
  height?: number;
}) {
  const data = [
    {
      name: "Fields",
      extracted: report.extracted_count,
      ambiguous: report.ambiguous_count,
      not_found: report.not_found_count,
      flagged: report.flagged_count,
    },
  ];

  const series: { key: keyof (typeof data)[0]; label: string; color: string }[] = [
    { key: "extracted", label: "Extracted", color: FIELD_REPORT_ACCENT.extracted.hex },
    { key: "ambiguous", label: "Unclear", color: FIELD_REPORT_ACCENT.ambiguous.hex },
    { key: "not_found", label: "Not found", color: FIELD_REPORT_ACCENT.not_found.hex },
    { key: "flagged", label: "Needs review", color: FIELD_REPORT_ACCENT.flagged.hex },
  ];

  return (
    <div>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            layout="vertical"
            data={data}
            margin={{ top: 0, right: 8, left: 8, bottom: 0 }}
            barSize={26}
          >
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="name" hide />
            <Tooltip cursor={{ fill: "transparent" }} content={<ChartTooltip />} />
            {series.map((s, i) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.label}
                stackId="a"
                fill={s.color}
                radius={
                  i === 0
                    ? [6, 0, 0, 6]
                    : i === series.length - 1
                      ? [0, 6, 6, 0]
                      : 0
                }
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {series.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5 text-xs text-ink/70">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            {s.label}
            <span className="stat-num font-semibold text-ink tabular-nums">
              {data[0][s.key] as number}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
