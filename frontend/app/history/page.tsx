"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Database,
  GitCompareArrows,
  History,
  Info,
  LayoutList,
  Loader2,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { Topbar } from "@/components/Topbar";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/textarea";
import { useRunHistory } from "@/lib/hooks";
import { cn, pct, relativeTime, truncate, formatDateTime } from "@/lib/format";
import { createRun, deleteRun } from "@/lib/api";
import { upsertRecentSearch, removeRecentSearch } from "@/lib/cache-storage";
import type { RunHistoryEntry, RunMode } from "@/lib/types";

type TypeFilter = "all" | "normal" | "compare";
type StatusFilter = "all" | RunHistoryEntry["status"];
type QualityFilter = "all" | "high" | "medium" | "low" | "unknown";
type SourceFilter = "all" | "db" | "live";
type SortKey = "newest" | "oldest" | "quality_desc" | "quality_asc" | "name_asc" | "mode";

const MODE_TONE: Record<RunMode, Tone> = {
  single: "teal",
  compare: "blue",
  converse: "teal",
};

const STATUS_TONE: Record<RunHistoryEntry["status"], Tone> = {
  done: "green",
  running: "teal",
  error: "red",
  clarification_needed: "blue",
  cancelled: "amber",
};

const STATUS_LABEL: Record<RunHistoryEntry["status"], string> = {
  done: "Complete",
  running: "Running",
  error: "Error",
  clarification_needed: "Needs clarification",
  cancelled: "Stopped",
};

const PROGRAM_COLORS = [
  { header: "bg-teal/15 text-teal border-teal/25", accent: "text-teal", label: "A" },
  { header: "bg-blue/15 text-blue border-blue/25", accent: "text-blue", label: "B" },
  { header: "bg-navy/15 text-navy border-navy/25", accent: "text-navy", label: "C" },
  { header: "bg-green/15 text-green border-green/25", accent: "text-green", label: "D" },
  { header: "bg-amber/15 text-amber border-amber/25", accent: "text-amber", label: "E" },
];

function analysisType(mode: RunMode): TypeFilter {
  return mode === "compare" ? "compare" : "normal";
}

function modeLabel(mode: RunMode): string {
  return mode === "compare" ? "Compare" : "Normal Analyse";
}

function displayName(run: RunHistoryEntry): string {
  return run.program_name || run.user_input || "Untitled analysis";
}

function detailHref(run: RunHistoryEntry): string {
  return run.mode === "compare" ? `/run/${run.run_id}/compare` : `/run/${run.run_id}`;
}

function qualityBucket(value: number): QualityFilter {
  if (!value) return "unknown";
  if (value >= 0.7) return "high";
  if (value >= 0.4) return "medium";
  return "low";
}

function qualityClass(value: number): string {
  if (!value) return "bg-soft-grey text-ink/45";
  if (value >= 0.7) return "bg-soft-green text-green";
  if (value >= 0.4) return "bg-soft-amber text-amber";
  return "bg-soft-red text-red";
}

// ── Selection / compare-from-history helpers ──────────────────────────────────

/** Extract individual program names from any history entry.
 *  Compare runs store program_name as "A vs B vs C" (server-joined). */
function extractProgramsFromRun(run: RunHistoryEntry): string[] {
  if (run.mode === "compare") {
    const raw = (run.program_name || run.user_input || "").trim();
    const parts = raw.split(/\s+vs\s+/i).map((p) => p.trim()).filter(Boolean);
    return parts.length >= 2 ? parts : [raw].filter(Boolean);
  }
  return [(run.program_name || run.user_input || "").trim()].filter(Boolean);
}

interface ResolvedProgram {
  name: string;
  fromRun: RunHistoryEntry;
  expandedFromCompare: boolean;
}

type CompareWarning =
  | { kind: "incomplete"; run: RunHistoryEntry; programs: string[] }
  | { kind: "duplicate"; displayName: string; sources: RunHistoryEntry[]; kept: RunHistoryEntry };

