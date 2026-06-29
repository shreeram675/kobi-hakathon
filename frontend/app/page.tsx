"use client";

import Link from "next/link";
import { useState } from "react";
import {
  History,
  Loader2,
  Sparkles,
  GitCompareArrows,
  MessageCircle,
  TrendingUp,
  Shield,
  Zap,
  Plus,
  X,
} from "lucide-react";
import { Topbar } from "@/components/Topbar";
import { RunModeTab } from "@/components/RunModeTab";
import { RecentRunsList } from "@/components/RecentRunsList";
import { Button } from "@/components/ui/button";
import { Textarea, Input } from "@/components/ui/textarea";
import { CacheDecisionModal, type CacheDecision } from "@/components/CacheDecisionModal";
import { CompareCacheModal, type CompareCacheDecision } from "@/components/CompareCacheModal";
import { useCreateRun } from "@/lib/hooks";
import { checkCache, checkCacheMulti } from "@/lib/api";
import type { CacheCheckResult, CompareCacheCheckItem, CreateRunBody, RunMode } from "@/lib/types";
import { cn } from "@/lib/format";

const EXAMPLES = ["Marriott Bonvoy", "Hilton Honors", "Delta SkyMiles", "World of Hyatt"];

const PROGRAM_COLORS = [
  { label: "A", bg: "bg-teal/10", text: "text-teal", border: "border-teal/30", ring: "ring-teal/30" },
  { label: "B", bg: "bg-blue/10", text: "text-blue", border: "border-blue/30", ring: "ring-blue/30" },
  { label: "C", bg: "bg-navy/10", text: "text-navy", border: "border-navy/30", ring: "ring-navy/30" },
  { label: "D", bg: "bg-green/10", text: "text-green", border: "border-green/30", ring: "ring-green/30" },
  { label: "E", bg: "bg-amber/10", text: "text-amber", border: "border-amber/30", ring: "ring-amber/30" },
];

const MODE_DETAIL: Record<RunMode, { title: string; sub: string; cta: string }> = {
  single: {
    title: "Single Program Analysis",
    sub: "Full pipeline: identity resolution → web retrieval → claim extraction → conflict adjudication → analyst brief.",
    cta: "Run analysis",
  },
  compare: {
    title: "Side-by-Side Comparison",
    sub: "Run each program sequentially through the full pipeline, then surface a field-by-field comparison with insights.",
    cta: "Run comparison",
  },
  converse: {
    title: "Analyse & Chat",
    sub: "Full extraction first, then ask grounded follow-up questions against verified claims.",
    cta: "Analyse & open chat",
  },
};

const CAPABILITY_CHIPS = [
  { icon: Shield, label: "Source-verified claims" },
  { icon: Zap, label: "Conflict adjudication" },
  { icon: TrendingUp, label: "Field coverage scoring" },
];

