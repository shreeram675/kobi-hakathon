"use client";

import { useState } from "react";
import {
  Loader2,
  Sparkles,
  GitCompareArrows,
  MessageCircle,
  TrendingUp,
  Shield,
  Zap,
} from "lucide-react";
import { Topbar } from "@/components/Topbar";
import { RunModeTab } from "@/components/RunModeTab";
import { RecentRunsList } from "@/components/RecentRunsList";
import { Button } from "@/components/ui/button";
import { Textarea, Input } from "@/components/ui/textarea";
import { useCreateRun } from "@/lib/hooks";
import type { RunMode } from "@/lib/types";

const EXAMPLES = ["Marriott Bonvoy", "Hilton Honors", "Delta SkyMiles", "World of Hyatt"];

const MODE_DETAIL: Record<RunMode, { title: string; sub: string; cta: string }> = {
  single: {
    title: "Single Program Analysis",
    sub: "Full pipeline: identity resolution → web retrieval → claim extraction → conflict adjudication → analyst brief.",
    cta: "Run analysis",
  },
  compare: {
    title: "Side-by-Side Comparison",
    sub: "Run both programs through the pipeline and surface field-by-field differences with a winner grid.",
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
  const [inputB, setInputB] = useState("");
  const create = useCreateRun();

  const detail = MODE_DETAIL[mode];
  const canSubmit =
    mode === "compare"
      ? input.trim() && inputB.trim()
      : input.trim().length > 0;

  function submit() {
    if (!canSubmit || create.isPending) return;
    create.mutate({
      user_input: input.trim(),
      mode,
      user_input_b: mode === "compare" ? inputB.trim() : undefined,
    });
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Topbar>
        <RunModeTab value={mode} onChange={setMode} />
      </Topbar>

      {/* ── Hero ── */}
      <div className="relative overflow-hidden border-b border-white/8 bg-[#0e1e30] hero-mesh">
        {/* grid overlay */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />

        <div className="relative mx-auto max-w-3xl px-5 py-12 sm:py-16 text-center">
          {/* eyebrow */}
          <div className="inline-flex items-center gap-2 mb-5 rounded-pill border border-white/10 bg-white/5 px-3.5 py-1.5 text-xs font-medium text-white/65 shadow-sm backdrop-blur-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-teal animate-pulse" />
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

          {/* capability chips */}
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
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-teal/80">
                    Program A
                  </label>
                  <Input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="e.g. Marriott Bonvoy"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-blue/80">
                    Program B
                  </label>
                  <Input
                    value={inputB}
                    onChange={(e) => setInputB(e.target.value)}
                    placeholder="e.g. Hilton Honors"
                  />
                </div>
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
                    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit();
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
                  onClick={() =>
                    mode === "compare" && input ? setInputB(ex) : setInput(ex)
                  }
                  className="rounded-pill border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium text-white/60 transition hover:border-teal/40 hover:bg-teal/10 hover:text-white"
                >
                  {ex}
                </button>
              ))}
              <Button
                onClick={submit}
                disabled={!canSubmit || create.isPending}
                className="ml-auto"
              >
                {create.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : mode === "compare" ? (
                  <GitCompareArrows className="h-3.5 w-3.5" />
                ) : mode === "converse" ? (
                  <MessageCircle className="h-3.5 w-3.5" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                {detail.cta}
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

      {/* ── Footer ── */}
      <footer className="border-t border-line bg-white/60 px-5 py-3 text-center text-[11px] text-ink/30">
        Kobie Loyalty Intelligence · AI-extracted, source-cited competitive data
      </footer>
    </div>
  );
}
