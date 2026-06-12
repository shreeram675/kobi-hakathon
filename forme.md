# Kobie Project Architecture

## Purpose
Kobie is a loyalty-program competitive intelligence agent. It validates a user-provided program name, generates targeted search queries, retrieves candidate URLs, scrapes the resulting pages/PDFs, extracts structured loyalty-program facts, normalizes them, and stores them in SQLite.

The project is built as a pipeline with a validation-first workflow. The root `arcguide` file is treated as the reference documentation and prompt guide for schema design and stage behavior.

## High-Level Flow

1. User input enters the system.
2. `validation.py` resolves the input to a single canonical loyalty program identity.
3. `query_generator.py` generates a set of high-value Tavily search queries.
4. `retrieval.py` sends those queries to Tavily and deduplicates the returned URLs.
5. `firecrawl_scraper.py` scrapes the deduplicated URLs into raw text/markdown.
6. `pipeline.nodes.ingest_node.py` stores raw content, chunks it, extracts structured schema facts, normalizes them, and persists normalized packets to SQLite.

The Streamlit UI in `app.py` runs this workflow and shows node status, results, and compare mode.

---

## Main Files and Their Responsibilities

### `app.py`
- Builds the Streamlit web interface.
- Displays workflow status, metrics, and inspection panels.
- Runs validation and compare flows with `graph.py`.
- Handles session state for live UI updates.

### `graph.py`
- Defines the LangGraph-style pipeline graph.
- Wires nodes together in linear order: `input_validator` → `query_generator` → `retrieval` → `firecrawl_scraper` → `ingest`.
- Implements node wrappers to catch exceptions and report pipeline errors.
- Provides helper entry points such as `run_single`, `run_validation_chat`, and `run_validation_chat_traced`.
- Controls Firecrawl spend via `select_urls_for_firecrawl`.

### `providers.py`
- Central provider configuration for external API stages.
- Loads environment variables with `dotenv`.
- Defines provider configs for validation, query generation, Tavily, Firecrawl, extraction, verification, narration, and converse stages.
- Ensures clients can read API base URLs, keys, and resolved model names from env vars.

### `schemas.py`
- Defines all shared data models used across the project.
- Includes `ProgramIdentity`, `ValidationResult`, `SearchQuery`, `RetrievedUrl`, `FirecrawlScrapeOutput`, `RawDocument`, `SemanticChunk`, `ExtractedField`, `ExtractedObjectPacket`, `NormalizedObjectPacket`, `Claim`, `ConflictRecord`, and more.
- Stores the ArcGuide field path list and volatility metadata.
- Enforces schema validation rules using Pydantic.

### `db.py`
- Implements SQLite persistence.
- Creates tables for runs, program identities, sources, pages, chunks, claims, conflicts, briefs, conversations, raw documents, and normalized packets.
- Provides safe connection setup with WAL mode and busy timeout.
- Contains upsert and insert helper functions for run state, identities, raw docs, and normalized packets.

---

## Validation Stage

### `validation.py`
- Performs LLM-backed input validation and canonical program resolution.
- Sends user input to a chat provider with a strict system prompt.
- Parses the LLM JSON response into `ValidationResult`.
- Handles three outcomes:
  - `resolved` with a canonical `ProgramIdentity`
  - `needs_clarification`
  - `rejected`
- Uses `provider_for_stage("validation")` to configure the LLM client.
- Validates confidence and rejects synthetic or unknown program names.

### `INPUT_VERIFIER_SYSTEM_PROMPT`
- Encodes loyalty-program discovery rules, ambiguity handling, confidence rules, and valid JSON output expectations.

---

## Query Generation Stage

### `query_generator.py`
- Generates search queries for Tavily using Gemini.
- Accepts a resolved `ProgramIdentity` as input.
- Produces a `QueryGenerationOutput` containing:
  - `queries`
  - `field_query_map`
  - `priority_fields`
  - `detected_category`
  - `resolved_corporate_parent`
  - `estimated_web_coverage`
- Uses a strict system prompt with query planning and coverage rules.
- Validates query count, maximum words, and required coverage vectors.
- Uses `provider_for_stage("query_generator")` and environment config for Gemini.

---

## Retrieval Stage

### `retrieval.py`
- Uses Tavily search to retrieve candidate URLs for each generated query.
- Sends each `SearchQuery.query` to Tavily and returns raw results.
- Canonicalizes URLs by normalizing scheme, host, path, and removing tracking params.
- Deduplicates URLs by canonical URL and keeps the highest-scoring candidate.
- Returns `RetrievalOutput` with counts and unique URL list.

---

## Scraping Stage

### `firecrawl_scraper.py`
- Scrapes the deduplicated URLs with Firecrawl.
- Supports markdown and PDF content parsing.
- Produces `ScrapedUrlBlock` records with content, status, and error handling.
- Converts Firecrawl payloads into normalized content forms.
- Yearns to preserve evidence from HTML/PDF pages for downstream extraction.

---

## Ingestion Stage

### `pipeline/nodes/ingest_node.py`
- Central post-Firecrawl ingestion node.
- Pipeline steps:
  1. Store Firecrawl output as raw documents.
  2. Split raw documents into semantic chunks.
  3. Select informative chunks for extraction.
  4. Extract structured objects from chunks.
  5. Normalize extracted packets.
  6. Persist normalized packets to SQLite.
- Uses `AgentState` to read workflow state and attach outputs.
- Manages schema config resolution and alias matching.

