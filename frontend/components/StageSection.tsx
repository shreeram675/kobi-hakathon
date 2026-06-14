"use client";

import { Check, Loader2 } from "lucide-react";
import { type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { stageMeta } from "@/lib/schema";
import { cn } from "@/lib/format";
import type { StageStatus } from "@/lib/types";

/** Anchored section wrapper for one pipeline stage in the right detail panel. */
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
  return (
    <section id={`stage-${stageId}`} className="scroll-mt-4">
      <div className="mb-3 flex items-center gap-2.5">
        <span
          className={cn(
            "grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-semibold",
            status === "done" && "bg-soft-green text-green",
            status === "running" && "bg-[#e2f3f3] text-teal",
            status === "error" && "bg-soft-red text-red",
            status === "idle" && "bg-soft-grey text-ink/40",
          )}
        >
          {status === "done" ? (
            <Check className="h-4 w-4" />
          ) : status === "running" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            meta?.index
          )}
        </span>
        <h2 className="text-base font-semibold text-navy">{meta?.label}</h2>
        <StageStatusPill status={status} />
        {aside && <div className="ml-auto">{aside}</div>}
      </div>
      <div className="rounded-card border border-line bg-white p-4 shadow-panel">
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
  const map = {
    done: { tone: "green" as const, label: "Done" },
    running: { tone: "teal" as const, label: "Running" },
    error: { tone: "red" as const, label: "Error" },
    idle: { tone: "grey" as const, label: "Pending" },
  };
  const m = map[status];
  return (
    <Badge tone={m.tone} dot={status === "running"}>
      {m.label}
    </Badge>
  );
}

function PendingPlaceholder() {
  return (
    <p className="py-6 text-center text-sm text-ink/35">
      Waiting for upstream stages…
    </p>
  );
}

function RunningPlaceholder() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-4 w-2/3" />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-16" />
        ))}
      </div>
      <Skeleton className="h-24 w-full" />
    </div>
  );
}