export default function HomePage() {
  const [mode, setMode] = useState<RunMode>("single");
  const [input, setInput] = useState("");
  const [programs, setPrograms] = useState<string[]>(["", ""]);
  const [isChecking, setIsChecking] = useState(false);

  const [singleModal, setSingleModal] = useState<{
    result: CacheCheckResult;
    body: CreateRunBody;
  } | null>(null);

  const [compareModal, setCompareModal] = useState<{
    results: CompareCacheCheckItem[];
    body: CreateRunBody;
  } | null>(null);

  const create = useCreateRun();
  const detail = MODE_DETAIL[mode];

  const canSubmit =
    mode === "compare"
      ? programs.filter((p) => p.trim()).length >= 2
      : input.trim().length > 0;

  function addProgram() {
    if (programs.length < 5) setPrograms((prev) => [...prev, ""]);
  }

  function removeProgram(idx: number) {
    if (programs.length <= 2) return;
    setPrograms((prev) => prev.filter((_, i) => i !== idx));
  }

  function updateProgram(idx: number, value: string) {
    setPrograms((prev) => prev.map((p, i) => (i === idx ? value : p)));
  }

  async function handleSubmit() {
    if (!canSubmit || create.isPending || isChecking) return;
    setIsChecking(true);
    try {
      if (mode === "compare") {
        const cleaned = programs.map((p) => p.trim()).filter(Boolean);
        const body: CreateRunBody = { user_input: cleaned[0], mode, programs: cleaned };
        const results = await checkCacheMulti(cleaned);
        if (results.some((r) => r.found)) {
          setCompareModal({ results, body });
          return;
        }
        create.mutate(body);
      } else {
        const body: CreateRunBody = { user_input: input.trim(), mode };
        const result = await checkCache(input.trim());
        if (result.found) {
          setSingleModal({ result, body });
          return;
        }
        create.mutate(body);
      }
    } catch {
      // Cache check failed — run without cache modal
      if (mode === "compare") {
        const cleaned = programs.map((p) => p.trim()).filter(Boolean);
        create.mutate({ user_input: cleaned[0], mode, programs: cleaned });
      } else {
        create.mutate({ user_input: input.trim(), mode });
      }
    } finally {
      setIsChecking(false);
    }
  }

  function handleSingleDecision(choice: CacheDecision) {
    if (!singleModal) return;
    if (choice === "cancel") { setSingleModal(null); return; }
    create.mutate({ ...singleModal.body, force_fresh: choice === "fresh" });
    setSingleModal(null);
  }

  function handleCompareDecision(choice: CompareCacheDecision) {
    if (!compareModal) return;
    if (choice === "cancel") { setCompareModal(null); return; }
    create.mutate({ ...compareModal.body, force_fresh: choice === "fresh" });
    setCompareModal(null);
  }

  function fillExample(ex: string) {
    if (mode === "compare") {
      const firstEmpty = programs.findIndex((p) => !p.trim());
      updateProgram(firstEmpty >= 0 ? firstEmpty : 0, ex);
    } else {
      setInput(ex);
    }
  }

  const busy = create.isPending || isChecking;

  return (
    <div className="min-h-screen flex flex-col">
      <Topbar>
        <Link href="/history">
          <Button size="sm" variant="ghost" className="text-white/75 hover:bg-white/10 hover:text-white">
            <History className="h-4 w-4" />
            History
          </Button>
        </Link>
        <RunModeTab value={mode} onChange={setMode} />
      </Topbar>

      {/* ── Hero ── */}
      <div className="relative overflow-hidden border-b border-white/8 bg-[#0d1b2a] hero-mesh">
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />

        <div className="relative mx-auto max-w-3xl px-5 py-12 sm:py-16 text-center">
          <div className="inline-flex items-center gap-2 mb-5 rounded-pill border border-white/10 bg-white/5 px-3.5 py-1.5 text-xs font-medium text-white/65 shadow-sm backdrop-blur-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-[#F47920] animate-pulse" />
            Loyalty Intelligence Platform
            <span className="ml-1 text-white/30">·</span>
            <span className="text-white/45">AI-powered, source-verified</span>
          </div>

          <h1 className="text-balance text-3xl sm:text-[2.4rem] font-bold tracking-tight text-white leading-[1.15] mb-4">
            {detail.title}
          </h1>
          <p className="mx-auto max-w-lg text-sm text-white/55 leading-relaxed mb-3">
            {detail.sub}
          </p>

          <div className="flex flex-wrap justify-center gap-2 mb-8">
            {CAPABILITY_CHIPS.map(({ icon: Icon, label }) => (
              <span
                key={label}
                className="inline-flex items-center gap-1.5 rounded-pill bg-white/[0.06] px-2.5 py-1 text-[11px] font-medium text-white/50 border border-white/8"
              >
                <Icon className="h-3 w-3 text-teal" />
                {label}
              </span>
            ))}
          </div>

          {/* input card */}
          <div className="mx-auto max-w-xl rounded-[14px] border border-white/10 bg-white/[0.05] p-4 text-left shadow-[0_24px_60px_rgba(0,0,0,0.35)] backdrop-blur-sm">
            {mode === "compare" ? (
              <div className="space-y-2.5">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
                    Programs to compare
                  </span>
                  <span className="text-[10px] text-white/30">
                    {programs.filter((p) => p.trim()).length}/{programs.length} filled · min 2
                  </span>
                </div>

                {programs.map((prog, idx) => {
                  const color = PROGRAM_COLORS[idx % PROGRAM_COLORS.length];
                  return (
                    <div key={idx} className="flex items-center gap-2">
                      <span
                        className={cn(
                          "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold",
                          color.bg,
                          color.text,
                        )}
                      >
                        {color.label}
                      </span>
                      <Input
                        value={prog}
                        onChange={(e) => updateProgram(idx, e.target.value)}
                        onKeyDown={(e) => {
                          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleSubmit();
                        }}
                        placeholder={`e.g. ${EXAMPLES[idx % EXAMPLES.length]}`}
                        className={cn("flex-1 transition-all", prog.trim() && `ring-1 ${color.ring}`)}
                      />
                      {programs.length > 2 && (
                        <button
                          onClick={() => removeProgram(idx)}
                          className="shrink-0 rounded-full p-1 text-white/30 transition hover:bg-white/10 hover:text-white/70"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  );
                })}

                {programs.length < 5 && (
                  <button
                    onClick={addProgram}
                    className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-white/15 py-2 text-[11px] font-medium text-white/40 transition hover:border-white/30 hover:text-white/60"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Add program
                    <span className="ml-1 text-white/25">({programs.length}/5)</span>
                  </button>
                )}
              </div>
            ) : (
              <div>
                <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                  Loyalty program
                </label>
                <Textarea
                  rows={2}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleSubmit();
                  }}
                  placeholder="e.g. Marriott Bonvoy, Hilton Honors, Alaska Airlines MVP…  (⌘+Enter)"
                />
              </div>
            )}

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-medium text-white/30 uppercase tracking-wide">Try:</span>
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => fillExample(ex)}
                  className="rounded-pill border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium text-white/60 transition hover:border-teal/40 hover:bg-teal/10 hover:text-white"
                >
                  {ex}
                </button>
              ))}
              <Button onClick={handleSubmit} disabled={!canSubmit || busy} className="ml-auto">
                {busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : mode === "compare" ? (
                  <GitCompareArrows className="h-3.5 w-3.5" />
                ) : mode === "converse" ? (
                  <MessageCircle className="h-3.5 w-3.5" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                {isChecking ? "Checking…" : detail.cta}
              </Button>
            </div>

            {create.isError && (
              <p className="mt-2 rounded-md bg-red/10 px-3 py-1.5 text-xs text-red border border-red/20">
                {(create.error as Error)?.message ?? "Failed to start run."}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* ── Recent runs ── */}
      <main className="mx-auto w-full max-w-4xl flex-1 px-5 py-8">
        <RecentRunsList />
      </main>

      <footer className="border-t border-line bg-white/60 px-5 py-3 text-center text-[11px] text-ink/30">
        Kobie Loyalty Intelligence · AI-extracted, source-cited competitive data
      </footer>

      {singleModal && (
        <CacheDecisionModal
          open
          programQuery={singleModal.body.user_input}
          result={singleModal.result}
          onDecision={handleSingleDecision}
        />
      )}
      {compareModal && (
        <CompareCacheModal
          open
          results={compareModal.results}
          onDecision={handleCompareDecision}
        />
      )}
    </div>
  );
}
