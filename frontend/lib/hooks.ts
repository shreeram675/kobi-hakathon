"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  createRun,
  fetchRun,
  fetchRunHistory,
  fetchRuns,
  generateComparisonBrief,
  postCompareConverse,
  postConverse,
  postClarify,
  stopRun,
} from "./api";
import type { CreateRunBody } from "./types";
import { upsertRecentSearch } from "./cache-storage";

const TERMINAL_STATUSES = new Set(["done", "error", "cancelled"]);

/** Poll the run state every 2s while the run is still in progress. */
export function useRun(runId: string) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => fetchRun(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL_STATUSES.has(status) ? false : 2000;
    },
    refetchIntervalInBackground: true,
  });
}

export function useClarify(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (answer: string) => postClarify(runId, answer),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["run", runId] });
    },
  });
}

export function useRuns() {
  return useQuery({
    queryKey: ["runs"],
    queryFn: fetchRuns,
    refetchInterval: 4000,
  });
}

/** Server-persisted run history (SQLite + live). Survives server restarts. */
export function useRunHistory() {
  return useQuery({
    queryKey: ["run-history"],
    queryFn: fetchRunHistory,
    refetchInterval: 5000,
    retry: 1,
    staleTime: 2000,
  });
}

export function useCreateRun() {
  const router = useRouter();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateRunBody) => createRun(body),
    onSuccess: (data, variables) => {
      upsertRecentSearch({
        run_id: data.run_id,
        user_input: variables.user_input,
        mode: variables.mode,
        programs: variables.programs,
        created_at: new Date().toISOString(),
        status: "running",
      });
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["run-history"] });
      router.push(`/run/${data.run_id}`);
    },
  });
}

export function useStopRun(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => stopRun(runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["run", runId] });
      qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

export function useRetryRun() {
  const router = useRouter();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateRunBody) => createRun(body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      router.push(`/run/${data.run_id}`);
    },
  });
}

export function useConverse(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (message: string) => postConverse(runId, message),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["run", runId] });
    },
  });
}

export function useCompareConverse(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (message: string) => postCompareConverse(runId, message),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["run", runId] });
    },
  });
}

export function useGenerateBrief(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => generateComparisonBrief(runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["run", runId] });
    },
  });
}
