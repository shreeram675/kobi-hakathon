import { type ReactNode } from "react";
import { cn } from "@/lib/format";
import type { Tone } from "@/components/ui/badge";

const GRADIENT: Record<Tone, string> = {
  green:  "from-[#e8f6ef] to-white border-[#16704a]/15",
  amber:  "from-[#fff8ec] to-white border-[#a66100]/15",
  red:    "from-[#fde8e8] to-white border-[#b83232]/15",
  grey:   "from-[#eef2f6] to-white border-line",
  blue:   "from-[#e6f0fb] to-white border-[#1f65b7]/15",
  teal:   "from-[#e2f3f3] to-white border-[#0f7c7d]/15",
  navy:   "from-[#eaf0f6] to-white border-[#17324d]/15",
};

const ACCENT_BAR: Record<Tone, string> = {
  green: "bg-green",
  amber: "bg-amber",
  red:   "bg-red",
  grey:  "bg-ink/25",
  blue:  "bg-blue",
  teal:  "bg-teal",
  navy:  "bg-navy",
};

const VALUE_COLOR: Record<Tone, string> = {
  green: "text-green",
  amber: "text-amber",
  red:   "text-red",
  grey:  "text-ink/60",
  blue:  "text-blue",
  teal:  "text-teal",
  navy:  "text-navy",
};

const ICON_BG: Record<Tone, string> = {
  green: "bg-green/10 text-green",
  amber: "bg-amber/10 text-amber",
  red:   "bg-red/10 text-red",
  grey:  "bg-ink/8 text-ink/50",
  blue:  "bg-blue/10 text-blue",
  teal:  "bg-teal/10 text-teal",
  navy:  "bg-navy/10 text-navy",
};

export interface MetricCardProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  className?: string;
}

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
        "relative overflow-hidden rounded-[10px] border bg-gradient-to-b p-3.5 shadow-sm analyst-card",
        GRADIENT[tone],
        className,
      )}
    >
      <span
        className={cn("absolute inset-y-0 left-0 w-[3px] rounded-r-full", ACCENT_BAR[tone])}
        aria-hidden
      />
      <div className="flex items-start justify-between gap-2">
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-ink/40 leading-tight">
          {label}
        </p>
        {icon && (
          <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[11px]", ICON_BG[tone])}>
            {icon}
          </span>
        )}
      </div>
      <p className={cn("stat-num mt-1.5 text-2xl font-bold leading-none tracking-tight", VALUE_COLOR[tone])}>
        {value}
      </p>
      {hint && (
        <p className="mt-1 text-[10.5px] text-ink/40 leading-snug">{hint}</p>
      )}
    </div>
  );
}
