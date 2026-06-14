"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createRun, fetchRun, fetchRuns, postConverse, postClarify } from "./api";
import type { CreateRunBody } from "./types";

/** Poll the run state every 2s while the run is still in progress. */
export function useRun(runId: string) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => fetchRun(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "error" ? false : 2000;
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

export function useConverse(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (message: string) => postConverse(runId, message),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["run", runId] });
    },
  });
}
