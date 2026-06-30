"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  History,
  Loader2,
  Sparkles,
  GitCompareArrows,
  MessagesSquare,
  CheckCircle2,
  Database,
  Trash2,
} from "lucide-react";
import { Badge, type Tone } from "@/components/ui/badge";
import { useRunHistory } from "@/lib/hooks";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { pct, relativeTime, truncate } from "@/lib/format";
import { getRecentSearches, removeRecentSearch, type RecentSearch } from "@/lib/cache-storage";
import { deleteRun } from "@/lib/api";
import type { RunHistoryEntry, RunMode } from "@/lib/types";

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
  const { data: serverRuns, isLoading, isError } = useRunHistory();
  const qc = useQueryClient();

  // localStorage fallback — populated client-side on mount only
  const [localRuns, setLocalRuns] = useState<RunHistoryEntry[]>([]);
  useEffect(() => {
    const searches = getRecentSearches();
    setLocalRuns(
      searches.map((s: RecentSearch) => ({
        run_id: s.run_id,
        user_input: s.user_input,
        mode: s.mode,
        program_name: s.program_name ?? null,
        data_quality: s.data_quality ?? 0,
        status: (s.status as RunHistoryEntry["status"]) ?? "running",
        created_at: s.created_at,
      })),
    );
  }, []);

  // Server data is authoritative; fall back to localStorage when server returns nothing
  const runs = useMemo<RunHistoryEntry[]>(() => {
    if (serverRuns && serverRuns.length > 0) return serverRuns;
    return localRuns;
  }, [serverRuns, localRuns]);

  const deleteRunMutation = useMutation({
    mutationFn: (runId: string) => deleteRun(runId),
    onSuccess: (_data, runId) => {
      removeRecentSearch(runId);
      setLocalRuns((prev) => prev.filter((r) => r.run_id !== runId));
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["run-history"] });
    },
    onError: (_err, runId) => {
      // Even if backend fails, remove from localStorage
      removeRecentSearch(runId);
      setLocalRuns((prev) => prev.filter((r) => r.run_id !== runId));
    },
  });

  const isEmpty = !isLoading && runs.length === 0;

  return (
    <div className="overflow-hidden rounded-[12px] border border-line bg-white shadow-panel">
      {/* header */}
      <div className="flex items-center gap-2.5 border-b border-line bg-soft-grey/40 px-4 py-3">
        <History className="h-4 w-4 text-teal/70" />
        <h3 className="text-[13px] font-semibold text-navy">Recent analyses</h3>
        {runs.length > 0 && (
          <span className="ml-1 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-soft-grey px-1.5 text-[10px] font-semibold text-ink/50">
            {runs.length}
          </span>
        )}
        {isError && localRuns.length > 0 && (
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-amber/10 px-2 py-0.5 text-[10px] font-medium text-amber">
            <Database className="h-2.5 w-2.5" />
            offline · showing cached
          </span>
        )}
      </div>

      {isLoading && localRuns.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-ink/35">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      ) : isEmpty ? (
        <div className="py-14 text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-soft-grey">
            <Sparkles className="h-5 w-5 text-ink/25" />
          </div>
          <p className="text-sm font-medium text-ink/40">No analyses yet</p>
          <p className="mt-1 text-xs text-ink/30">
            Start one above to get intelligence on any loyalty program.
          </p>
        </div>
      ) : (
        <div className="divide-y divide-line">
          <div className="hidden grid-cols-[1fr_auto_auto] items-center gap-3 pl-4 pr-20 py-2 text-[10px] font-semibold uppercase tracking-wide text-ink/35 sm:grid">
            <span>Program / Input</span>
            <span className="w-[68px] text-center">Mode</span>
            <span className="w-[68px] text-center">Quality</span>
          </div>
          <ul className="divide-y divide-line">
            {runs.map((run) => {
              const Icon = MODE_ICON[run.mode] ?? Sparkles;
              const name = run.program_name ?? run.user_input;
              const isDeleting = deleteRunMutation.isPending && deleteRunMutation.variables === run.run_id;
              return (
                <li key={run.run_id} className="group flex items-center hover:bg-soft-grey/35 transition-colors">
                  <Link
                    href={`/run/${run.run_id}`}
                    className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3"
                  >
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

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium text-ink leading-tight">
                        {truncate(name, 68)}
                      </p>
                      {run.program_name && run.program_name !== run.user_input && (
                        <p className="mt-0.5 truncate text-[10px] text-ink/35">
                          {truncate(run.user_input, 50)}
                        </p>
                      )}
                      <p className="mt-0.5 font-mono text-[10px] text-ink/35">
                        {run.run_id.replace(/^run_/, "").slice(0, 10)} · {relativeTime(run.created_at)}
                      </p>
                    </div>

                    <Badge
                      tone={MODE_TONE[run.mode] ?? "teal"}
                      className="hidden w-[68px] justify-center shrink-0 capitalize sm:inline-flex text-[10px]"
                    >
                      {run.mode}
                    </Badge>

                    {run.status === "done" ? (
                      <span
                        className={`hidden sm:inline-flex items-center justify-center gap-1 w-[68px] shrink-0 rounded-pill px-2.5 py-1 text-[11px] font-semibold ${
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
                    ) : run.status === "cancelled" ? (
                      <Badge tone="amber" dot className="hidden w-[68px] justify-center shrink-0 sm:inline-flex text-[10px]">
                        stopped
                      </Badge>
                    ) : run.status === "error" ? (
                      <Badge tone="red" dot className="hidden w-[68px] justify-center shrink-0 sm:inline-flex text-[10px]">
                        error
                      </Badge>
                    ) : (
                      <Badge tone="teal" dot className="hidden w-[68px] justify-center shrink-0 sm:inline-flex text-[10px]">
                        running
                      </Badge>
                    )}

                    <ArrowUpRight className="h-4 w-4 shrink-0 text-ink/25 transition-colors group-hover:text-teal" />
                  </Link>
                  <div className="flex shrink-0 items-center pr-2">
                    <button
                      onClick={() => deleteRunMutation.mutate(run.run_id)}
                      disabled={isDeleting}
                      className="flex h-7 w-7 items-center justify-center rounded-full text-ink/25 opacity-0 transition group-hover:opacity-100 hover:bg-red/10 hover:text-red disabled:cursor-not-allowed"
                      title="Delete this analysis"
                    >
                      {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
