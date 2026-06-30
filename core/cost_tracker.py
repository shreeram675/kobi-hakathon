"""Thread-safe API cost ledger for Kobie pipeline runs.

One CostLedger is created per run. The pipeline thread calls set_active_run_id()
at startup so every downstream API call can locate the right ledger via
get_current_ledger() without explicit parameter threading.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

# ── Provider pricing constants ─────────────────────────────────────────────────
# Gemini 2.5 Flash (non-thinking, thinkingBudget=0)
_GEMINI_INPUT_PER_1M = 0.075    # USD per 1M input tokens
_GEMINI_OUTPUT_PER_1M = 0.30    # USD per 1M output tokens

# Groq llama-3.3-70b-versatile
_GROQ_INPUT_PER_1M = 0.59       # USD per 1M input tokens
_GROQ_OUTPUT_PER_1M = 0.79      # USD per 1M output tokens

# Tavily search (credit-based; ~$0.004 per query on standard plan)
_TAVILY_PER_CALL = 0.004

# Firecrawl scrape (~$0.001 per page on standard plan)
_FIRECRAWL_PER_PAGE = 0.001


@dataclass
class LedgerLine:
    provider: str
    stage: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd_cost: float = 0.0


class CostLedger:
    """Thread-safe per-run cost ledger."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._lock = threading.Lock()
        self._lines: dict[str, LedgerLine] = {}

    def _line(self, provider: str, stage: str) -> LedgerLine:
        key = f"{provider}/{stage}"
        if key not in self._lines:
            self._lines[key] = LedgerLine(provider=provider, stage=stage)
        return self._lines[key]

    def record_gemini(self, stage: str, prompt_tokens: int, completion_tokens: int) -> None:
        cost = (
            prompt_tokens * _GEMINI_INPUT_PER_1M / 1_000_000
            + completion_tokens * _GEMINI_OUTPUT_PER_1M / 1_000_000
        )
        with self._lock:
            ln = self._line("gemini", stage)
            ln.calls += 1
            ln.prompt_tokens += prompt_tokens
            ln.completion_tokens += completion_tokens
            ln.usd_cost += cost

    def record_groq(self, stage: str, prompt_tokens: int, completion_tokens: int) -> None:
        cost = (
            prompt_tokens * _GROQ_INPUT_PER_1M / 1_000_000
            + completion_tokens * _GROQ_OUTPUT_PER_1M / 1_000_000
        )
        with self._lock:
            ln = self._line("groq", stage)
            ln.calls += 1
            ln.prompt_tokens += prompt_tokens
            ln.completion_tokens += completion_tokens
            ln.usd_cost += cost

    def record_tavily(self, calls: int = 1) -> None:
        cost = calls * _TAVILY_PER_CALL
        with self._lock:
            ln = self._line("tavily", "retrieval")
            ln.calls += calls
            ln.usd_cost += cost

    def record_firecrawl(self, pages: int = 1) -> None:
        cost = pages * _FIRECRAWL_PER_PAGE
        with self._lock:
            ln = self._line("firecrawl", "firecrawl_scraper")
            ln.calls += pages
            ln.usd_cost += cost

    def snapshot(self) -> dict[str, LedgerLine]:
        """Return a point-in-time copy of the current per-line totals.

        Pass the result to to_dict(since=...) to compute only the cost
        accrued after the snapshot was taken (e.g. for one program's
        share of a shared run-wide ledger in compare mode).
        """
        with self._lock:
            return {k: LedgerLine(**vars(ln)) for k, ln in self._lines.items()}

    def to_dict(self, since: dict[str, "LedgerLine"] | None = None) -> dict[str, Any]:
        baseline = since or {}
        with self._lock:
            lines = []
            for key, ln in self._lines.items():
                base = baseline.get(key)
                calls = ln.calls - (base.calls if base else 0)
                prompt_tokens = ln.prompt_tokens - (base.prompt_tokens if base else 0)
                completion_tokens = ln.completion_tokens - (base.completion_tokens if base else 0)
                usd_cost = ln.usd_cost - (base.usd_cost if base else 0.0)
                if calls <= 0 and usd_cost <= 0 and prompt_tokens <= 0 and completion_tokens <= 0:
                    continue
                lines.append({
                    "provider": ln.provider,
                    "stage": ln.stage,
                    "calls": calls,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "usd_cost": round(usd_cost, 6),
                })
            lines.sort(key=lambda r: (r["provider"], r["stage"]))

            total_cost = sum(r["usd_cost"] for r in lines)
            total_calls = sum(r["calls"] for r in lines)
            total_prompt = sum(r["prompt_tokens"] for r in lines)
            total_completion = sum(r["completion_tokens"] for r in lines)

        return {
            "lines": lines,
            "total_calls": total_calls,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_usd_cost": round(total_cost, 6),
        }


# ── Global registry keyed by run_id ───────────────────────────────────────────
_LEDGERS: dict[str, CostLedger] = {}
_LEDGERS_LOCK = threading.Lock()

# Thread-local storage so each pipeline thread knows its run_id without
# passing it through every call frame.
_thread_local = threading.local()


def create_ledger(run_id: str) -> CostLedger:
    ledger = CostLedger(run_id)
    with _LEDGERS_LOCK:
        _LEDGERS[run_id] = ledger
    return ledger


def get_ledger(run_id: str) -> CostLedger | None:
    with _LEDGERS_LOCK:
        return _LEDGERS.get(run_id)


def set_active_run_id(run_id: str) -> None:
    """Call once at the start of each pipeline thread."""
    _thread_local.run_id = run_id


def get_current_ledger() -> CostLedger | None:
    """Return the ledger for the currently active run (thread-local lookup)."""
    run_id = getattr(_thread_local, "run_id", None)
    if run_id is None:
        return None
    return get_ledger(run_id)
