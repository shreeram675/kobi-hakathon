"use client";

import { CheckCircle2, Database, RefreshCw, X, Circle, Clock } from "lucide-react";
import type { CompareCacheCheckItem } from "@/lib/types";
import { cn } from "@/lib/format";

export type CompareCacheDecision = "view" | "fresh" | "cancel";

interface Props {
  open: boolean;
  results: CompareCacheCheckItem[];
  onDecision: (choice: CompareCacheDecision) => void;
}

export function CompareCacheModal({ open, results, onDecision }: Props) {
  if (!open) return null;

  const cachedCount = results.filter((r) => r.found).length;
  const totalCount = results.length;
  const allCached = cachedCount === totalCount;
  const someCached = cachedCount > 0 && !allCached;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={() => onDecision("cancel")}
    >
      <div className="absolute inset-0 bg-navy/60 backdrop-blur-sm" />

      <div
        className="relative w-full max-w-lg rounded-[16px] border border-line bg-white shadow-[0_24px_60px_rgba(0,0,0,0.22)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-start justify-between gap-3 border-b border-line bg-soft-grey/40 px-5 py-4">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue/10">
              <Database className="h-4 w-4 text-blue" />
            </span>
            <div>
              <h2 className="text-[14px] font-semibold text-navy">
                {allCached
                  ? "Previous analyses found"
                  : `${cachedCount} of ${totalCount} programs have stored analyses`}
              </h2>
              <p className="mt-0.5 text-[11px] text-ink/45">Choose how to source data for this comparison</p>
            </div>
          </div>
          <button
            onClick={() => onDecision("cancel")}
            className="shrink-0 rounded-full p-1 text-ink/30 transition hover:bg-soft-grey hover:text-ink/60"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* program list */}
        <div className="divide-y divide-line/60 max-h-52 overflow-y-auto">
          {results.map((item, idx) => (
            <ProgramRow key={idx} item={item} />
          ))}
        </div>

        {/* choices */}
        <div className="flex flex-col gap-2 border-t border-line px-5 py-4">
          {allCached && (
            <ChoiceButton
              variant="primary"
              icon={<Database className="h-4 w-4" />}
              label="View Previous Analyses"
              description="Load all programs from stored results — instant, no cost"
              onClick={() => onDecision("view")}
            />
          )}
          {someCached && (
            <ChoiceButton
              variant="primary"
              icon={<Database className="h-4 w-4" />}
              label="Use Cached + Fetch Missing"
              description={`Load ${cachedCount} stored + run ${totalCount - cachedCount} fresh`}
              onClick={() => onDecision("view")}
            />
          )}
          <ChoiceButton
            variant="secondary"
            icon={<RefreshCw className="h-4 w-4" />}
            label="Run Again for All"
            description="Run the full pipeline for every program and update stored results"
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

function ProgramRow({ item }: { item: CompareCacheCheckItem }) {
  return (
    <div className="flex items-center gap-2.5 px-5 py-2.5">
      {item.found ? (
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-teal" />
      ) : (
        <Circle className="h-3.5 w-3.5 shrink-0 text-ink/25" />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-[12px] font-medium text-ink leading-tight">
          {item.program_name ?? item.program}
        </p>
        {item.found && item.run_date ? (
          <p className="mt-0.5 flex items-center gap-1 text-[10px] text-teal/70">
            <Clock className="h-2.5 w-2.5" />
            {item.run_date}
            {(item.age_days ?? 0) > 0 && (
              <span className="text-ink/35">({item.age_days}d ago)</span>
            )}
          </p>
        ) : (
          <p className="mt-0.5 text-[10px] text-ink/35">No stored data — will fetch fresh</p>
        )}
      </div>
      <span
        className={cn(
          "shrink-0 rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide",
          item.found ? "bg-teal/10 text-teal" : "bg-soft-grey text-ink/40",
        )}
      >
        {item.found ? "stored" : "fresh"}
      </span>
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
          ? "border-blue/30 bg-blue/8 hover:bg-blue/14 hover:border-blue/50"
          : "border-line bg-soft-grey/40 hover:bg-soft-grey hover:border-line",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
          variant === "primary" ? "bg-blue/15 text-blue" : "bg-white text-ink/50 border border-line",
        )}
      >
        {icon}
      </span>
      <div>
        <p className={cn("text-[13px] font-semibold leading-tight", variant === "primary" ? "text-blue" : "text-ink")}>
          {label}
        </p>
        <p className="mt-0.5 text-[11px] text-ink/45 leading-snug">{description}</p>
      </div>
    </button>
  );
}
