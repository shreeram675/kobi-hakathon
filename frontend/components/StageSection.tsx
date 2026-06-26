"use client";

import { Check, Loader2, Clock } from "lucide-react";
import { type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { stageMeta } from "@/lib/schema";
import { cn } from "@/lib/format";
import type { StageStatus } from "@/lib/types";

export function StageSection({
  stageId,
  status,
  children,
  aside,
}: {
  stageId: string;
  status: StageStatus;
  children: ReactNode;
  aside?: ReactNode;
}) {
  const meta = stageMeta(stageId);

  const headerBg = {
    done:    "bg-soft-green border-green/15",
    running: "bg-[#e2f3f3] border-teal/20",
    error:   "bg-soft-red border-red/20",
    idle:    "bg-soft-grey border-line",
  }[status];

  const numBg = {
    done:    "bg-green text-white",
    running: "bg-teal text-white",
    error:   "bg-red text-white",
    idle:    "bg-line text-ink/40",
  }[status];

  return (
    <section id={`stage-${stageId}`} className="scroll-mt-6">
      {/* ── Stage header ── */}
      <div
        className={cn(
          "flex items-center gap-3 rounded-t-[10px] border-x border-t px-4 py-2.5",
          headerBg,
        )}
      >
        {/* numbered badge */}
        <span
          className={cn(
            "grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold",
            numBg,
          )}
        >
          {status === "done" ? (
            <Check className="h-3.5 w-3.5" strokeWidth={2.5} />
          ) : status === "running" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            meta?.index
          )}
        </span>

        {/* label */}
        <h2 className="flex-1 text-[13px] font-semibold tracking-tight text-navy">
          {meta?.label}
        </h2>

        {/* status pill */}
        <StageStatusPill status={status} />

        {aside && <div className="ml-1">{aside}</div>}
      </div>

      {/* ── Stage body ── */}
      <div
        className={cn(
          "rounded-b-[10px] border border-t-0 bg-white px-4 py-4 shadow-sm",
          status === "error" ? "border-red/20" : "border-line",
        )}
      >
        {status === "idle" ? (
          <PendingPlaceholder />
        ) : status === "running" ? (
          <RunningPlaceholder />
        ) : (
          children
        )}
      </div>
    </section>
  );
}

function StageStatusPill({ status }: { status: StageStatus }) {
  if (status === "done") return <Badge tone="green">Done</Badge>;
  if (status === "running") return <Badge tone="teal" dot>Running</Badge>;
  if (status === "error") return <Badge tone="red">Error</Badge>;
  return (
    <span className="inline-flex items-center gap-1 rounded-pill bg-soft-grey px-2 py-0.5 text-[10px] font-medium text-ink/40">
      <Clock className="h-3 w-3" /> Pending
    </span>
  );
}

function PendingPlaceholder() {
  return (
    <div className="flex items-center gap-2 py-4 text-center text-xs text-ink/35 justify-center">
      <Clock className="h-3.5 w-3.5 text-ink/25" />
      Waiting for upstream stages…
    </div>
  );
}

function RunningPlaceholder() {
  return (
    <div className="space-y-3 py-1">
      <Skeleton className="h-3.5 w-2/5" />
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[62px]" />
        ))}
      </div>
      <Skeleton className="h-20 w-full" />
    </div>
  );
}
