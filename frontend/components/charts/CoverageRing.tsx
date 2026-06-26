"use client";

import { TOKENS } from "@/lib/colors";
import { cn } from "@/lib/format";
import type { SchemaCoverage } from "@/lib/types";

const BG = "#eef2f6";

function Ring({
  cx,
  cy,
  r,
  pct,
  color,
  strokeWidth,
}: {
  cx: number;
  cy: number;
  r: number;
  pct: number;
  color: string;
  strokeWidth: number;
}) {
  const circ = 2 * Math.PI * r;
  const filled = circ * Math.min(Math.max(pct / 100, 0), 1);
  return (
    <g>
      {/* track */}
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={BG} strokeWidth={strokeWidth} />
      {/* filled arc */}
      {filled > 0 && (
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={`${filled} ${circ - filled}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cy})`}
        />
      )}
    </g>
  );
}

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
    { key: "Supported",     value: coverage.supported_fields,     color: TOKENS.green },
    { key: "Manual review", value: coverage.manual_review_fields, color: TOKENS.red   },
    { key: "Rejected",      value: coverage.rejected_fields,      color: TOKENS.amber },
    { key: "Null / N/A",   value: coverage.null_fields,          color: TOKENS.grey  },
  ];

  const cx = size / 2;
  const cy = size / 2;
  const sw = Math.round(size * 0.047);   // stroke width ≈ 9px at 200
  const gap = Math.round(size * 0.022);  // gap between rings ≈ 4px at 200
  // outermost ring radius — leaves a small margin from the SVG edge
  const r0 = cx - sw / 2 - Math.round(size * 0.025);

  return (
    <div className={cn("flex items-center gap-6", className)}>
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          {rows.map((row, i) => (
            <Ring
              key={row.key}
              cx={cx}
              cy={cy}
              r={r0 - i * (sw + gap)}
              pct={(row.value / total) * 100}
              color={row.color}
              strokeWidth={sw}
            />
          ))}
        </svg>

        {/* Center text — absolutely positioned, never touches the SVG rings */}
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <div className="flex items-baseline leading-none">
            <span className="text-[1.75rem] font-bold tabular-nums" style={{ color: "#1b2a4a" }}>
              {coverage.supported_fields}
            </span>
            <span className="ml-0.5 text-[0.75rem] font-medium" style={{ color: "#9aa5b4" }}>
              /{coverage.total_fields}
            </span>
          </div>
          <span
            className="mt-1 text-[0.55rem] font-semibold uppercase tracking-[0.12em]"
            style={{ color: "#9aa5b4" }}
          >
            Fields covered
          </span>
        </div>
      </div>

      {/* Legend */}
      <ul className="min-w-0 space-y-2">
        {rows.map((r) => (
          <li key={r.key} className="flex items-center gap-2 text-xs">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: r.color }}
            />
            <span className="truncate text-ink/60">{r.key}</span>
            <span className="stat-num ml-auto pl-3 font-semibold tabular-nums text-ink">
              {r.value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
