import type {
  AgentState,
  CacheCheckResult,
  CompareCacheCheckItem,
  ConverseAnswer,
  CreateRunBody,
  CreateRunResponse,
  RunHistoryEntry,
  RunSummary,
} from "./types";

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}

export async function createRun(body: CreateRunBody): Promise<CreateRunResponse> {
  const res = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return asJson<CreateRunResponse>(res);
}

export async function fetchRun(runId: string): Promise<AgentState> {
  const res = await fetch(`/api/run/${runId}`, { cache: "no-store" });
  return asJson<AgentState>(res);
}

export async function fetchRuns(): Promise<RunSummary[]> {
  const res = await fetch("/api/run", { cache: "no-store" });
  return asJson<RunSummary[]>(res);
}

export async function fetchRunHistory(): Promise<RunHistoryEntry[]> {
  const res = await fetch("/api/run/history", { cache: "no-store" });
  return asJson<RunHistoryEntry[]>(res);
}


export async function postConverse(
  runId: string,
  message: string,
): Promise<ConverseAnswer> {
  const res = await fetch(`/api/run/${runId}/converse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return asJson<ConverseAnswer>(res);
}

export async function postCompareConverse(
  runId: string,
  message: string,
): Promise<ConverseAnswer> {
  const res = await fetch(`/api/run/${runId}/compare/converse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return asJson<ConverseAnswer>(res);
}

export async function stopRun(runId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`/api/run/${runId}/stop`, { method: "POST" });
  return asJson<{ ok: boolean }>(res);
}

export async function deleteRun(runId: string): Promise<{ ok: boolean; deleted: boolean }> {
  const res = await fetch(`/api/run/${runId}/delete`, { method: "POST" });
  return asJson<{ ok: boolean; deleted: boolean }>(res);
}

export async function generateComparisonBrief(runId: string): Promise<import("./types").ComparisonBrief> {
  const res = await fetch(`/api/run/${runId}/generate-brief`, { method: "POST" });
  return asJson(res);
}

export async function postClarify(
  runId: string,
  answer: string,
): Promise<{ ok: boolean }> {
  const res = await fetch(`/api/run/${runId}/clarify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  return asJson<{ ok: boolean }>(res);
}

export async function postCacheDecision(
  runId: string,
  decision: "use_cache" | "fresh",
): Promise<{ ok: boolean }> {
  const res = await fetch(`/api/run/${runId}/cache-decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  return asJson<{ ok: boolean }>(res);
}
