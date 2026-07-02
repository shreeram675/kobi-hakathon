# Kobie — Autonomous Competitive Intelligence Agent

**Kobie AI Hackathon 2026 · Phase 2**

An autonomous research agent that builds evidence-grounded competitive intelligence briefs on loyalty programs. Given a program name (or two, for comparison), it plans searches, scrapes and extracts structured facts, resolves conflicting claims across sources, and produces a cited, narrated brief — with a follow-up chat interface to query the results.

Built by Shreyas R Gowda, Shreeram G Patgar, and Naveen G — R.V. College of Engineering (RVCE), Bengaluru.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Setup](#setup)
- [Running Locally](#running-locally)
- [Docker Deployment](#docker-deployment)
- [API Overview](#api-overview)
- [Project Structure](#project-structure)
- [Sample Workflow](#sample-workflow)
- [Troubleshooting](#troubleshooting)
- [Future Enhancements](#future-enhancements)

---

## Overview

Loyalty program research today means manually reading terms pages, app store reviews, press releases, and forum threads — sources that frequently disagree or go stale. Kobie automates this: it validates the user's request, plans a bounded set of search queries, retrieves and scrapes sources, extracts claims into a canonical schema, adjudicates conflicts between sources, and writes a narrated, cited brief. It never invents facts — every claim is tied to a `source_url` and `access_date`, and unsupported values are marked `not_found` / `manual_review_needed` rather than guessed.

The system supports three modes:

- **Single** — deep-dive research brief on one loyalty program.
- **Compare** — side-by-side comparison of two programs across fixed categories, with a declared winner and rationale.
- **Converse** — follow-up Q&A grounded in the claims already extracted for a run.

## Features

- **Validation-first intake** — an LLM validator checks the user's input is a coherent research request before any search budget is spent, and can ask clarifying questions instead of guessing.
- **Bounded, planned retrieval** — a query generator plans a capped set (≤15) of search queries; results are fetched via Tavily and scraped via Firecrawl.
- **Schema-driven extraction** — page content is chunked, scored, and extracted into a canonical multi-object schema (`program_basics`, `earn_mechanics`, `burn_mechanics`, `tier_system`, `partnerships`, `digital_experience`, `member_sentiment`, `competitive_position`).
- **Conflict adjudication** — when sources disagree on a field, confidence gaps under a threshold trigger a multi-round adversarial debate between models to resolve the discrepancy; every claim keeps its provenance.
- **Volatility-aware confidence scoring** — fields that change often (pricing, promotions) weight recency more heavily; stable fields (program name, structure) weight source authority more heavily.
- **Grounded brief generation** — an executive summary, category-by-category verdicts, differentiators, and persona/strategic profiles are generated from extracted claims only; any source URL not present in the underlying field reports is stripped from the output before it reaches the user.
- **Program comparison** — structured, two-program comparisons with category winners and an overall recommendation.
- **Conversational follow-ups** — ask questions about a completed run and get answers grounded in the stored claims, with citations.
- **Persistent caching** — completed program analyses are cached by normalized program identity so re-running the same program (or comparing against a previously-analyzed one) reuses prior work instead of re-scraping.
- **Run history & cost tracking** — every run is persisted (SQLite) with live status, and per-run/per-program LLM token cost is tracked stage-by-stage.
- **Live pipeline visualization** — the frontend renders the LangGraph pipeline as an interactive node graph, polling run status and streaming stage-by-stage output as it completes.
- **PDF export** — completed briefs and comparisons can be exported to PDF.

## Architecture

Kobie's backend is a [LangGraph](https://github.com/langchain-ai/langgraph) state machine (`pipeline/graph.py`) orchestrating the following stages:

```
User Input
   │
   ▼
Input Validator ──(needs clarification)──► back to user
   │ (resolved)
   ▼
Query Generator  (plans ≤15 search queries)
   │
   ▼
Retrieval (Tavily)  ──►  Firecrawl Scraper  ──►  App Ratings / Wikipedia enrichment
   │
   ▼
Ingest
   ├─ Raw store
   ├─ Semantic chunker
   ├─ Structured extractor (Gemini)
   ├─ Normalizer
   └─ Field report builder
   │
   ▼
Conflict Adjudication
   ├─ auto-resolve if confidence gap > 0.20
   └─ else: adversarial debate (Groq/Llama)
   │
   ▼
Brief Generation (comparison_brief.py) ──► Executive summary, category verdicts,
   │                                        differentiators, personas
   ▼
Converse  (grounded Q&A over stored claims)
```

Each pipeline run's state (`AgentState`) is persisted to SQLite as it progresses, so the frontend can poll a run and render its current stage, partial results, and final brief. Every extracted claim retains its `source_url`, `access_date`, a supporting quote, a confidence score, and a volatility classification — nothing in the final brief is permitted to reference a source that isn't in that trail.

The frontend (Next.js) is a thin client: it calls the FastAPI backend directly for run creation, status polling, clarification, comparison, and converse, and renders the pipeline as a live node graph alongside per-stage detail panels.

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph (Python) |
| Backend API | FastAPI + Uvicorn |
| Legacy/alt UI | Streamlit (`app.py`) |
| Frontend | Next.js 14 (App Router), React 18, TypeScript |
| Styling/UI | Tailwind CSS, Recharts, ReactFlow (pipeline graph), Lucide icons |
| PDF export | `@react-pdf/renderer` |
| Data fetching (frontend) | TanStack Query |
| Search | Tavily |
| Scraping | Firecrawl |
| LLMs | Gemini (extraction, query planning, narration/brief generation), Groq/Llama (input validation, debate, converse) |
| Storage | SQLite (WAL mode) |
| Testing | pytest |

## Prerequisites

- Python 3.10+ (developed against 3.14)
- Node.js 18+ and npm (developed against Node 22)
- `sqlite3` CLI (used by `server.sh` for integrity checks)
- API keys for the providers you intend to use: Gemini, Groq, Tavily, Firecrawl (see [Environment Variables](#environment-variables))

## Installation

```bash
git clone <this-repo>
cd kobi-hakathon

# Python backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend
npm install
cd ..
```

## Environment Variables

Copy the template and fill in the keys you have:

```bash
cp .env.example .env
```

Any stage-specific key left blank falls back to the shared provider key for that stage's provider (`GEMINI_API_KEY` or `GROQ_API_KEY`).

| Variable | Purpose |
|---|---|
| `INPUT_VERIFIER_API_BASE` / `_MODEL` / `_API_KEY` | OpenAI-compatible endpoint used to validate/clarify user input |
| `GEMINI_API_KEY` / `GEMINI_API_BASE` | Shared Gemini credentials (fallback for query gen, extraction, verification, narration) |
| `GROQ_API_KEY` | Shared Groq credentials (fallback for converse, debate) |
| `TAVILY_API_KEY` / `TAVILY_API_BASE` | Search retrieval |
| `FIRECRAWL_API_KEY` / `FIRECRAWL_API_BASE` | Page scraping |
| `QUERY_GENERATOR_API_KEY/_API_BASE/_MODEL/_FALLBACK_MODELS` | Per-stage override for query planning (Gemini) |
| `EXTRACTION_API_KEY/_API_BASE/_MODEL/_FALLBACK_MODELS` | Per-stage override for structured extraction (Gemini) |
| `VERIFICATION_API_KEY/_API_BASE` | Per-stage override for confidence/verification scoring |
| `NARRATION_API_KEY/_API_BASE` | Per-stage override for brief generation |
| `CONVERSE_API_KEY/_MODEL` | Per-stage override for follow-up Q&A (Groq) |
| `DEBATE_API_KEY/_MODEL` | Per-stage override for adversarial conflict debate (Groq) |
| `MAX_FIRECRAWL_URLS` | Cap on URLs scraped per run (default `12`) |
| `MAX_EXTRACTION_CHUNKS` | Cap on chunks sent to extraction (default `30`) |
| `EXTRACTION_BATCH_WORDS` | Words per extraction batch (default `4000`) |
| `MIN_EXTRACTION_CHUNK_SCORE` | Minimum relevance score for a chunk to be extracted (default `2`) |
| `GEMINI_EXTRACTION_CONCURRENCY` | Parallel extraction calls (default `2`) |

Any of the above `*_API_KEY` variables also accept a comma-separated list via a `*_KEYS` (plural) variant (e.g. `NARRATION_API_KEYS`, `TAVILY_API_KEYS`) for round-robin key rotation, which the pipeline uses automatically on rate limits.

The frontend reads `BACKEND_URL` (set in `frontend/.env.local`, not committed) to reach the FastAPI backend from its route handlers.

**Never commit `.env`** — it's already git-ignored.

## Setup

1. Complete [Installation](#installation) and [Environment Variables](#environment-variables) above.
2. The SQLite database (`kobie.sqlite3`) and its schema are created automatically on first backend startup via `core/db.py`'s `migrate()` — no manual migration step is needed.

## Running Locally

The included `server.sh` script manages both the backend and frontend as background processes:

```bash
./server.sh start     # starts backend (port 8000) and frontend (port 3000)
./server.sh stop      # stops both
./server.sh restart   # restart both
```

- Backend: FastAPI via `uvicorn server:app --reload`, at `http://127.0.0.1:8000`
- Frontend: Next.js dev server, at `http://localhost:3000`
- Logs: `logs/backend.log`, `logs/frontend.log`
- PIDs tracked in `.backend.pid` / `.frontend.pid`

On each start, `server.sh` runs `PRAGMA integrity_check` against the SQLite database; if it's corrupted, the existing DB files are moved into `db_corrupted_backup/` and a fresh database is created.

To run either service manually instead:

```bash
# Backend only
source .venv/bin/activate
uvicorn server:app --host 127.0.0.1 --port 8000 --reload

# Frontend only
cd frontend && npm run dev
```

A legacy Streamlit UI also exists at `app.py` (`streamlit run app.py`) from an earlier iteration of the project; the FastAPI + Next.js stack above is the current, actively developed interface.

### Running Tests

```bash
source .venv/bin/activate
pytest
```

Test coverage spans adjudication, debate, the SQLite layer, the Firecrawl scraper, the LangGraph pipeline, input validation, JSON parsing, query generation, retrieval, schemas, and the post-Firecrawl ingest pipeline (`tests/`).

## Docker Deployment

Not currently supported — this project does not include a `Dockerfile` or `docker-compose.yml`. Run the backend and frontend directly as described in [Running Locally](#running-locally).

## API Overview

FastAPI backend (`server.py`), base URL `http://127.0.0.1:8000`:

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/run` | Create a new run (single, compare, or converse mode) |
| `GET` | `/api/run` | List runs |
| `GET` | `/api/run/history` | Run history for the history view |
| `GET` | `/api/run/{run_id}` | Fetch a run's current `AgentState` |
| `DELETE` | `/api/run/{run_id}` | Delete a run |
| `POST` | `/api/run/{run_id}/delete` | Delete a run (alternate method for clients that can't send DELETE) |
| `POST` | `/api/run/{run_id}/clarify` | Answer a clarification question raised by the input validator |
| `POST` | `/api/run/{run_id}/cache-decision` | Accept or reject a cached prior analysis for this program |
| `POST` | `/api/run/{run_id}/converse` | Ask a follow-up question grounded in a single run's claims |
| `POST` | `/api/run/{run_id}/compare/converse` | Ask a follow-up question grounded in a comparison brief |
| `POST` | `/api/run/{run_id}/generate-brief` | Trigger brief/comparison generation for a run |
| `POST` | `/api/run/{run_id}/stop` | Cancel an in-progress run |
| `GET` | `/api/cache/check` | Check whether a cached analysis exists for a program |
| `GET` | `/api/cache/check-multi` | Check cache status for multiple programs at once |

The Next.js frontend proxies these through its own route handlers under `frontend/app/api/**`, reading `BACKEND_URL` to reach the FastAPI service.

## Project Structure

```
kobi-hakathon/
├── server.py               # FastAPI backend, all API routes
├── app.py                  # Legacy Streamlit UI (earlier iteration)
├── server.sh                # Start/stop/restart script for backend + frontend
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
├── core/
│   ├── db.py                 # SQLite connection, schema, migrations, CRUD
│   ├── schemas.py             # Pydantic models (AgentState, FieldReport, etc.)
│   ├── providers.py           # LLM provider clients (Gemini, Groq)
│   └── cost_tracker.py        # Per-run/per-program token cost tracking
├── pipeline/
│   ├── graph.py               # LangGraph orchestration (the pipeline itself)
│   ├── schema_config.py       # Canonical schema field definitions
│   ├── nodes/                 # LangGraph node wrappers (e.g. ingest_node.py)
│   ├── stages/                # Individual pipeline stages (validation, query
│   │                           # generation, retrieval, scraping, extraction,
│   │                           # normalization, comparison_brief, converse, ...)
│   └── adjudication/          # conflict_adjudicator.py, debate_engine.py
├── frontend/                  # Next.js app
│   ├── app/                   # Pages (/, /history, /run/[run_id], /run/[run_id]/compare)
│   │                           # and API route handlers under app/api/**
│   ├── components/            # Pipeline graph, comparison table, PDF docs, etc.
│   └── lib/                   # Types, schema field paths, API client
├── tests/                    # pytest suite
├── docs/                     # Architecture docs, progress notes, arcguide spec
└── kobie.sqlite3              # SQLite database (created on first run, git-ignored)
```

## Sample Workflow

1. Start the app: `./server.sh start`, then open `http://localhost:3000`.
2. Enter a loyalty program name (e.g. "Marriott Bonvoy") and select **Single** mode.
3. If the input needs clarification, the input validator will ask a follow-up question in the UI before any search runs.
4. Watch the live pipeline graph progress through query generation, retrieval, scraping, ingest (chunking → extraction → normalization → field report), and adjudication.
5. Once complete, view the generated brief: executive summary, per-category findings (earn/burn mechanics, tiers, partnerships, digital experience, sentiment, competitive position), each backed by cited sources.
6. Switch to **Converse** on the completed run and ask a follow-up question (e.g. "What's their tier upgrade path?") — the answer is grounded in the claims already extracted, with citations.
7. To compare two programs, start a new run in **Compare** mode with both program names; the result page shows category-by-category winners and an overall recommendation.
8. Export the brief or comparison to PDF from the run view.
9. Previously analyzed programs are cached — re-running or comparing against them will prompt whether to reuse the cached analysis instead of re-scraping.

## Troubleshooting

- **Backend won't start / port 8000 or 3000 already in use** — `server.sh` kills any existing process on those ports before starting; if it still fails, check `logs/backend.log` / `logs/frontend.log` for the actual error.
- **`kobie.sqlite3` looks corrupted / run history missing after a crash** — `server.sh` runs an integrity check on every start and automatically moves a corrupted DB into `db_corrupted_backup/` before recreating it. Note that `kobie.sqlite3-wal` / `-shm` are intentionally git-ignored; if they were ever committed and then reverted, a `git checkout` can silently roll back or truncate committed WAL data — always let SQLite manage those files itself rather than tracking them.
- **LLM calls failing / 401s** — confirm the relevant `*_API_KEY` is set in `.env` and that the process was restarted after editing it (`./server.sh restart`).
- **429 rate limit errors** — the pipeline retries with exponential backoff and rotates through comma-separated `*_KEYS` values automatically; add more keys to the relevant `*_KEYS` variable if you're hitting limits frequently.
- **Brief generation returns empty `category_verdicts`** — this is retried once automatically; if it fails twice, check that the field reports for the run actually have extracted claims (an empty upstream extraction will produce an empty brief).
- **Frontend can't reach the backend** — verify `BACKEND_URL` in `frontend/.env.local` points at the running FastAPI instance (default `http://127.0.0.1:8000`).
- **Tests failing on a fresh clone** — ensure `.venv` is activated and `requirements.txt` is installed; some tests may require API keys to be set for provider-dependent paths.

## Future Enhancements

Per the project's own progress notes (`docs/Kobie_ACI_Agent_Progress.md`), planned/not-yet-started work includes:

- **Temporal ledger** — explicit tracking of how field values change over time across repeated runs, rather than only the latest snapshot.
- **Entailment checking** — an automated check that every sentence in a generated brief is entailed by its cited source claims, beyond the current invented-URL filter.
- **Deeper converse module** — richer multi-turn context and citation quality for the follow-up Q&A mode.
- **Broader source coverage** — additional retrieval/scraping providers beyond Tavily and Firecrawl for higher-volatility fields.
- **Containerized deployment** — a `Dockerfile` / `docker-compose.yml` for one-command setup, replacing the current manual venv + npm install flow.
