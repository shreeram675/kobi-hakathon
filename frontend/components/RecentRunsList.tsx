"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  History,
  Sparkles,
  GitCompareArrows,
  MessagesSquare,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { Badge, type Tone } from "@/components/ui/badge";
import { useRuns } from "@/lib/hooks";
import { confidenceTone } from "@/lib/colors";
import { pct, relativeTime, truncate } from "@/lib/format";
import type { RunMode } from "@/lib/types";

const MODE_TONE: Record<RunMode, Tone> = {
  single: "teal",
  compare: "blue",
  converse: "navy",
};

const MODE_ICON: Record<RunMode, typeof Sparkles> = {
  single: Sparkles,
  compare: GitCompareArrows,
  converse: MessagesSquare,
};

export function RecentRunsList() {
  const { data: runs, isLoading } = useRuns();

  return (
    <div className="overflow-hidden rounded-[12px] border border-line bg-white shadow-panel">
      {/* header */}
      <div className="flex items-center gap-2.5 border-b border-line bg-soft-grey/40 px-4 py-3">
        <History className="h-4 w-4 text-teal/70" />
        <h3 className="text-[13px] font-semibold text-navy">Recent analyses</h3>
        {runs && runs.length > 0 && (
          <span className="ml-1 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-soft-grey px-1.5 text-[10px] font-semibold text-ink/50">
            {runs.length}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-ink/35">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      ) : !runs || runs.length === 0 ? (
        <div className="py-14 text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-soft-grey">
            <Sparkles className="h-5 w-5 text-ink/25" />
          </div>
          <p className="text-sm font-medium text-ink/40">No analyses yet</p>
          <p className="mt-1 text-xs text-ink/30">Start one above to get intelligence on any loyalty program.</p>
        </div>
      ) : (
        <div className="divide-y divide-line">
          {/* column headers */}
          <div className="hidden grid-cols-[1fr_auto_auto_auto] items-center gap-4 px-4 py-2 text-[10px] font-semibold uppercase tracking-wide text-ink/35 sm:grid">
            <span>Program / Input</span>
            <span>Mode</span>
            <span>Quality</span>
            <span />
          </div>
          <ul className="divide-y divide-line">
            {runs.map((run) => {
              const Icon = MODE_ICON[run.mode];
              return (
                <li key={run.run_id}>
                  <Link
                    href={`/run/${run.run_id}`}
                    className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-soft-grey/35"
                  >
                    {/* mode icon bubble */}
                    <span
                      className={`hidden sm:flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                        run.mode === "compare"
                          ? "bg-blue/10 text-blue"
                          : run.mode === "converse"
                          ? "bg-navy/10 text-navy"
                          : "bg-teal/10 text-teal"
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                    </span>

                    {/* program name + meta */}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium text-ink leading-tight">
                        {truncate(run.user_input, 68)}
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] text-ink/35">
                        {run.run_id.replace(/^run_/, "").slice(0, 10)} ·{" "}
                        {relativeTime(run.created_at)}
                      </p>
                    </div>

                    {/* mode badge */}
                    <Badge tone={MODE_TONE[run.mode]} className="hidden shrink-0 capitalize sm:inline-flex text-[10px]">
                      {run.mode}
                    </Badge>

                    {/* quality / status */}
                    {run.status === "done" ? (
                      <span
                        className={`hidden sm:inline-flex items-center gap-1 shrink-0 rounded-pill px-2.5 py-1 text-[11px] font-semibold ${
                          run.data_quality >= 0.7
                            ? "bg-soft-green text-green"
                            : run.data_quality >= 0.4
                            ? "bg-soft-amber text-amber"
                            : "bg-soft-red text-red"
                        }`}
                      >
                        <CheckCircle2 className="h-3 w-3" />
                        {pct(run.data_quality)}
                      </span>
                    ) : (
                      <Badge tone="amber" dot className="hidden shrink-0 sm:inline-flex text-[10px]">
                        running
                      </Badge>
                    )}

                    <ArrowUpRight className="h-4 w-4 shrink-0 text-ink/25 transition-colors group-hover:text-teal" />
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
