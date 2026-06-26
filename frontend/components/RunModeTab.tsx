"use client";

import { GitCompareArrows, Sparkles } from "lucide-react";
import { cn } from "@/lib/format";
import type { RunMode } from "@/lib/types";

const MODES: { id: RunMode; label: string; icon: typeof Sparkles }[] = [
  { id: "single", label: "Single", icon: Sparkles },
  { id: "compare", label: "Compare", icon: GitCompareArrows },
];

/** Single / Compare / Converse switcher (glass pill group for the dark topbar). */
export function RunModeTab({
  value,
  onChange,
}: {
  value: RunMode;
  onChange: (mode: RunMode) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Run mode"
      className="inline-flex items-center gap-1 rounded-pill border border-white/10 bg-white/5 p-1"
    >
      {MODES.map(({ id, label, icon: Icon }) => {
        const active = value === id;
        return (
          <button
            key={id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(id)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-pill px-3 py-1.5 text-xs font-medium transition-all",
              active
                ? id === "single"
                  ? "bg-[#F47920] text-white shadow-sm shadow-[#F47920]/30"
                  : "bg-[#1a3a5c] text-white shadow-sm shadow-[#1a3a5c]/30"
                : "text-white/60 hover:bg-white/10 hover:text-white",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        );
      })}
    </div>
  );
}
