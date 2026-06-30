"use client";

import { CheckCircle2, AlertCircle, Loader2, Clock } from "lucide-react";
import { cn } from "@/lib/format";
import type { ComparisonRunInfo, ProgramStatus, StageStatus } from "@/lib/types";
import { PIPELINE_STAGES } from "@/lib/schema";

interface ProgramQueuePanelProps {
  info: ComparisonRunInfo;
  /** Current stage_status from the polled run (for the in-progress program). */
  currentStageStatus: Record<string, StageStatus>;
  overallStatus: "running" | "done" | "error" | "clarification_needed" | "cache_hit_pending" | "cancelled";
  selectedIdx?: number;
  onSelect?: (idx: number) => void;
}

const STATUS_CONFIG: Record<
  ProgramStatus,
  { dot: string; badge: string; icon: React.ReactNode; label: string }
> = {
  pending: {
    dot: "bg-ink/20",
    badge: "bg-soft-grey text-ink/45 border-line",
    icon: <Clock className="h-3.5 w-3.5" />,
    label: "Pending",
  },
  running: {
    dot: "bg-teal animate-pulse",
    badge: "bg-[#e2f3f3] text-teal border-teal/25",
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    label: "Running",
  },
  done: {
    dot: "bg-green",
    badge: "bg-soft-green text-green border-green/25",
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    label: "Complete",
  },
  error: {
    dot: "bg-red",
    badge: "bg-soft-red text-red border-red/25",
    icon: <AlertCircle className="h-3.5 w-3.5" />,
    label: "Error",
  },
};


function MiniStageBar({
  stageStatus,
}: {
  stageStatus: Record<string, StageStatus>;
}) {
  return (
    <div className="flex gap-[3px] mt-1.5">
      {PIPELINE_STAGES.map((s) => {
        const st = stageStatus[s.id] ?? "idle";
        return (
          <div
            key={s.id}
            title={s.label}
            className={cn(
              "h-1 flex-1 rounded-full transition-all duration-500",
              st === "done" && "bg-green",
              st === "running" && "bg-teal animate-pulse",
              st === "error" && "bg-red",
              st === "idle" && "bg-ink/10",
            )}
          />
        );
      })}
    </div>
  );
}

export function ProgramQueuePanel({
  info,
  currentStageStatus,
  overallStatus,
  selectedIdx,
  onSelect,
}: ProgramQueuePanelProps) {
  const { programs, current_program_index, total_programs, program_statuses, program_stage_statuses } =
    info;

  const doneCount = program_statuses.filter((s) => s === "done").length;
  const overallPct = Math.round((doneCount / total_programs) * 100);

  return (
    <div className="rounded-[12px] border border-line bg-white shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-line px-4 py-3 bg-soft-grey/30">
        <div className="flex-1 min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/50">
            Comparison Queue
          </p>
          <p className="text-[12px] font-medium text-navy mt-0.5">
            {overallStatus === "done"
              ? `All ${total_programs} programs complete`
              : overallStatus === "error"
                ? "Pipeline encountered errors"
                : `Program ${current_program_index + 1} of ${total_programs}`}
          </p>
        </div>

        {/* Overall progress ring */}
        <div className="relative shrink-0 h-10 w-10">
          <svg className="h-10 w-10 -rotate-90" viewBox="0 0 36 36">
            <circle
              cx="18" cy="18" r="15"
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
              className="text-ink/10"
            />
            <circle
              cx="18" cy="18" r="15"
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
              strokeDasharray={`${overallPct * 0.942} 94.2`}
              strokeLinecap="round"
              className={cn(
                "transition-all duration-700",
                overallStatus === "done" ? "text-green" :
                overallStatus === "error" ? "text-red" : "text-teal",
              )}
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-[9px] font-bold text-ink/60 tabular-nums">
            {overallPct}%
          </span>
        </div>
      </div>

      {/* Program list */}
      <div className="divide-y divide-line/50">
        {programs.map((prog, idx) => {
          const status: ProgramStatus = (program_statuses[idx] as ProgramStatus) ?? "pending";
          const cfg = STATUS_CONFIG[status];
          const isActive = status === "running";
          const stageStatusForProg =
            isActive ? currentStageStatus : (program_stage_statuses[idx] ?? {});
          const doneStages = Object.values(stageStatusForProg).filter((s) => s === "done").length;
          const activeStageLabel = PIPELINE_STAGES.find(
            (s) => stageStatusForProg[s.id] === "running"
          )?.short;

          const isSelected = selectedIdx === idx;
          const isClickable = onSelect && (status === "done" || isActive);

          return (
            <div
              key={idx}
              role={isClickable ? "button" : undefined}
              tabIndex={isClickable ? 0 : undefined}
              onClick={isClickable ? () => onSelect(idx) : undefined}
              onKeyDown={isClickable ? (e) => { if (e.key === "Enter" || e.key === " ") onSelect(idx); } : undefined}
              className={cn(
                "px-4 py-3 transition-colors duration-300",
                isActive && !isSelected && "bg-[#f0fafa]/60",
                isSelected && "bg-teal/5 border-l-2 border-l-teal",
                isClickable && !isSelected && "cursor-pointer hover:bg-soft-grey/40",
                isClickable && "select-none",
              )}
            >
              <div className="flex items-start gap-3">
                {/* Letter badge */}
                <span
                  className={cn(
                    "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold",
                    isSelected
                      ? "bg-teal/20 border-teal/40 text-teal"
                      : isActive
                        ? "bg-teal/15 border-teal/25 text-teal"
                        : status === "done"
                          ? "bg-green/15 border-green/25 text-green"
                          : "bg-ink/6 border-ink/15 text-ink/35",
                  )}
                >
                  {String.fromCharCode(65 + idx)}
                </span>

                <div className="flex-1 min-w-0">
                  {/* Program name */}
                  <p
                    className={cn(
                      "text-[13px] font-semibold leading-tight truncate",
                      isActive ? "text-navy" : status === "pending" ? "text-ink/40" : "text-navy",
                    )}
                  >
                    {prog}
                  </p>

                  {/* Status / sub-label */}
                  <div className="flex items-center gap-2 mt-1">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
                        cfg.badge,
                      )}
                    >
                      {cfg.icon}
                      {isActive && activeStageLabel ? activeStageLabel : cfg.label}
                    </span>
                    {(isActive || status === "done") && (
                      <span className="text-[10px] text-ink/40 tabular-nums">
                        {doneStages}/{PIPELINE_STAGES.length} stages
                      </span>
                    )}
                  </div>

                  {/* Mini stage progress bar */}
                  {(isActive || status === "done" || status === "error") && (
                    <MiniStageBar stageStatus={stageStatusForProg} />
                  )}
                </div>

                {/* Right status dot */}
                <span
                  className={cn(
                    "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                    cfg.dot,
                  )}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Bottom overall progress bar */}
      <div className="h-1 bg-soft-grey/50">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-700",
            overallStatus === "done" ? "bg-green" :
            overallStatus === "error" ? "bg-red" : "bg-teal",
          )}
          style={{ width: `${overallPct}%` }}
        />
      </div>
    </div>
  );
}
