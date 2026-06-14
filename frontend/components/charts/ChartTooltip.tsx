"use client";

import type { TooltipProps } from "recharts";

/** Compact themed tooltip shared across the Recharts charts. */
export function ChartTooltip({
  active,
  payload,
  label,
  unit,
  labelKey,
}: TooltipProps<number, string> & { unit?: string; labelKey?: string }) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0];
  const heading =
    (labelKey && (row.payload as Record<string, unknown>)?.[labelKey]) ?? label;
  return (
    <div className="rounded-md border border-line bg-white px-2.5 py-1.5 text-xs shadow-panel">
      {heading != null && (
        <p className="mb-0.5 font-medium text-navy">{String(heading)}</p>
      )}
      {payload.map((p, i) => (
        <p key={i} className="flex items-center gap-1.5 text-ink/70">
          <span
            className="h-2 w-2 rounded-sm"
            style={{ background: (p.color as string) ?? p.fill }}
          />
          {p.name && <span>{p.name}:</span>}
          <span className="stat-num font-semibold text-ink tabular-nums">
            {p.value}
          </span>
          {unit && <span className="text-ink/45">{unit}</span>}
        </p>
      ))}
    </div>
  );
}
