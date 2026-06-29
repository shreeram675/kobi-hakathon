# Eraser Canvas — Node Prompts
### Kobie ACI Agent · LangGraph 6-Node Pipeline
### Paste each prompt individually into Eraser AI → generate → then connect manually.

---

## NODE 1 — input_validator

**Eraser Prompt:**
```
Create a component card titled "Node 1 · input_validator" for a LangGraph pipeline.

ROLE: Resolves a raw user-typed loyalty program name into a canonical program identity.

INPUTS (top):
- user_input: raw string (e.g. "Marriott Bonvoy")
- validation_messages: list of chat turns (optional, for multi-turn clarification)

INTERNAL STEPS (body, as a numbered list):
1. validate_conversation(messages) → calls Input Verifier LLM
2. Check status: resolved / needs_clarification / rejected
3. If resolved → extract identity fields from ValidationResult
4. If not resolved → append PipelineError and halt

OUTPUTS (bottom):
- validation_result (status, reason)
- program_identity (program_name, brand, domain, country_or_region)

ROUTING (conditional edge):
- status == "resolved" → query_generator
- status != "resolved" → END

STYLE: Blue border, label "Input Validator", icon: shield or filter
```

---

## NODE 2 — query_generator

**Eraser Prompt:**
```
Create a component card titled "Node 2 · query_generator" for a LangGraph pipeline.

ROLE: Converts a resolved program identity into a structured set of Tavily search queries covering every loyalty schema field.

INPUTS (top):
- program_identity (program_name, brand, domain, country_or_region)

LLM USED:
- Gemini 2.5 Flash (via GEMINI_API_KEY or QUERY_GENERATOR_API_KEY)

INTERNAL STEPS (body):
1. Build a field-query map across 8 schema categories (earn, burn, tiers, partners, fees, sentiment, valuation, app ratings)
2. Call Gemini 2.5 Flash with identity context
3. Return ≤ 15 Tavily queries with source_type tags (official, terms, financial, news, review, forum, etc.)
4. FALLBACK_QUERIES fire if LLM call fails

OUTPUTS (bottom):
- query_generation_result (queries list, field_query_map)
- search_queries: list[str] (Tavily query strings)

STYLE: Purple border, label "Query Generator", icon: search or brain
```

---

## NODE 3 — retrieval

**Eraser Prompt:**
```
Create a component card titled "Node 3 · retrieval" for a LangGraph pipeline.

ROLE: Executes all Tavily search queries in parallel and returns a deduplicated ranked URL list.

INPUTS (top):
- search_queries: list[str] (up to 15 Tavily queries)

SERVICE USED:
- Tavily Search API (TAVILY_API_KEY)

INTERNAL STEPS (body):
1. Fan out all queries to Tavily concurrently
2. Collect (url, score, source_type, query_id) tuples per result
3. Deduplicate by normalized URL
4. Rank by Tavily relevance score

OUTPUTS (bottom):
- retrieval_result (urls, total_found)
- retrieved_urls: list of RetrievedURL objects (url, score, source_type, query_id)

STYLE: Teal border, label "Retrieval (Tavily)", icon: globe or link
```

---

## NODE 4 — firecrawl_scraper

**Eraser Prompt:**
```
Create a component card titled "Node 4 · firecrawl_scraper" for a LangGraph pipeline.

ROLE: Selects the most valuable URLs within a budget cap and scrapes each into clean markdown blocks.

INPUTS (top):
- retrieved_urls: list of RetrievedURL objects

SERVICE USED:
- Firecrawl API (FIRECRAWL_API_KEY)

URL SELECTION LOGIC (inner box titled "select_urls_for_firecrawl"):
- Hard cap: MAX_FIRECRAWL_URLS (default 12)
- Priority order: official → terms → financial → faq → partners → review → app_reviews → news → forum → competitors
- Consumer floor: reserve MAX/6 slots for review/forum/app_review source types (sentiment always represented)
- Round-robin across source-type groups so every query category gets at least 1 URL

SCRAPING:
- Firecrawl per-URL markdown scrape
- Each result → ScrapedBlock (url, markdown_content, source_type, query_id, error)

OUTPUTS (bottom):
- firecrawl_result (blocks, total_urls, successful_scrapes)
- scraped_blocks: list[ScrapedBlock]

ERROR HANDLING: If all URLs fail → PipelineError (checks for Insufficient Credits / 403 Forbidden messages)

STYLE: Orange border, label "Firecrawl Scraper", icon: fire or spider
```

