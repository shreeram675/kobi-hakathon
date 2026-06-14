"use client";

import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { cn } from "@/lib/format";

export interface DonutDatum {
  name: string;
  value: number;
  color: string;
}

/** Generic donut with a center label. Used for success/fail, source-type, etc. */
export function Donut({
  data,
  centerValue,
  centerLabel,
  size = 168,
  thickness = 22,
  className,
}: {
  data: DonutDatum[];
  centerValue?: string | number;
  centerLabel?: string;
  size?: number;
  thickness?: number;
  className?: string;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const inner = (size - thickness * 2) / 2;
  const outer = size / 2 - 2;

  return (
    <div className={cn("flex flex-wrap items-center gap-4", className)}>
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={total === 0 ? [{ name: "empty", value: 1, color: "#eef2f6" }] : data}
              dataKey="value"
              nameKey="name"
              innerRadius={inner}
              outerRadius={outer}
              paddingAngle={total > 0 ? 2 : 0}
              startAngle={90}
              endAngle={-270}
              stroke="none"
            >
              {(total === 0 ? [{ color: "#eef2f6" }] : data).map((d, i) => (
                <Cell key={i} fill={d.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="stat-num text-2xl font-semibold text-navy">
            {centerValue ?? total}
          </span>
          {centerLabel && (
            <span className="mt-0.5 text-[10px] uppercase tracking-wide text-ink/45">
              {centerLabel}
            </span>
          )}
        </div>
      </div>
      <ul className="min-w-[100px] flex-1 space-y-1.5">
        {data.map((d) => (
          <li key={d.name} className="flex items-center gap-2 text-xs">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ background: d.color }}
            />
            <span className="min-w-0 break-words text-ink/70">{d.name}</span>
            <span className="stat-num ml-auto shrink-0 pl-2 font-semibold text-ink tabular-nums">
              {d.value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
