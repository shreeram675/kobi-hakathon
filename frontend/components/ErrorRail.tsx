"use client";

import { ChevronDown, OctagonAlert } from "lucide-react";
import { useState } from "react";
import { cn, relativeTime } from "@/lib/format";
import type { PipelineError } from "@/lib/types";

/** Collapsible list of PipelineError items. */
export function ErrorRail({
  errors,
  className,
}: {
  errors: PipelineError[];
  className?: string;
}) {
  const [open, setOpen] = useState(true);
  if (!errors.length) return null;
  return (
    <div
      className={cn(
        "overflow-hidden rounded-card border border-red/30 bg-soft-red/40",
        className,
      )}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <OctagonAlert className="h-4 w-4 text-red" />
        <span className="text-xs font-semibold text-red">
          {errors.length} pipeline error{errors.length === 1 ? "" : "s"}
        </span>
        <ChevronDown
          className={cn(
            "ml-auto h-4 w-4 text-red/60 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <ul className="divide-y divide-red/15 border-t border-red/20">
          {errors.map((e, i) => (
            <li key={i} className="px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-[10px] text-red">
                  {e.stage}
                </span>
                <span className="text-[10px] text-ink/40">
                  {relativeTime(e.created_at)}
                </span>
              </div>
              <p className="mt-1 break-words text-xs text-ink/70">{e.message}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
