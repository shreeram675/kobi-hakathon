"use client";

import { useState } from "react";
import { Send, HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useClarify } from "@/lib/hooks";
import type { ClarificationOption, ValidationResult } from "@/lib/types";

interface Props {
  runId: string;
  validationResult: ValidationResult;
}

export function ClarificationPanel({ runId, validationResult }: Props) {
  const [answer, setAnswer] = useState("");
  const clarify = useClarify(runId);

  const { follow_up_questions, possible_matches } = validationResult;

  function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || clarify.isPending) return;
    clarify.mutate(trimmed, { onSuccess: () => setAnswer("") });
  }

  function selectMatch(match: ClarificationOption) {
    submit(match.program_name);
  }

  return (
    <div className="rounded-card border border-teal/30 bg-teal/5 p-5 shadow-panel">
      <div className="mb-4 flex items-center gap-2">
        <HelpCircle className="h-4 w-4 text-teal" />
        <h3 className="text-sm font-semibold text-navy">Clarification needed</h3>
      </div>

      {follow_up_questions.length > 0 && (
        <div className="mb-4 space-y-1">
          {follow_up_questions.map((q, i) => (
            <p key={i} className="text-sm text-ink">
              {q}
            </p>
          ))}
        </div>
      )}

      {possible_matches.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-xs font-medium text-ink/50">Select a program:</p>
          <div className="flex flex-wrap gap-2">
            {possible_matches.map((match) => (
              <button
                key={match.program_name}
                onClick={() => selectMatch(match)}
                disabled={clarify.isPending}
                className="rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-navy shadow-sm transition hover:border-teal hover:bg-teal/5 hover:text-teal disabled:opacity-50"
              >
                {match.program_name}
                <span className="ml-1 text-ink/40">· {match.domain}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit(answer);
          }}
          placeholder="Or type your answer…"
          disabled={clarify.isPending}
          className="flex-1 rounded-card border border-line bg-white px-3 py-2 text-sm text-ink placeholder:text-ink/35 focus:border-teal focus:outline-none disabled:opacity-50"
        />
        <Button
          size="sm"
          onClick={() => submit(answer)}
          disabled={!answer.trim() || clarify.isPending}
        >
          <Send className="h-3.5 w-3.5" />
          Send
        </Button>
      </div>

      {clarify.isError && (
        <p className="mt-2 text-xs text-red">
          {(clarify.error as Error)?.message ?? "Failed to send answer."}
        </p>
      )}
    </div>
  );
}
