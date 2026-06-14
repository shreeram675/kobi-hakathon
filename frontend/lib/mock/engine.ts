/**
 * In-memory run store + progressive pipeline simulator.
 *
 * Replaces the Python/LangGraph backend for local demos. Each run is built once
 * (fully) and then "revealed" stage-by-stage on each poll based on wall-clock
 * elapsed time, so GET /api/run/{id} shows live progress exactly as the real
 * backend would stream it.
 */

import { STAGE_IDS, type StageId } from "../schema";
import type {
  AgentState,
  ConverseAnswer,
  ConverseTurn,
  CreateRunBody,
  RunSummary,
  StageStatus,
} from "../types";
import {
  buildComparison,
  buildFullState,
  pickProfile,
  pickSecondProfile,
} from "./data";

interface RunRecord {
  full: AgentState;
  startedAt: number;
  /** stageId -> seconds-from-start at which that stage completes */
  schedule: Record<StageId, number>;
  conversation: ConverseTurn[];
}

// survive Next.js dev HMR by hanging the store off globalThis
const STORE: Map<string, RunRecord> =
  (globalThis as any).__kobie_runs__ ?? new Map<string, RunRecord>();
(globalThis as any).__kobie_runs__ = STORE;

const STAGE_DURATIONS: Record<StageId, number> = {
  input_validator: 1.6,
  query_generator: 2.0,
  retrieval: 2.6,
  firecrawl_scraper: 3.0,
  chunking: 1.8,
  extraction: 3.2,
  claims: 1.8,
  adjudication: 2.4,
  output: 1.6,
};

function buildSchedule(): Record<StageId, number> {
  let acc = 0;
  const schedule = {} as Record<StageId, number>;
  for (const id of STAGE_IDS) {
    acc += STAGE_DURATIONS[id];
    schedule[id] = acc;
  }
  return schedule;
}

/** Keys each UI stage is responsible for producing in the AgentState. */
const STAGE_KEYS: Record<StageId, (keyof AgentState)[]> = {
  input_validator: [
    "validation_result",
    "validation_messages",
    "program_identity",
    "program_name",
    "brand",
    "domain",
    "country_or_region",
  ],
  query_generator: ["query_generation_result", "search_queries"],
  retrieval: ["retrieval_result", "retrieved_urls"],
  firecrawl_scraper: ["firecrawl_result", "scraped_blocks"],
  chunking: ["raw_documents", "semantic_chunks", "extraction_chunks", "skipped_chunks"],
  extraction: ["extracted_packets", "normalized_packets", "field_report"],
  claims: ["extracted_claims", "conflicts"],
  adjudication: ["adjudicated", "human_review_queue", "adjudicated_claims"],
  output: ["schema_coverage", "data_quality", "final_brief", "comparison_output", "conversation_answer"],
};

const EMPTY_FOR_KEY: Partial<Record<keyof AgentState, unknown>> = {
  validation_result: null,
  validation_messages: [],
  program_identity: null,
  program_name: null,
  brand: null,
  domain: null,
  country_or_region: null,
  query_generation_result: null,
  search_queries: [],
  retrieval_result: null,
  retrieved_urls: [],
  firecrawl_result: null,
  scraped_blocks: [],
  raw_documents: [],
  semantic_chunks: [],
  extraction_chunks: [],
  skipped_chunks: [],
  extracted_packets: [],
  normalized_packets: [],
  field_report: null,
  extracted_claims: [],
  conflicts: [],
  adjudicated: [],
  human_review_queue: [],
  adjudicated_claims: [],
  final_brief: null,
  comparison_output: null,
  conversation_answer: null,
};

function emptyCoverage(total: number) {
  return {
    total_fields: total,
    supported_fields: 0,
    manual_review_fields: 0,
    null_fields: 0,
    rejected_fields: 0,
  };
}

/** Project the full state to the moment `elapsedSec` into the run. */
function project(record: RunRecord, elapsedSec: number): AgentState {
  const { full, schedule } = record;
  const view: AgentState = structuredClone(full);

  const stageStatus: Record<string, StageStatus> = {};
  let activeStage: string | null = null;
  let prevDone = true;

  for (const id of STAGE_IDS) {
    const completeAt = schedule[id];
    const startAt = completeAt - STAGE_DURATIONS[id];
    let status: StageStatus;
    if (elapsedSec >= completeAt) {
      status = "done";
    } else if (prevDone && elapsedSec >= startAt) {
      status = "running";
      activeStage = id;
    } else {
      status = "idle";
    }
    stageStatus[id] = status;
    prevDone = status === "done";

    // strip data for stages that haven't completed yet
    if (status !== "done") {
      for (const key of STAGE_KEYS[id]) {
        if (key === "schema_coverage") {
          (view as any)[key] = emptyCoverage(full.schema_coverage.total_fields);
        } else if (key === "data_quality") {
          view.data_quality = 0;
        } else if (key in EMPTY_FOR_KEY) {
          (view as any)[key] = structuredClone(EMPTY_FOR_KEY[key]);
        }
      }
    }
  }

  // errors only surface once their producing stage has run
  if (stageStatus["firecrawl_scraper"] !== "done") {
    view.errors = [];
  }

  const allDone = STAGE_IDS.every((id) => stageStatus[id] === "done");
  view.stage_status = stageStatus;
  view.active_stage = activeStage;
  view.status = allDone ? "done" : "running";
  view.updated_at = new Date(record.startedAt + elapsedSec * 1000).toISOString();
  view.conversation = record.conversation;

  // compare overlay: attach B only once output stage is done
  if (full.compare_b) {
    if (stageStatus["output"] === "done") {
      view.compare_b = full.compare_b;
    } else {
      view.compare_b = null;
    }
  }
  return view;
}