### `pipeline/stages/raw_store.py`
- Saves raw scraped content to SQLite.
- Filters out short content under 100 words.
- Associates each raw document with query metadata and source authority.
- Produces `RawDocument` records for later chunking.

### `pipeline/stages/chunker.py`
- Splits raw markdown into evidence-sized `SemanticChunk` units.
- Uses heading-based segmentation and section word count thresholds.
- Limits chunk size to 1500 words.
- Propagates target field hints from query metadata into chunk records.

### `pipeline/stages/extractor.py`
- Runtime-schema extraction engine.
- Schema-agnostic: input schema and field definitions are supplied at runtime.
- Two-phase extraction:
  1. Detect which candidate fields are present.
  2. Extract field values for the chunk using Gemini.
- Builds strict extraction prompts that require JSON-only output.
- Uses local scoring to pick informative chunks before Gemini calls.
- Contains field matching heuristics and low-information filters.
- Parses Gemini responses into `ExtractedObjectPacket` records.

### `pipeline/schema_config.py`
- Defines the project’s focused ArcGuide schema config.
- Lists the active field paths used in extraction.
- Maps aliases to canonical schema fields.
- Builds `SchemaConfig` objects consumed by the extractor.
- Includes identity field definitions used for packet hashing.

### `pipeline/stages/normalizer.py`
- Normalizes extracted values while preserving evidence.
- Converts strings, numbers, lists, and dictionaries into canonical forms.
- Generates deterministic identity hashes for object packets.
- Produces `NormalizedObjectPacket` records.

### `pipeline.nodes.ingest_node.persist_normalized_packets`
- Writes normalized packets into SQLite via `db.upsert_normalized_packets`.
- Ensures the database schema exists with migrations.

---

## Supporting Components

### `extraction.py`
- Contains claim-extraction helpers and a scaffold for absent fields.
- Builds `Claim` records for manual-review fields that were not searched.
- Not yet a full runtime extraction pipeline; supports evaluation-safe null claims.

### `verification.py`
- Contains confidence scoring and conflict detection logic.
- Computes claim confidence based on recency, authority, corroboration, and volatility.
- Detects conflicting claims by field path and scores gaps.
- This module is intended for later adjudication of extracted evidence.

### `narration.py`
- Placeholder narrator stage scaffold.
- Builds a brief output placeholder until verified claims are available.
- Intended to generate analyst-style summaries from verified claims.

### `converse.py` and `comparison.py`
- Not part of the main pipeline, but likely support user conversation and program comparison.
- They are present in repo root and integrate with the system-level functionality.

---

## Data Model Summary

- `ProgramIdentity`: canonical loyalty program resolved from user input.
- `ValidationResult`: status and optional clarification questions.
- `SearchQuery`: generated query plan metadata.
- `RetrievedUrl`: deduplicated URL from retrieval.
- `ScrapedUrlBlock`: raw scraped content for a URL.
- `RawDocument`: persisted Firecrawl document record.
- `SemanticChunk`: chunked evidence unit.
- `ExtractedField`: extracted schema field with status and source evidence.
- `ExtractedObjectPacket`: per-chunk extraction result.
- `NormalizedObjectPacket`: normalized packet with deterministic identity hash.
- `Claim` and `ConflictRecord`: future verification/adjudication records.

---

## Persistence and Storage

- Uses SQLite at `kobie.sqlite3`.
- Tables include runs, identities, sources, pages, chunks, claims, conflicts, briefs, conversations, raw documents, and normalized packets.
- `db.py` manages migrations, connections, and upserts.
- `raw_store.py` stores raw fetched documents, while ingestion persists normalized packets.

---

## Environment and Configuration

The project uses environment variables for API keys and endpoints.
Common env vars:
- `INPUT_VERIFIER_API_BASE`
- `INPUT_VERIFIER_API_KEY`
- `INPUT_VERIFIER_MODEL`
- `GEMINI_API_KEY`
- `GEMINI_API_BASE`
- `TAVILY_API_KEY`
- `TAVILY_API_BASE`
- `FIRECRAWL_API_KEY`
- `FIRECRAWL_API_BASE`

`providers.py` centralizes provider selection for each stage.

---

## Tests and Validation

- The `tests/` folder contains unit tests covering database behavior, retrieval, validation, query generation, graph orchestration, schema validation, and other components.
- The project also includes a `test_input_validator.py` script for manual end-to-end validator testing.

---

## How the Pieces Work Together

- `app.py` is the user-facing UI layer.
- `graph.py` orchestrates the pipeline and state transitions.
- `validation.py`, `query_generator.py`, `retrieval.py`, and `firecrawl_scraper.py` are the main external-facing stage implementations.
- `pipeline/nodes/ingest_node.py` connects the scraped content with the extraction pipeline.
- `pipeline/stages/*` implements reusable pipeline building blocks: raw storage, chunking, extraction, and normalization.
- `schemas.py` provides the shared typed contracts for all state and payloads.
- `db.py` persists structured evidence and pipeline outputs.
- `providers.py` keeps API configuration centralized.

## Notes

- The repository is intentionally designed around evidence grounding and anti-hallucination.
- The extraction stage is schema-driven and strict: it only uses chunk text and requires source-attributed evidence.
- The architecture separates retrieval, scraping, and extraction clearly so each stage can be swapped or replaced individually.
- Some modules like `verification.py`, `narration.py`, and `extraction.py` are scaffolded for later stages beyond core ingestion.
