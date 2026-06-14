import { type ReactNode } from "react";
import { cn } from "@/lib/format";
import type { Tone } from "@/components/ui/badge";

const ACCENT_BAR: Record<Tone, string> = {
  green: "bg-green",
  amber: "bg-amber",
  red: "bg-red",
  grey: "bg-ink/30",
  blue: "bg-blue",
  teal: "bg-teal",
  navy: "bg-navy",
};

const ACCENT_TEXT: Record<Tone, string> = {
  green: "text-green",
  amber: "text-amber",
  red: "text-red",
  grey: "text-ink",
  blue: "text-blue",
  teal: "text-teal",
  navy: "text-navy",
};

export interface MetricCardProps {
  label: string;
  value: ReactNode;
  /** small context line under the value, e.g. units */
  hint?: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  className?: string;
}

/** Count + label + optional colour. */
export function MetricCard({
  label,
  value,
  hint,
  tone = "navy",
  icon,
  className,
}: MetricCardProps) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-card border border-line bg-white p-3.5 shadow-sm",
        className,
      )}
    >
      <span
        className={cn("absolute inset-y-0 left-0 w-1", ACCENT_BAR[tone])}
        aria-hidden
      />
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink/45">
          {label}
        </p>
        {icon && <span className={ACCENT_TEXT[tone]}>{icon}</span>}
      </div>
      <p
        className={cn(
          "stat-num mt-1 text-2xl font-semibold leading-none",
          ACCENT_TEXT[tone],
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-[11px] text-ink/45">{hint}</p>}
    </div>
  );
}
