"use client";

import { useState } from "react";
import { ArrowRight, Loader2, Sparkles } from "lucide-react";
import { Topbar } from "@/components/Topbar";
import { RunModeTab } from "@/components/RunModeTab";
import { RecentRunsList } from "@/components/RecentRunsList";
import { Button } from "@/components/ui/button";
import { Textarea, Input } from "@/components/ui/textarea";
import { useCreateRun } from "@/lib/hooks";
import type { RunMode } from "@/lib/types";

const EXAMPLES = ["Marriott Bonvoy", "Hilton Honors", "Delta SkyMiles"];

const MODE_COPY: Record<RunMode, { title: string; sub: string; cta: string }> = {
  single: {
    title: "Analyse one loyalty program",
    sub: "Resolve a program identity and build a fully-sourced intelligence brief.",
    cta: "Run analysis",
  },
  compare: {
    title: "Compare two loyalty programs",
    sub: "Run both through the pipeline and surface field-by-field differences.",
    cta: "Run comparison",
  },
  converse: {
    title: "Converse with extracted claims",
    sub: "Analyse a program, then ask grounded follow-up questions.",
    cta: "Analyse & open chat",
  },
};

export default function HomePage() {
  const [mode, setMode] = useState<RunMode>("single");
  const [input, setInput] = useState("");
  const [inputB, setInputB] = useState("");
  const create = useCreateRun();

  const copy = MODE_COPY[mode];
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
    <div className="min-h-screen">
      <Topbar>
        <RunModeTab value={mode} onChange={setMode} />
      </Topbar>

      {/* hero */}
      <div className="relative overflow-hidden border-b border-line bg-navy">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.5]"
          style={{
            background:
              "radial-gradient(60% 120% at 15% 0%, rgba(15,124,125,0.45) 0%, transparent 55%), radial-gradient(50% 100% at 100% 100%, rgba(31,101,183,0.35) 0%, transparent 60%)",
          }}
        />
        <div className="relative mx-auto max-w-3xl px-4 py-10 text-center sm:px-5 sm:py-14">
          <span className="pill mx-auto mb-4 w-fit border border-white/15 bg-white/5 text-white/70">
            <Sparkles className="h-3.5 w-3.5 text-teal" />
            Grounded loyalty intelligence
          </span>
          <h1 className="text-balance text-3xl font-semibold tracking-tight text-white sm:text-4xl">
            {copy.title}
          </h1>
          <p className="mx-auto mt-3 max-w-xl text-sm text-white/60">{copy.sub}</p>

          <div className="mx-auto mt-7 max-w-2xl rounded-card border border-white/10 bg-white/[0.04] p-4 text-left shadow-panel-lg backdrop-blur">
            {mode === "compare" ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <Input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Program A — e.g. Marriott Bonvoy"
                />
                <Input
                  value={inputB}
                  onChange={(e) => setInputB(e.target.value)}
                  placeholder="Program B — e.g. Hilton Honors"
                />
              </div>
            ) : (
              <Textarea
                rows={3}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit();
                }}
                placeholder={
                  mode === "converse"
                    ? "Which program should I analyse so you can ask about it?"
                    : "Describe the loyalty program to analyse… (⌘+Enter to run)"
                }
              />
            )}

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-xs text-white/40">Try:</span>
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() =>
                    mode === "compare" && input
                      ? setInputB(ex)
                      : setInput(ex)
                  }
                  className="pill border border-white/10 bg-white/5 text-white/70 transition hover:border-teal/50 hover:text-white"
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
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ArrowRight className="h-4 w-4" />
                )}
                {copy.cta}
              </Button>
            </div>
            {create.isError && (
              <p className="mt-2 text-xs text-red">
                {(create.error as Error)?.message ?? "Failed to start run."}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* recent runs */}
      <main className="mx-auto max-w-3xl px-5 py-10">
        <RecentRunsList />
      </main>
    </div>
  );
}