function resolveComparePrograms(selectedRuns: RunHistoryEntry[]): {
  resolved: ResolvedProgram[];
  warnings: CompareWarning[];
} {
  const warnings: CompareWarning[] = [];

  // Warn about every non-done run that was selected
  for (const run of selectedRuns) {
    if (run.status !== "done") {
      warnings.push({ kind: "incomplete", run, programs: extractProgramsFromRun(run) });
    }
  }

  // Flatten to (name, normalized, run, expandedFromCompare) entries
  type Entry = { name: string; normalized: string; run: RunHistoryEntry; expanded: boolean };
  const entries: Entry[] = [];
  for (const run of selectedRuns) {
    const progs = extractProgramsFromRun(run);
    const expanded = run.mode === "compare" && progs.length > 1;
    for (const name of progs) {
      entries.push({ name, normalized: name.toLowerCase().trim(), run, expanded });
    }
  }

  // Group by normalized name — later we pick the best from each group
  const groups = new Map<string, Entry[]>();
  for (const e of entries) {
    if (!groups.has(e.normalized)) groups.set(e.normalized, []);
    groups.get(e.normalized)!.push(e);
  }

  const resolved: ResolvedProgram[] = [];
  for (const [, group] of groups) {
    if (group.length === 1) {
      resolved.push({ name: group[0].name, fromRun: group[0].run, expandedFromCompare: group[0].expanded });
    } else {
      // Pick: prefer done, then most recent
      const sorted = [...group].sort((a, b) => {
        const scoreA = a.run.status === "done" ? 1 : 0;
        const scoreB = b.run.status === "done" ? 1 : 0;
        if (scoreB !== scoreA) return scoreB - scoreA;
        return new Date(b.run.created_at).getTime() - new Date(a.run.created_at).getTime();
      });
      const best = sorted[0];
      warnings.push({
        kind: "duplicate",
        displayName: best.name,
        sources: group.map((e) => e.run),
        kept: best.run,
      });
      resolved.push({ name: best.name, fromRun: best.run, expandedFromCompare: best.expanded });
    }
  }

  return { resolved, warnings };
}