export function createRun(body: CreateRunBody): string {
  const mode = body.mode;
  const createdAt = new Date().toISOString();
  const profileA = pickProfile(body.user_input);
  const runId = `run_${cryptoId()}`;

  let full: AgentState;
  if (mode === "compare") {
    const profileB = pickSecondProfile(profileA, body.user_input_b ?? body.user_input);
    const stateA = buildFullState(runId, body.user_input, "compare", profileA, createdAt);
    const stateB = buildFullState(
      `${runId}_b`,
      body.user_input_b ?? profileB.program_name,
      "compare",
      profileB,
      createdAt,
    );
    stateB.status = "done";
    stateB.stage_status = Object.fromEntries(STAGE_IDS.map((id) => [id, "done"]));
    stateB.active_stage = null;
    const comparison = buildComparison(runId, stateA, stateB);
    full = { ...stateA, comparison_output: comparison, compare_b: stateB };
  } else {
    full = buildFullState(runId, body.user_input, mode, profileA, createdAt);
  }

  const record: RunRecord = {
    full,
    startedAt: Date.now(),
    schedule: buildSchedule(),
    conversation:
      mode === "converse"
        ? [
            {
              role: "assistant",
              message: `I've analysed ${profileA.program_name}. Ask me anything about its earn rates, tiers, partners, or member sentiment — I'll answer only from the extracted claims.`,
              created_at: createdAt,
            },
          ]
        : [],
  };
  STORE.set(runId, record);
  return runId;
}

export function getRun(runId: string): AgentState | null {
  const record = STORE.get(runId);
  if (!record) return null;
  const elapsedSec = (Date.now() - record.startedAt) / 1000;
  return project(record, elapsedSec);
}

export function listRuns(): RunSummary[] {
  return Array.from(STORE.entries())
    .sort((a, b) => b[1].startedAt - a[1].startedAt)
    .map(([runId, record]) => {
      const elapsedSec = (Date.now() - record.startedAt) / 1000;
      const view = project(record, elapsedSec);
      return {
        run_id: runId,
        user_input: record.full.user_input,
        mode: record.full.mode,
        data_quality: view.data_quality,
        status: view.status,
        created_at: record.full.created_at,
      };
    });
}

export function converse(runId: string, message: string): ConverseAnswer | null {
  const record = STORE.get(runId);
  if (!record) return null;
  const claims = record.full.extracted_claims;
  const lower = message.toLowerCase();

  // naive grounded lookup: find a claim whose field path/leaf appears in the question
  const matched = claims.find((c) => {
    const leaf = c.field_path.split(".")[1]?.replace(/_/g, " ") ?? "";
    return leaf && lower.includes(leaf.split(" ")[0]) && c.status === "supported";
  });

  let answer: ConverseAnswer;
  if (matched) {
    const value = Array.isArray(matched.value_json)
      ? (matched.value_json as unknown[]).join(", ")
      : String(matched.value_json ?? "—");
    answer = {
      answer: `${record.full.program_name}: ${value}. (Source-grounded, confidence ${(matched.confidence * 100).toFixed(0)}%.)`,
      status: "supported",
      cited_claim_ids: [matched.claim_id],
      missing_field_paths: [],
    };
  } else {
    answer = {
      answer: `I don't have a source-grounded claim that answers that for ${record.full.program_name}. This may not have been retrieved during the run.`,
      status: "not_found/manual_review_needed",
      cited_claim_ids: [],
      missing_field_paths: [],
    };
  }

  const now = new Date().toISOString();
  record.conversation.push({ role: "user", message, created_at: now });
  record.conversation.push({ role: "assistant", message: answer.answer, answer, created_at: now });
  record.full.conversation_answer = answer;
  return answer;
}

function cryptoId(): string {
  try {
    return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  } catch {
    return Math.random().toString(16).slice(2, 18);
  }
}
