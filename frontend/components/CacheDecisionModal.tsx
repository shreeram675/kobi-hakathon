"use client";

import { Database, RefreshCw, X, Clock } from "lucide-react";
import type { CacheCheckResult } from "@/lib/types";
import { cn } from "@/lib/format";

export type CacheDecision = "view" | "fresh" | "cancel";

interface Props {
  open: boolean;
  programQuery: string;
  result: CacheCheckResult;
  onDecision: (choice: CacheDecision) => void;
}

export function CacheDecisionModal({ open, programQuery, result, onDecision }: Props) {
  if (!open) return null;

  const ageDays = result.age_days ?? 0;
  const ageLabel =
    ageDays === 0 ? "today" : ageDays === 1 ? "yesterday" : `${ageDays} days ago`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={() => onDecision("cancel")}
    >
      <div className="absolute inset-0 bg-navy/60 backdrop-blur-sm" />

      <div
        className="relative w-full max-w-md rounded-[16px] border border-line bg-white shadow-[0_24px_60px_rgba(0,0,0,0.22)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-start justify-between gap-3 border-b border-line bg-soft-grey/40 px-5 py-4">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-teal/10">
              <Database className="h-4 w-4 text-teal" />
            </span>
            <div>
              <h2 className="text-[14px] font-semibold text-navy">Previous analysis found</h2>
              <p className="mt-0.5 text-[11px] text-ink/45">
                {result.program_name ?? programQuery}
                {result.brand && result.brand !== result.program_name && (
                  <span className="text-ink/30"> · {result.brand}</span>
                )}
              </p>
            </div>
          </div>
          <button
            onClick={() => onDecision("cancel")}
            className="shrink-0 rounded-full p-1 text-ink/30 transition hover:bg-soft-grey hover:text-ink/60"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* timestamp row */}
        <div className="flex items-center gap-2 border-b border-line/60 px-5 py-3 bg-teal/[0.03]">
          <Clock className="h-3.5 w-3.5 shrink-0 text-teal/60" />
          <p className="text-[12px] text-ink/60">
            Last analysed{" "}
            <span className="font-semibold text-ink/80">{ageLabel}</span>
            {result.run_datetime && (
              <span className="text-ink/40"> · {result.run_datetime}</span>
            )}
          </p>
        </div>

        {/* choices */}
        <div className="flex flex-col gap-2 px-5 py-4">
          <ChoiceButton
            variant="primary"
            icon={<Database className="h-4 w-4" />}
            label="View Previous Analysis"
            description="Load the stored result instantly — no cost, no wait"
            onClick={() => onDecision("view")}
          />
          <ChoiceButton
            variant="secondary"
            icon={<RefreshCw className="h-4 w-4" />}
            label="Run Again"
            description="Run a fresh pipeline and overwrite the stored result"
            onClick={() => onDecision("fresh")}
          />
          <button
            onClick={() => onDecision("cancel")}
            className="mt-1 py-1 text-center text-[12px] text-ink/35 hover:text-ink/55 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function ChoiceButton({
  variant,
  icon,
  label,
  description,
  onClick,
}: {
  variant: "primary" | "secondary";
  icon: React.ReactNode;
  label: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3 text-left transition-all",
        variant === "primary"
          ? "border-teal/30 bg-teal/8 hover:bg-teal/14 hover:border-teal/50"
          : "border-line bg-soft-grey/40 hover:bg-soft-grey hover:border-line",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
          variant === "primary" ? "bg-teal/15 text-teal" : "bg-white text-ink/50 border border-line",
        )}
      >
        {icon}
      </span>
      <div>
        <p className={cn("text-[13px] font-semibold leading-tight", variant === "primary" ? "text-teal" : "text-ink")}>
          {label}
        </p>
        <p className="mt-0.5 text-[11px] text-ink/45 leading-snug">{description}</p>
      </div>
    </button>
  );
}