function rowKey(run: RunHistoryEntry): string {
  return `${run.source ?? "db"}-${run.run_id}`;
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const { data: runs = [], isLoading, isError, refetch } = useRunHistory();
  const router = useRouter();
  const qc = useQueryClient();

  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [qualityFilter, setQualityFilter] = useState<QualityFilter>("all");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("newest");

  // Selection state
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [reviewOpen, setReviewOpen] = useState(false);

  const createCompareMutation = useMutation({
    mutationFn: (programs: string[]) =>
      createRun({ user_input: programs[0], mode: "compare", programs }),
    onSuccess: (data, programs) => {
      upsertRecentSearch({
        run_id: data.run_id,
        user_input: programs[0],
        mode: "compare",
        programs,
        created_at: new Date().toISOString(),
        status: "running",
      });
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["run-history"] });
      router.push(`/run/${data.run_id}/compare`);
    },
  });

  const deleteRunMutation = useMutation({
    mutationFn: (runId: string) => deleteRun(runId),
    onSuccess: (_data, runId) => {
      removeRecentSearch(runId);
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["run-history"] });
    },
  });

  function handleDeleteRun(runId: string) {
    deleteRunMutation.mutate(runId);
  }

  function handleDeleteSelected() {
    for (const run of selectedRuns) {
      deleteRunMutation.mutate(run.run_id);
    }
    exitSelectionMode();
  }

  function toggleSelectionMode() {
    setSelectionMode((prev) => !prev);
    setSelectedIds(new Set());
    setReviewOpen(false);
  }

  function toggleRowSelection(key: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function exitSelectionMode() {
    setSelectionMode(false);
    setSelectedIds(new Set());
    setReviewOpen(false);
  }

  const selectedRuns = useMemo(
    () => runs.filter((r) => selectedIds.has(rowKey(r))),
    [runs, selectedIds],
  );

  // Count resolved programs (after dedup) for the action bar
  const resolvedProgramCount = useMemo(() => {
    if (selectedRuns.length === 0) return 0;
    const { resolved } = resolveComparePrograms(selectedRuns);
    return resolved.length;
  }, [selectedRuns]);

  const stats = useMemo(() => {
    const normal = runs.filter((run) => analysisType(run.mode) === "normal").length;
    const compare = runs.filter((run) => run.mode === "compare").length;
    const complete = runs.filter((run) => run.status === "done").length;
    const avgQuality =
      complete > 0
        ? runs
            .filter((run) => run.status === "done")
            .reduce((sum, run) => sum + (run.data_quality || 0), 0) / complete
        : 0;
    return { total: runs.length, normal, compare, complete, avgQuality };
  }, [runs]);

  const filtered = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return runs
      .filter((run) => {
        const haystack = [
          run.run_id,
          run.user_input,
          run.program_name ?? "",
          modeLabel(run.mode),
          run.status,
        ]
          .join(" ")
          .toLowerCase();
        if (normalizedQuery && !haystack.includes(normalizedQuery)) return false;
        if (typeFilter !== "all" && analysisType(run.mode) !== typeFilter) return false;
        if (statusFilter !== "all" && run.status !== statusFilter) return false;
        if (qualityFilter !== "all" && qualityBucket(run.data_quality) !== qualityFilter) return false;
        if (sourceFilter !== "all" && run.source !== sourceFilter) return false;
        return true;
      })
      .sort((a, b) => {
        if (sortKey === "oldest") {
          return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
        }
        if (sortKey === "quality_desc") return (b.data_quality || 0) - (a.data_quality || 0);
        if (sortKey === "quality_asc") return (a.data_quality || 0) - (b.data_quality || 0);
        if (sortKey === "name_asc") return displayName(a).localeCompare(displayName(b));
        if (sortKey === "mode") return modeLabel(a.mode).localeCompare(modeLabel(b.mode));
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      });
  }, [qualityFilter, query, runs, sortKey, sourceFilter, statusFilter, typeFilter]);

  const hasFilters =
    query ||
    typeFilter !== "all" ||
    statusFilter !== "all" ||
    qualityFilter !== "all" ||
    sourceFilter !== "all" ||
    sortKey !== "newest";

  function clearFilters() {
    setQuery("");
    setTypeFilter("all");
    setStatusFilter("all");
    setQualityFilter("all");
    setSourceFilter("all");
    setSortKey("newest");
  }

  return (
    <div className={cn("min-h-screen bg-canvas", selectionMode && "pb-28")}>
      <Topbar>
        <Link href="/">
          <Button size="sm" variant="outline">
            <ArrowLeft className="h-4 w-4" />
            New analysis
          </Button>
        </Link>
      </Topbar>

      <main className="mx-auto max-w-7xl px-5 py-7">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-teal">
              <History className="h-3.5 w-3.5" />
              Analysis Library
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-navy">
              Previous analyses
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-ink/55">
              Search, filter, sort, and reopen completed loyalty intelligence runs.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant={selectionMode ? "primary" : "outline"}
              onClick={toggleSelectionMode}
            >
              <GitCompareArrows className="h-4 w-4" />
              {selectionMode ? "Cancel selection" : "Compare runs"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isLoading}>
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />}
              Refresh
            </Button>
          </div>
        </div>

        {selectionMode && (
          <div className="mb-4 flex items-start gap-3 rounded-[10px] border border-teal/30 bg-teal/5 px-4 py-3 text-sm text-ink/70">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-teal" />
            <div>
              <span className="font-semibold text-navy">Selection mode active.</span>
              {" "}Click rows to select runs. You can mix normal and compare runs — programs from compare runs will be expanded.
              Select at least 2 runs to enable comparison.
            </div>
          </div>
        )}

        <section className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard icon={LayoutList} label="Total analyses" value={String(stats.total)} />
          <StatCard icon={Sparkles} label="Normal analyses" value={String(stats.normal)} />
          <StatCard icon={GitCompareArrows} label="Compare analyses" value={String(stats.compare)} />
          <StatCard icon={CheckCircle2} label="Avg. Content Extracted" value={stats.complete ? pct(stats.avgQuality) : "-"} />
        </section>

        <section className="mb-5 rounded-[12px] border border-line bg-white p-4 shadow-panel">
          <div className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_auto_auto_auto_auto]">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/30" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search program, input, run id..."
                className="pl-9"
              />
            </label>

            <Select label="Type" value={typeFilter} onChange={(value) => setTypeFilter(value as TypeFilter)}>
              <option value="all">All types</option>
              <option value="normal">Normal Analyse</option>
              <option value="compare">Compare</option>
            </Select>

            <Select label="Status" value={statusFilter} onChange={(value) => setStatusFilter(value as StatusFilter)}>
              <option value="all">All statuses</option>
              <option value="done">Complete</option>
              <option value="running">Running</option>
              <option value="error">Error</option>
              <option value="clarification_needed">Needs clarification</option>
              <option value="cancelled">Stopped</option>
            </Select>

            <Select label="Content Extracted" value={qualityFilter} onChange={(value) => setQualityFilter(value as QualityFilter)}>
              <option value="all">All</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
              <option value="unknown">Unknown</option>
            </Select>

            <Select label="Sort" value={sortKey} onChange={(value) => setSortKey(value as SortKey)}>
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="quality_desc">Content extracted high to low</option>
              <option value="quality_asc">Content extracted low to high</option>
              <option value="name_asc">Name A-Z</option>
              <option value="mode">Type</option>
            </Select>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-ink/45">
              <SlidersHorizontal className="h-3.5 w-3.5" />
              Showing {filtered.length} of {runs.length}
            </span>
            <Select
              label="Source"
              value={sourceFilter}
              onChange={(value) => setSourceFilter(value as SourceFilter)}
              compact
            >
              <option value="all">All sources</option>
              <option value="db">Database</option>
              <option value="live">Live session</option>
            </Select>
            {hasFilters && (
              <button
                onClick={clearFilters}
                className="ml-auto inline-flex items-center gap-1.5 rounded-pill border border-line bg-white px-3 py-1.5 text-xs font-medium text-ink/55 transition hover:bg-soft-grey hover:text-navy"
              >
                <X className="h-3.5 w-3.5" />
                Clear
              </button>
            )}
          </div>
        </section>

        <section className="overflow-hidden rounded-[12px] border border-line bg-white shadow-panel">
          <div
            className={cn(
              "hidden border-b border-line bg-soft-grey/50 px-4 py-2.5 text-[10px] font-semibold uppercase tracking-wide text-ink/45 lg:grid",
              selectionMode
                ? "grid-cols-[32px_1.5fr_150px_140px_130px_100px] gap-4"
                : "grid-cols-[1.5fr_150px_140px_130px_100px] gap-4",
            )}
          >
            {selectionMode && (
              <span className="flex items-center">
                <input
                  type="checkbox"
                  readOnly
                  checked={selectedIds.size > 0 && filtered.every((r) => selectedIds.has(rowKey(r)))}
                  ref={(el) => {
                    if (el) el.indeterminate = selectedIds.size > 0 && !filtered.every((r) => selectedIds.has(rowKey(r)));
                  }}
                  onChange={() => {
                    const allKeys = filtered.map(rowKey);
                    const allSelected = allKeys.every((k) => selectedIds.has(k));
                    if (allSelected) {
                      setSelectedIds((prev) => {
                        const next = new Set(prev);
                        allKeys.forEach((k) => next.delete(k));
                        return next;
                      });
                    } else {
                      setSelectedIds((prev) => {
                        const next = new Set(prev);
                        allKeys.forEach((k) => next.add(k));
                        return next;
                      });
                    }
                  }}
                  className="h-4 w-4 cursor-pointer accent-teal"
                  title="Select all visible"
                />
              </span>
            )}
            <span>Analysis</span>
            <span>Type</span>
            <span>Status</span>
            <span>Quality</span>
            <span />
          </div>

          {isLoading ? (
            <StateBlock icon={Loader2} title="Loading analyses..." spinning />
          ) : isError ? (
            <StateBlock icon={Database} title="History is unavailable" text="The backend history endpoint could not be reached." />
          ) : filtered.length === 0 ? (
            <StateBlock
              icon={Search}
              title={runs.length === 0 ? "No analyses yet" : "No matching analyses"}
              text={runs.length === 0 ? "Run a normal analysis or comparison and it will appear here." : "Try adjusting the search or filters."}
            />
          ) : (
            <ul className="divide-y divide-line">
              {filtered.map((run) => (
                <HistoryRow
                  key={rowKey(run)}
                  run={run}
                  selectionMode={selectionMode}
                  isSelected={selectedIds.has(rowKey(run))}
                  onToggle={() => toggleRowSelection(rowKey(run))}
                  onDelete={() => handleDeleteRun(run.run_id)}
                  isDeleting={deleteRunMutation.isPending && deleteRunMutation.variables === run.run_id}
                />
              ))}
            </ul>
          )}
        </section>
      </main>

      {/* Floating selection action bar */}
      {selectionMode && (
        <SelectionBar
          selectedCount={selectedRuns.length}
          programCount={resolvedProgramCount}
          canCompare={resolvedProgramCount >= 2}
          onCompare={() => setReviewOpen(true)}
          onCancel={exitSelectionMode}
          onDeleteSelected={handleDeleteSelected}
          isDeletingSelected={deleteRunMutation.isPending}
        />
      )}

      {/* Review modal */}
      {reviewOpen && (
        <CompareReviewModal
          selectedRuns={selectedRuns}
          onConfirm={(programs) => createCompareMutation.mutate(programs)}
          onClose={() => setReviewOpen(false)}
          isLoading={createCompareMutation.isPending}
          error={createCompareMutation.isError ? (createCompareMutation.error as Error)?.message : null}
        />
      )}
    </div>
  );
}

