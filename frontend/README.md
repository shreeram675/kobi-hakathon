# Kobie AI — Frontend

React + TypeScript frontend for the Kobie Loyalty Intelligence platform.
Next.js 14 (App Router) · Tailwind CSS · Recharts · ReactFlow · TanStack Query.

It visualises the Python/LangGraph pipeline's `AgentState` across three run modes —
**single**, **compare**, and **converse** — surfacing every field of the state
(not just the final brief).

## Run it

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
# or: npm run build && npm start
npm run typecheck  # tsc --noEmit
```

## Pages

| Route | What |
|---|---|
| `/` | Query entry. Run-mode tabs, hero input, recent-runs history. |
| `/run/[run_id]` | Live run. Left 40% = ReactFlow pipeline graph; right 60% = per-stage detail + final output. Polls every 2s until `done`. |
| `/run/[run_id]/compare` | Side-by-side comparison table, quality deltas, category winners, recommendation, debate. |

## Data layer / API contract

The frontend talks to the contract from the brief:

- `POST /api/run` `{ user_input, mode, user_input_b? }` → `{ run_id }`
- `GET  /api/run/{run_id}` → `AgentState` (polled every 2s while not done/error)
- `POST /api/run/{run_id}/converse` `{ message }` → `ConverseAnswer`
- `GET  /api/run` → `RunSummary[]` (recent runs)

Because the real backend is Streamlit (not a REST service), these routes are
implemented as **Next.js route handlers backed by an in-memory pipeline
simulator** ([lib/mock/engine.ts](lib/mock/engine.ts), [lib/mock/data.ts](lib/mock/data.ts)).
A run is built once (schema-faithfully) and then *revealed stage-by-stage* on
each poll based on elapsed time — so the live graph animates exactly as the real
backend would stream.

**To wire the real backend:** point the fetchers in [lib/api.ts](lib/api.ts) at
the Python service (or proxy `/api/*`), and delete `lib/mock` + `app/api`. The
types in [lib/types.ts](lib/types.ts) already mirror `schemas.py`.

## Key files

- [lib/types.ts](lib/types.ts) — strongly-typed mirror of `schemas.py` (`AgentState` + all models).
- [lib/schema.ts](lib/schema.ts) — `SCHEMA_FIELD_PATHS` (59), categories, `HIGH_VOLATILITY_FIELDS` (9), the 9 UI pipeline stages.
- [lib/colors.ts](lib/colors.ts) — design tokens + status/outcome → colour maps.
- [components/](components/) — 28 components from the brief (PipelineGraph, SchemaFieldTable, ComparisonTable, DebateTimeline, charts, badges, …).

## Notes on fidelity to the brief

- The brief says "57 fields"; the actual `schemas.py` `SCHEMA_FIELD_PATHS` has
  **59** (competitive_position has 6). The code follows the backend and derives
  `total_fields` from the array, so it stays correct regardless.
- The 7 backend LangGraph nodes (`input_validator → query_generator → retrieval →
  firecrawl_scraper → ingest → adjudication → narration`) are presented as the
  **9 UI stages** from the brief (ingest split into Chunking/Extraction/Claims,
  narration → Output).
- The pipeline graph is laid out **top-to-bottom** (not left-to-right) to fit the
  40% side panel legibly; edges still animate while a stage is active.
