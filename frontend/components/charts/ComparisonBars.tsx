import { cn } from "@/lib/format";

interface BarRow {
  label: string;
  value: number;
  color?: string;
}

/** Simple labelled horizontal bars (e.g. raw vs unique retrieval counts). */
export function ComparisonBars({
  rows,
  className,
}: {
  rows: BarRow[];
  className?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className={cn("space-y-2.5", className)}>
      {rows.map((r) => (
        <div key={r.label}>
          <div className="mb-1 flex items-baseline justify-between">
            <span className="text-xs text-ink/60">{r.label}</span>
            <span className="stat-num text-sm font-semibold text-navy tabular-nums">
              {r.value}
            </span>
          </div>
          <div className="h-2.5 w-full overflow-hidden rounded-pill bg-soft-grey">
            <div
              className="h-full rounded-pill transition-[width] duration-700 ease-out"
              style={{
                width: `${(r.value / max) * 100}%`,
                background: r.color ?? "var(--teal)",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
