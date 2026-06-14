"use client";

import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { confidenceHex } from "@/lib/colors";
import { cn } from "@/lib/format";

/** Large % gauge (half-donut). 0..1 input. */
export function DataQualityGauge({
  value,
  label = "Data quality",
  size = 200,
  className,
}: {
  value: number;
  label?: string;
  size?: number;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(1, value || 0));
  const data = [
    { name: "filled", value: clamped },
    { name: "rest", value: 1 - clamped },
  ];
  const color = confidenceHex(clamped);

  return (
    <div className={cn("flex flex-col items-center", className)} style={{ width: size }}>
      {/* arc only — no text inside the SVG area */}
      <div style={{ width: size, height: Math.round(size * 0.52) }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              startAngle={180}
              endAngle={0}
              innerRadius="68%"
              outerRadius="100%"
              cy="100%"
              stroke="none"
              cornerRadius={4}
            >
              <Cell fill={color} />
              <Cell fill="#eef2f6" />
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      {/* text sits below the arc, never overlapping */}
      <div className="mt-1 flex flex-col items-center">
        <span
          className="stat-num text-3xl font-semibold leading-none"
          style={{ color }}
        >
          {Math.round(clamped * 100)}%
        </span>
        <span className="mt-1 text-[11px] uppercase tracking-wide text-ink/45">
          {label}
        </span>
      </div>
    </div>
  );
}