// ── HistoryRow ────────────────────────────────────────────────────────────────

function HistoryRow({
  run,
  selectionMode,
  isSelected,
  onToggle,
  onDelete,
  isDeleting,
}: {
  run: RunHistoryEntry;
  selectionMode: boolean;
  isSelected: boolean;
  onToggle: () => void;
  onDelete: () => void;
  isDeleting: boolean;
}) {
  const isCompare = run.mode === "compare";
  const Icon = isCompare ? GitCompareArrows : Sparkles;
  const expandedPrograms = isCompare ? extractProgramsFromRun(run) : null;

  const innerContent = (
    <>
      {selectionMode && (
        <span
          className="flex items-center justify-center"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={isSelected}
            onChange={onToggle}
            className="h-4 w-4 cursor-pointer accent-teal rounded"
          />
        </span>
      )}

      <div className="flex min-w-0 items-start gap-3">
        <span
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
            isCompare ? "bg-blue/10 text-blue" : "bg-teal/10 text-teal",
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-navy">
            {truncate(displayName(run), 90)}
          </p>
          {run.program_name && run.program_name !== run.user_input && (
            <p className="mt-0.5 truncate text-xs text-ink/45">
              {truncate(run.user_input, 80)}
            </p>
          )}
          {/* In selection mode, show expanded programs for compare runs */}
          {selectionMode && isCompare && expandedPrograms && expandedPrograms.length > 1 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {expandedPrograms.map((prog, i) => (
                <span
                  key={i}
                  className="inline-flex items-center rounded-pill bg-blue/10 px-2 py-0.5 text-[10px] font-medium text-blue"
                >
                  {prog}
                </span>
              ))}
            </div>
          )}
          <div className="mt-1 space-y-0.5 text-[10px] text-ink/35">
            <p className="font-mono">{run.run_id.replace(/^run_/, "").slice(0, 12)}</p>
            <p className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-navy">
                {formatDateTime(run.created_at)}
              </span>
              <span className="font-sans">.</span>
              <span className="inline-flex items-center gap-1 font-sans">
                <Clock className="h-3 w-3" />
                {relativeTime(run.created_at)}
              </span>
              {run.source && (
                <>
                  <span className="font-sans">.</span>
                  <span className="font-sans capitalize">{run.source}</span>
                </>
              )}
            </p>
          </div>
        </div>
      </div>

      <Badge tone={MODE_TONE[run.mode]} className="w-fit text-[10px]">
        {modeLabel(run.mode)}
      </Badge>

      <Badge tone={STATUS_TONE[run.status]} dot className="w-fit text-[10px]">
        {STATUS_LABEL[run.status]}
      </Badge>

      <span className={cn("inline-flex w-fit items-center rounded-pill px-2.5 py-1 text-[11px] font-semibold", qualityClass(run.data_quality))}>
        {run.data_quality ? pct(run.data_quality) : "No score"}
      </span>

      {!selectionMode && (
        <span className="inline-flex items-center gap-1 text-xs font-semibold text-teal lg:justify-end">
          View details
          <ArrowUpRight className="h-4 w-4 transition group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
        </span>
      )}
    </>
  );

  const selectionGridClass = cn(
    "gap-3 px-4 py-4 transition grid lg:grid-cols-[32px_1.5fr_150px_140px_130px] lg:items-center",
  );

  const linkGridClass = cn(
    "gap-3 pl-4 py-4 transition grid flex-1 min-w-0 lg:grid-cols-[1.5fr_150px_140px_130px_100px] lg:items-center",
  );

  if (selectionMode) {
    return (
      <li>
        <div
          role="button"
          tabIndex={0}
          onClick={onToggle}
          onKeyDown={(e) => e.key === "Enter" && onToggle()}
          className={cn(
            selectionGridClass,
            "cursor-pointer select-none hover:bg-soft-grey/35",
            isSelected && "bg-teal/5 ring-1 ring-inset ring-teal/25",
          )}
        >
          {innerContent}
        </div>
      </li>
    );
  }

  return (
    <li className="group flex items-center hover:bg-soft-grey/35 transition">
      <Link
        href={detailHref(run)}
        className={linkGridClass}
      >
        {innerContent}
      </Link>
      <div className="flex shrink-0 items-center pr-2">
        <button
          onClick={onDelete}
          disabled={isDeleting}
          className="flex h-7 w-7 items-center justify-center rounded-full text-ink/25 opacity-0 transition group-hover:opacity-100 hover:bg-red/10 hover:text-red disabled:cursor-not-allowed"
          title="Delete this analysis"
        >
          {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
        </button>
      </div>
    </li>
  );
}

