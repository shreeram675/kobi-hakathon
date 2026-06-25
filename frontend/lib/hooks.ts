"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createRun, fetchRun, fetchRuns, postCompareConverse, postConverse, postClarify, stopRun } from "./api";
import type { CreateRunBody } from "./types";

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

export function useCreateRun() {
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
