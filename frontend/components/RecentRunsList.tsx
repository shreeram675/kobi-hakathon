"use client";

import Link from "next/link";
import { ArrowUpRight, History } from "lucide-react";
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

/** Home-page run history table. */
export function RecentRunsList() {
  const { data: runs, isLoading } = useRuns();

  return (
    <div className="overflow-hidden rounded-card border border-line bg-white shadow-panel">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <History className="h-4 w-4 text-ink/40" />
        <h3 className="text-sm font-semibold text-navy">Recent runs</h3>
        {runs && runs.length > 0 && (
          <Badge tone="grey" className="ml-auto">
            {runs.length}
          </Badge>
        )}
      </div>

      {isLoading ? (
        <p className="px-4 py-8 text-center text-sm text-ink/40">Loading…</p>
      ) : !runs || runs.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-ink/40">
          No runs yet — start an analysis above.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {runs.map((run) => (
            <li key={run.run_id}>
              <Link
                href={`/run/${run.run_id}`}
                className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-soft-grey/40"
              >
                <Badge tone={MODE_TONE[run.mode]} className="shrink-0 capitalize">
                  {run.mode}
                </Badge>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">
                    {truncate(run.user_input, 72)}
                  </p>
                  <p className="font-mono text-[10px] text-ink/40">
                    {run.run_id} · {relativeTime(run.created_at)}
                  </p>
                </div>
                {run.status === "done" ? (
                  <Badge tone={confidenceTone(run.data_quality)} className="shrink-0">
                    {pct(run.data_quality)} quality
                  </Badge>
                ) : (
                  <Badge tone="amber" dot className="shrink-0">
                    running
                  </Badge>
                )}
                <ArrowUpRight className="h-4 w-4 shrink-0 text-ink/30 transition-colors group-hover:text-teal" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