// ── SelectionBar ──────────────────────────────────────────────────────────────

function SelectionBar({
  selectedCount,
  programCount,
  canCompare,
  onCompare,
  onCancel,
  onDeleteSelected,
  isDeletingSelected,
}: {
  selectedCount: number;
  programCount: number;
  canCompare: boolean;
  onCompare: () => void;
  onCancel: () => void;
  onDeleteSelected: () => void;
  isDeletingSelected: boolean;
}) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-white/95 shadow-[0_-4px_20px_rgba(0,0,0,0.08)] backdrop-blur-sm">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-5 py-4">
        <div className="min-w-0 flex-1">
          {selectedCount === 0 ? (
            <p className="text-sm text-ink/50">Select runs from the list above to compare or delete them.</p>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-pill bg-teal/10 px-3 py-1 text-sm font-semibold text-teal">
                {selectedCount} {selectedCount === 1 ? "run" : "runs"} selected
              </span>
              <span className="text-ink/40">·</span>
              <span className="text-sm font-medium text-ink/65">
                {programCount === 0
                  ? "No programs extracted"
                  : `${programCount} unique ${programCount === 1 ? "program" : "programs"}`}
              </span>
              {!canCompare && selectedCount > 0 && (
                <span className="text-xs text-amber">
                  — select at least 2 different programs to compare
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button size="sm" variant="outline" onClick={onCancel}>
            <X className="h-4 w-4" />
            Cancel
          </Button>
          {selectedCount > 0 && (
            <Button
              size="sm"
              variant="outline"
              disabled={isDeletingSelected}
              onClick={onDeleteSelected}
              className="border-red/30 text-red hover:bg-red/5 hover:border-red/50"
            >
              {isDeletingSelected ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Delete {selectedCount > 1 ? `${selectedCount} runs` : "run"}
            </Button>
          )}
          <Button
            size="sm"
            disabled={!canCompare}
            onClick={onCompare}
            className={cn(canCompare && "bg-teal text-white hover:bg-teal/90")}
          >
            <GitCompareArrows className="h-4 w-4" />
            Compare {programCount >= 2 ? `${programCount} programs` : "programs"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── CompareReviewModal ────────────────────────────────────────────────────────

function CompareReviewModal({
  selectedRuns,
  onConfirm,
  onClose,
  isLoading,
  error,
}: {
  selectedRuns: RunHistoryEntry[];
  onConfirm: (programs: string[]) => void;
  onClose: () => void;
  isLoading: boolean;
  error: string | null;
}) {
  const { resolved, warnings } = useMemo(
    () => resolveComparePrograms(selectedRuns),
    [selectedRuns],
  );
  const canCompare = resolved.length >= 2;
  const incompleteWarnings = warnings.filter((w): w is Extract<CompareWarning, { kind: "incomplete" }> => w.kind === "incomplete");
  const duplicateWarnings = warnings.filter((w): w is Extract<CompareWarning, { kind: "duplicate" }> => w.kind === "duplicate");

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative mx-4 flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-[16px] border border-line bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-line px-6 py-4">
          <div>
            <div className="flex items-center gap-2">
              <GitCompareArrows className="h-4 w-4 text-teal" />
              <h2 className="text-base font-semibold text-navy">Review comparison</h2>
            </div>
            <p className="mt-0.5 text-[12px] text-ink/50">
              {selectedRuns.length} {selectedRuns.length === 1 ? "run" : "runs"} selected
              {" · "}
              {resolved.length} unique {resolved.length === 1 ? "program" : "programs"} will be compared
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={isLoading}
            className="ml-3 mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-ink/40 transition hover:bg-soft-grey hover:text-navy"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">

          {/* Warnings */}
          {(incompleteWarnings.length > 0 || duplicateWarnings.length > 0) && (
            <div className="space-y-2.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-ink/40">Notices</p>

              {incompleteWarnings.map((w, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 rounded-[10px] border border-amber/30 bg-amber/5 px-4 py-3"
                >
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber" />
                  <div className="min-w-0 text-[12px] leading-relaxed text-ink/70">
                    <span className="font-semibold text-navy">
                      &ldquo;{truncate(displayName(w.run), 55)}&rdquo;
                    </span>
                    {" "}has status{" "}
                    <span className="font-semibold capitalize text-amber">
                      {STATUS_LABEL[w.run.status]}
                    </span>
                    {" "}— the analysis may be incomplete or have no data.
                    {w.programs.length > 0 && (
                      <>
                        {" "}
                        Its {w.programs.length === 1 ? "program" : "programs"} (
                        <span className="font-medium text-navy">{w.programs.join(", ")}</span>)
                        will still be included — the backend will use any cached data available.
                      </>
                    )}
                  </div>
                </div>
              ))}

              {duplicateWarnings.map((w, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 rounded-[10px] border border-blue/20 bg-blue/5 px-4 py-3"
                >
                  <Info className="mt-0.5 h-4 w-4 shrink-0 text-blue" />
                  <div className="min-w-0 text-[12px] leading-relaxed text-ink/70">
                    <span className="font-semibold text-navy">
                      &ldquo;{w.displayName}&rdquo;
                    </span>
                    {" "}appears in{" "}
                    <span className="font-semibold text-navy">{w.sources.length} selected runs</span>.
                    {" "}Using data from the most recent completed analysis
                    {" "}(<span className="font-medium text-navy">{formatDateTime(w.kept.created_at)}</span>).
                    {" "}It will only appear once in the comparison.
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Programs list */}
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-ink/40">
              Programs to compare
            </p>

            {resolved.length === 0 ? (
              <div className="rounded-[10px] border border-line bg-soft-grey/40 px-4 py-6 text-center text-sm text-ink/40">
                No programs could be extracted from the selected runs.
              </div>
            ) : (
              <div className="space-y-2">
                {resolved.map((prog, i) => {
                  const c = PROGRAM_COLORS[i % PROGRAM_COLORS.length];
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-3 rounded-[10px] border border-line bg-soft-grey/20 px-4 py-3"
                    >
                      <span
                        className={cn(
                          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold",
                          c.header,
                        )}
                      >
                        {c.label}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-navy">{prog.name}</p>
                        <p className="mt-0.5 truncate text-[10px] text-ink/45">
                          {prog.expandedFromCompare
                            ? `expanded from compare run · ${formatDateTime(prog.fromRun.created_at)}`
                            : `from "${truncate(displayName(prog.fromRun), 40)}" · ${formatDateTime(prog.fromRun.created_at)}`}
                          {prog.fromRun.status !== "done" && (
                            <span className="ml-1.5 font-semibold text-amber">
                              ({STATUS_LABEL[prog.fromRun.status]})
                            </span>
                          )}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {!canCompare && resolved.length < 2 && (
            <div className="flex items-center gap-2 rounded-[10px] border border-red/20 bg-red/5 px-4 py-3 text-[12px] text-red">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              At least 2 unique programs are required to start a comparison.
              Please go back and select more runs.
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 rounded-[10px] border border-red/20 bg-red/5 px-4 py-3 text-[12px] text-red">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Failed to start comparison: {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-line px-6 py-4">
          <p className="text-[11px] text-ink/40">
            {canCompare
              ? `The backend will reuse cached data where available.`
              : "Select more runs to enable comparison."}
          </p>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={onClose} disabled={isLoading}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={!canCompare || isLoading}
              onClick={() => onConfirm(resolved.map((p) => p.name))}
              className={cn(canCompare && !isLoading && "bg-teal text-white hover:bg-teal/90")}
            >
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <GitCompareArrows className="h-4 w-4" />
              )}
              {isLoading ? "Starting…" : `Compare ${resolved.length} programs`}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof History;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-[10px] border border-line bg-white px-4 py-3 shadow-sm">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-ink/45">
        <Icon className="h-3.5 w-3.5 text-teal" />
        {label}
      </div>
      <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-navy">{value}</p>
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  children,
  compact = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <label className={cn("block", compact ? "w-auto" : "min-w-[150px]")}>
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={cn(
          "h-10 rounded-card border border-line bg-white px-3 text-sm text-ink shadow-sm transition focus:border-teal focus:outline-none focus:ring-2 focus:ring-teal/30",
          compact ? "w-auto text-xs" : "w-full",
        )}
      >
        {children}
      </select>
    </label>
  );
}

function StateBlock({
  icon: Icon,
  title,
  text,
  spinning = false,
}: {
  icon: typeof History;
  title: string;
  text?: string;
  spinning?: boolean;
}) {
  return (
    <div className="flex min-h-[280px] flex-col items-center justify-center px-5 text-center">
      <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-soft-grey">
        <Icon className={cn("h-5 w-5 text-ink/35", spinning && "animate-spin")} />
      </div>
      <p className="text-sm font-semibold text-navy">{title}</p>
      {text && <p className="mt-1 max-w-sm text-xs text-ink/45">{text}</p>}
    </div>
  );
}
