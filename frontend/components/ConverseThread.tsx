"use client";

import { Bot, CornerDownLeft, ExternalLink, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/textarea";
import { StatusBadge } from "./badges";
import { useCompareConverse, useConverse } from "@/lib/hooks";
import { cn } from "@/lib/format";
import type { ConverseTurn, ConverseAnswer } from "@/lib/types";

const SINGLE_SUGGESTIONS = [
  "What is the base earn rate?",
  "List the elite tiers",
  "Who are the closest competitors?",
];

const COMPARE_SUGGESTIONS = [
  "Which program has better earn rates?",
  "Compare the tier systems",
  "Which is best for frequent travelers?",
];

/** Chat bubbles + composer for grounded follow-up Q&A (single or comparison runs). */
export function ConverseThread({
  runId,
  conversation,
  disabled,
  compare = false,
  suggestions,
  placeholder,
}: {
  runId: string;
  conversation: ConverseTurn[];
  disabled?: boolean;
  /** When true, sends messages to the comparison-specific endpoint. */
  compare?: boolean;
  suggestions?: string[];
  placeholder?: string;
}) {
  const [message, setMessage] = useState("");
  // Optimistic local turns — used for historical runs where server conversation won't update.
  const [localTurns, setLocalTurns] = useState<ConverseTurn[]>([]);
  const singleConverse = useConverse(runId);
  const compareConverse = useCompareConverse(runId);
  const converse = compare ? compareConverse : singleConverse;
  const effectiveSuggestions = suggestions ?? (compare ? COMPARE_SUGGESTIONS : SINGLE_SUGGESTIONS);
  const effectivePlaceholder = placeholder ?? (compare ? "Ask about the comparison…" : "Ask about this program…");
  const scrollRef = useRef<HTMLDivElement>(null);

  // When the server conversation grows (live run updated), clear local optimistic turns
  // so we don't duplicate messages that the server already persisted.
  const prevServerLen = useRef(conversation.length);
  useEffect(() => {
    if (conversation.length > prevServerLen.current) {
      setLocalTurns([]);
    }
    prevServerLen.current = conversation.length;
  }, [conversation.length]);

  // Combined display: server turns first, then any optimistic local turns
  const displayed: ConverseTurn[] = [...conversation, ...localTurns];

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [displayed.length, converse.isPending]);

  function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || converse.isPending) return;
    setMessage("");

    // Optimistically add the user turn immediately
    const userTurn: ConverseTurn = {
      role: "user",
      message: trimmed,
      created_at: new Date().toISOString(),
    };
    setLocalTurns((prev) => [...prev, userTurn]);

    converse.mutate(trimmed, {
      onSuccess: (answer: ConverseAnswer) => {
        const assistantTurn: ConverseTurn = {
          role: "assistant",
          message: answer.answer,
          answer,
          created_at: new Date().toISOString(),
        };
        setLocalTurns((prev) => [...prev, assistantTurn]);
      },
      onError: () => {
        // Remove the optimistic user turn on failure
        setLocalTurns((prev) => prev.slice(0, -1));
      },
    });
  }

  return (
    <div className="flex h-full flex-col">
      <div
        ref={scrollRef}
        className="max-h-[340px] min-h-[220px] flex-1 space-y-3 overflow-y-auto scroll-thin p-4"
      >
        {displayed.length === 0 && (
          <p className="text-sm text-ink/45">
            Ask a follow-up question — answers are grounded strictly in the
            extracted claims.
          </p>
        )}
        {displayed.map((turn, i) => (
          <Bubble key={i} turn={turn} />
        ))}
        {converse.isPending && (
          <div className="flex items-center gap-2 text-xs text-ink/45">
            <Bot className="h-3.5 w-3.5" />
            <span className="flex gap-1">
              <Dot /> <Dot delay={120} /> <Dot delay={240} />
            </span>
          </div>
        )}
        {converse.isError && (
          <p className="text-xs text-red/70">
            Failed to get a response. Please try again.
          </p>
        )}
      </div>

      {!disabled && displayed.length <= 1 && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-2">
          {effectiveSuggestions.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              className="pill border border-line bg-white text-ink/60 transition hover:border-teal/40 hover:text-teal"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(message);
        }}
        className="flex items-center gap-2 border-t border-line p-3"
      >
        <Input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={disabled ? "Run still processing…" : effectivePlaceholder}
          disabled={disabled || converse.isPending}
        />
        <Button type="submit" size="md" disabled={disabled || !message.trim() || converse.isPending}>
          <CornerDownLeft className="h-4 w-4" />
          Send
        </Button>
      </form>
    </div>
  );
}

function Bubble({ turn }: { turn: ConverseTurn }) {
  const isUser = turn.role === "user";
  return (
    <div className={cn("flex gap-2.5", isUser && "flex-row-reverse")}>
      <span
        className={cn(
          "grid h-7 w-7 shrink-0 place-items-center rounded-full",
          isUser ? "bg-navy text-white" : "bg-teal text-white",
        )}
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </span>
      <div
        className={cn(
          "max-w-[78%] rounded-card px-3 py-2 text-sm",
          isUser
            ? "bg-navy text-white"
            : "border border-line bg-white text-ink",
        )}
      >
        <p className="leading-relaxed whitespace-pre-wrap">{turn.message}</p>
        {turn.answer && (
          <div className="mt-2 space-y-1.5 border-t border-line/60 pt-2">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={turn.answer.status} />
              {turn.answer.cited_claim_ids.length > 0 && (
                <span className="text-[10px] text-ink/45">
                  {turn.answer.cited_claim_ids.length} claim{turn.answer.cited_claim_ids.length === 1 ? "" : "s"} cited
                </span>
              )}
            </div>
            {(turn.answer.source_urls ?? []).length > 0 && (
              <div className="flex flex-col gap-0.5">
                {(turn.answer.source_urls ?? []).map((url) => (
                  <a
                    key={url}
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[10px] text-teal hover:underline truncate max-w-full"
                  >
                    <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                    {url}
                  </a>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Dot({ delay = 0 }: { delay?: number }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 animate-pulse-ring rounded-full bg-ink/40"
      style={{ animationDelay: `${delay}ms` }}
    />
  );
}