---

## NODE 5 — ingest

**Eraser Prompt:**
```
Create a component card titled "Node 5 · ingest" for a LangGraph pipeline.
Show the internal sub-stages as a vertical pipeline inside the card.

ROLE: Transforms raw scraped markdown into normalized, deduplicated, schema-grounded extraction packets with per-field confidence scores and a Field Report.

INPUTS (top):
- scraped_blocks: list[ScrapedBlock] (raw markdown per URL)

INTERNAL SUB-STAGE PIPELINE (show as 6 chained steps inside the card):

  [1] store_firecrawl_output
       → Save raw markdown to SQLite table raw_documents
       → Output: raw_documents list

  [2] semantic_chunk  (chunker.py)
       → Heading-based markdown splitting
       → MIN_SECTION_WORDS=30 · TARGET_CHUNK_WORDS=600 · MAX_CHUNK_WORDS=1500
       → Strip boilerplate nav lines
       → Output: semantic_chunks list

  [3] select_informative_chunks
       → Filter low-signal chunks (no schema keywords, too short)
       → Output: extraction_chunks (passed), skipped_chunks (dropped)

  [4] extract_from_chunks  (extractor.py)
       → Gemini 2.5 Flash · structured JSON extraction per chunk
       → Maps to 8-category loyalty schema (earn, burn, tiers, partners, fees, sentiment, valuation, app)
       → Output: extracted_packets list

  [5] normalize_packet  (normalizer.py)
       → Lowercase strings, coerce numerics, deduplicate lists
       → SHA-256 identity hash (first 24 hex chars of JSON-serialized identity fields)
       → Upsert-based deduplication via identity hash
       → Save to SQLite table normalized_packets
       → Output: normalized_packets list

  [6] build_field_report  (field_report.py)
       → Per-field: extraction_status, source_urls, snippet, confidence_score
       → confidence_score = volatility_weighted(recency, authority, corroboration)
       → Output: field_report dict

LLM USED:
- Gemini 2.5 Flash for extraction (EXTRACTION_API_KEY or GEMINI_API_KEY)

OUTPUTS (bottom):
- raw_documents, semantic_chunks, extraction_chunks, skipped_chunks
- extracted_packets, normalized_packets
- field_report (per-field status + confidence)

STYLE: Green border, label "Ingest Pipeline", icon: database or layers. Show inner steps as a mini vertical flowchart.
```

---

## NODE 6 — adjudication

**Eraser Prompt:**
```
Create a component card titled "Node 6 · adjudication" for a LangGraph pipeline.
Show internal sub-components as nested boxes.

ROLE: Detects field-level conflicts across normalized packets from different sources and resolves them via confidence gap auto-resolution or a 5-step adversarial LLM debate.

INPUTS (top):
- normalized_packets: list of NormalizedPacket objects
- field_report: per-field extraction metadata

INNER COMPONENT 1 — Conflict Detector (conflict_adjudicator.py):
  - Group all extracted values per field_path across packets
  - A conflict = same field_path has ≥ 2 distinct values from independent sources
  - Independent-source check: URLs must differ at domain level
  - Output: conflicts list (field_name, claim_a, claim_b, volatility)

INNER COMPONENT 2 — Auto-Resolve Gate:
  - If confidence_gap between claim_a and claim_b > 0.20 → auto-resolve to higher-confidence claim (no debate)
  - Otherwise → route to 5-step debate

INNER COMPONENT 3 — 5-Step Adversarial Debate Engine (debate_engine.py):

  Show as 5 numbered steps in a mini flowchart:

  Step 1: Advocate A argues for claim_a
          (Groq llama3-70b-8192 · temp=0.0 · max 200 tokens · metadata-only)

  Step 2: Advocate B argues for claim_b
          (Groq llama3-70b-8192 · temp=0.0 · runs concurrently with Step 1)

  [TF-IDF Gate]: cosine_similarity(arg_A, arg_B)
          If similarity ≥ 0.80 → skip rebuttals (arguments not differentiated)
          If similarity < 0.80 → run rebuttals

  Step 3: Rebuttal A — A reads B's argument, attacks single weakest point
          (max 150 tokens · hallucination-fenced to claim metadata only)

  Step 4: Rebuttal B — B reads A's argument, attacks single weakest point
          (runs concurrently with Step 3)

  Step 5: Judge — sees all 4 outputs, applies volatility-weighted scoring
          (Groq llama3-70b-8192 · temp=0.1 · max 350 tokens)
          Returns structured JSON verdict:
            winner: A | B | FLAG
            winning_value: string or null
            deciding_factor: recency | authority | corroboration | rebuttal_quality | unresolvable
            rebuttal_assessment: {A_rebuttal: strong|weak|hallucinated, B_rebuttal: ...}
            confidence_adjustment: float [-0.10, +0.10]

  Concurrency control: asyncio.Semaphore(3) caps in-flight Groq calls

VOLATILITY WEIGHTS used by judge:
  HIGH volatility → recency 50%, authority 25%, corroboration 25%
  LOW volatility  → recency 20%, authority 50%, corroboration 30%

INNER COMPONENT 4 — apply_adjudication_to_field_report:
  - Write winning_value, deciding_factor, final_confidence back into field_report
  - FLAG fields marked for manual review

OUTPUTS (bottom):
- conflicts: list of detected conflict dicts
- adjudicated: list of debate verdicts (winner, winning_value, deciding_factor, reasoning, final_confidence)
- field_report: updated with adjudication results

→ END of pipeline

LLM USED: Groq llama3-70b-8192 (DEBATE_API_KEY or GROQ_API_KEY)

STYLE: Red border, label "Conflict Adjudication", icon: scales or gavel. Nest Debate Engine as an inner box with the 5 steps.
```

---

## PIPELINE FLOW CONNECTOR GUIDE
### After generating all 6 nodes, connect them in this order:

```
START
  │
  ▼
[Node 1: input_validator]
  │
  ├── status == "resolved" ──────────────────────────────►
  │                                                       │
  └── status != "resolved" → END                         ▼
                                              [Node 2: query_generator]
                                                          │
                                                          ▼
                                              [Node 3: retrieval]
                                                          │
                                                          ▼
                                              [Node 4: firecrawl_scraper]
                                                          │
                                                          ▼
                                              [Node 5: ingest]
                                                          │
                                                          ▼
                                              [Node 6: adjudication]
                                                          │
                                                          ▼
                                                        END
```

### Edge labels to add:
- Node 1 → Node 2: `"resolved" | program_identity`
- Node 1 → END: `"not resolved" | PipelineError`
- Node 2 → Node 3: `search_queries (≤15)`
- Node 3 → Node 4: `retrieved_urls (ranked)`
- Node 4 → Node 5: `scraped_blocks (≤12 URLs)`
- Node 5 → Node 6: `normalized_packets + field_report`
- Node 6 → END: `adjudicated field_report`

---

## ERASER CANVAS LAYOUT SUGGESTION

Arrange nodes left-to-right or top-to-bottom in a single lane.
- Place Node 5 (ingest) as a larger box — it has 6 internal sub-stages.
- Place Node 6 (adjudication) as the largest box — it has 4 nested sub-components and the 5-step debate engine.
- Use a separate swim lane or annotation box to show the SQLite storage layer (raw_documents, normalized_packets tables) alongside Nodes 4 and 5.
- Annotate the LLM provider beside each node that uses one:
  - Node 2: Gemini 2.5 Flash
  - Node 5: Gemini 2.5 Flash
  - Node 6: Groq / LLaMA 3 70B
