"""Runtime-schema Gemini extraction.

The extractor is intentionally schema-agnostic. Callers provide object and
field definitions at runtime, and the model is instructed to use only the
chunk text supplied in the prompt.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import threading
import time
from typing import Any, Protocol

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core import cost_tracker
from core.providers import provider_for_stage
from core.schemas import ExtractedField, ExtractedObjectPacket, SemanticChunk


VALID_STATUSES = {"EXTRACTED", "NOT_FOUND", "AMBIGUOUS"}
TRANSIENT_GEMINI_STATUS_CODES = {429, 500, 502, 503, 504}

# Source types that originate from financial/IR filings (annual reports, 10-K, prospectuses).
# Chunks from these sources are deprioritised for consumer-facing fields because they use
# loyalty vocabulary in an accounting context (breakage, deferred revenue, rooms/properties).
_FINANCIAL_SOURCE_TYPES = frozenset({"financial", "ir_filing"})

# Fields that should rarely or never be answered from financial/IR source text.
# A membership_count from an IR filing is valid only when the text explicitly names members;
# the penalty below reduces score but does not eliminate these chunks entirely.
_CONSUMER_FACING_FIELDS = frozenset({
    "program_basics.geography",
    "earn_mechanics.non_transactional_earn",
    "digital_experience.gamification_features",
    "digital_experience.app_ratings",
    "member_sentiment.ratings",
    "member_sentiment.common_praise",
    "member_sentiment.common_complaints",
})
DERIVABLE_SIGNAL_KEYWORDS = {
    "member",
    "members",
    "membership",
    "points",
    "miles",
    "earn",
    "redeem",
    "redemption",
    "tier",
    "elite",
    "benefit",
    "benefits",
    "partner",
    "partners",
    "transfer",
    "expiry",
    "expire",
    "validity",
    "annual",
    "liability",
    "rating",
    "ratings",
    "review",
    "reviews",
    "complaint",
    "complaints",
    "competitor",
    "comparison",
    "cashback",
    "lounge",
    "upgrade",
    "status",
}
LOW_INFORMATION_PATTERNS = (
    "accept cookies",
    "privacy policy",
    "terms of use",
    "all rights reserved",
    "subscribe to",
    "enable javascript",
    "sign in",
    "log in",
)


class PipelineSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldDef(PipelineSchemaModel):
    """Runtime field definition supplied by the caller."""

    name: str
    description: str
    value_type: str = "string"
    required: bool = False
    identity: bool = False


class ObjectTypeDef(PipelineSchemaModel):
    """Runtime object definition supplied by the caller."""

    object_type: str
    description: str | None = None
    fields: list[FieldDef]
    identity_fields: list[str] = Field(default_factory=list)

    @field_validator("identity_fields")
    @classmethod
    def identity_fields_are_unique(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    def model_post_init(self, __context: Any) -> None:
        field_names = {field.name for field in self.fields}
        identity_from_fields = {field.name for field in self.fields if field.identity}
        all_identity_fields = set(self.identity_fields) | identity_from_fields
        unknown = all_identity_fields - field_names
        if unknown:
            raise ValueError(f"identity fields are not defined: {sorted(unknown)}")
        self.identity_fields = sorted(all_identity_fields)


class SchemaConfig(PipelineSchemaModel):
    """Collection of runtime object definitions for extraction."""

    object_types: list[ObjectTypeDef]
    scope_fields: list[str] = Field(default_factory=lambda: ["geography"])

    def object_type(self, object_type: str) -> ObjectTypeDef | None:
        normalized = object_type.strip().lower()
        for item in self.object_types:
            if item.object_type.strip().lower() == normalized:
                return item
        return None


class _RoundRobinKeyPool:
    """Thread-safe round-robin selector across multiple API keys.

    Keys are read from EXTRACTION_API_KEYS (comma-separated), falling back to
    EXTRACTION_API_KEY then GEMINI_API_KEY so a single-key setup is unchanged.

    Each concurrent request acquires a unique slot via acquire_slot() so it
    starts from a different key than every other in-flight request, giving true
    round-robin distribution without relying on 429 signals to drive rotation.
    On 429, the request naturally moves to the next key in its rotation sequence.
    """

    def __init__(self) -> None:
        keys = self._load_keys()
        if not keys:
            raise RuntimeError(
                "Gemini extraction is not configured. "
                "Set EXTRACTION_API_KEYS (comma-separated) or GEMINI_API_KEY."
            )
        self._keys = keys
        self._index = 0
        self._lock = threading.Lock()

    @staticmethod
    def _load_keys() -> list[str]:
        multi = os.getenv("EXTRACTION_API_KEYS", "")
        keys = [k.strip() for k in multi.split(",") if k.strip()]
        if not keys:
            provider = provider_for_stage("extraction")
            if provider.api_key:
                keys = [provider.api_key]
        return keys

    def acquire_slot(self) -> int:
        """Atomically reserve a unique starting index for one request (true round-robin)."""
        with self._lock:
            slot = self._index
            self._index = (self._index + 1) % len(self._keys)
            return slot

    def key_at(self, index: int) -> str:
        """Return the key at the given index (wraps around the pool)."""
        return self._keys[index % len(self._keys)]

    def current(self) -> str:
        with self._lock:
            return self._keys[self._index % len(self._keys)]

    def advance(self) -> str:
        """Move to next key and return it."""
        with self._lock:
            self._index = (self._index + 1) % len(self._keys)
            return self._keys[self._index]

    def __len__(self) -> int:
        return len(self._keys)


class ExtractionClient(Protocol):
    """Small protocol for test doubles and Gemini clients."""

    def complete_text(self, prompt: str) -> str:
        ...


class GeminiExtractionClient:
    """Minimal Gemini REST client for structured extraction prompts.

    Rotates across all keys in EXTRACTION_API_KEYS on 429s so TPM limits
    are spread across multiple Gemini projects/accounts.
    """

    def __init__(self) -> None:
        self._key_pool = _RoundRobinKeyPool()
        provider = provider_for_stage("extraction")
        self.model = provider.resolved_model or "gemini-2.5-flash"
        self.models = _ordered_models(
            self.model,
            os.getenv("EXTRACTION_FALLBACK_MODELS") or os.getenv("GEMINI_FALLBACK_MODELS") or "gemini-2.5-flash-lite",
        )
        base = (provider.api_base or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        if not base.endswith("/models"):
            base = f"{base}/models"
        self.api_base = base
        self.max_retries = _env_int("EXTRACTION_MAX_RETRIES", 2)
        self.retry_sleep_seconds = max(0, _env_int("EXTRACTION_RETRY_SLEEP_SECONDS", 2))

    def complete_text(self, prompt: str) -> str:
        # Acquire a unique slot so each concurrent request starts from a different
        # key, giving true round-robin distribution across the pool.
        slot = self._key_pool.acquire_slot()
        response = self._post_with_fallbacks(prompt, slot=slot)
        payload = response.json()
        usage = payload.get("usageMetadata", {})
        ledger = cost_tracker.get_current_ledger()
        if ledger:
            ledger.record_gemini(
                "extraction",
                int(usage.get("promptTokenCount") or 0),
                int(usage.get("candidatesTokenCount") or 0),
            )
        candidates = payload.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts)

    def _post_with_fallbacks(self, prompt: str, *, slot: int = 0) -> requests.Response:
        last_error: requests.HTTPError | None = None
        num_keys = len(self._key_pool)
        for model_index, model in enumerate(self.models):
            # Each model gets (max_retries + 1) * num_keys attempts so every
            # key is tried before giving up on the model.  The slot ensures
            # concurrent requests start from different keys (true round-robin);
            # subsequent attempts in the retry loop naturally rotate through the
            # remaining keys without needing an explicit advance() call.
            total_attempts = (self.max_retries + 1) * num_keys
            for attempt in range(total_attempts):
                api_key = self._key_pool.key_at(slot + attempt)
                response = requests.post(
                    f"{self.api_base}/{model}:generateContent",
                    params={"key": api_key},
                    json={
                        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0,
                            "responseMimeType": "application/json",
                            "thinkingConfig": {"thinkingBudget": 0},
                        },
                    },
                    timeout=90,
                )
                if response.status_code not in TRANSIENT_GEMINI_STATUS_CODES:
                    response.raise_for_status()
                    self.model = model
                    return response

                if response.status_code != 429:
                    # Non-429 transient error: sleep before next attempt.
                    if attempt < total_attempts - 1:
                        time.sleep(self.retry_sleep_seconds * ((attempt % (self.max_retries + 1)) + 1))
                # 429: next iteration automatically uses key_at(slot + attempt + 1).

                last_error = requests.HTTPError(
                    f"Gemini extraction unavailable ({response.status_code}) "
                    f"for model {model} (key index {(slot + attempt) % num_keys}).",
                    response=response,
                )
            if model_index + 1 < len(self.models):
                time.sleep(self.retry_sleep_seconds)

        if last_error:
            raise last_error
        raise RuntimeError("Gemini extraction request failed.")


def extract_from_chunks(
    chunks: list[SemanticChunk],
    schema_config: SchemaConfig,
    *,
    client: ExtractionClient | None = None,
    extraction_context: dict | None = None,
) -> list[ExtractedObjectPacket]:
    """Extract runtime-schema object packets from chunks using Gemini.

    Chunks are packed into multi-chunk batches so one Gemini call covers
    several evidence units instead of paying one call per chunk.

    extraction_context carries program-level metadata (program_subtype, program_name,
    brand, reference_year) used to build entity isolation and temporal constraint rules
    that are prepended to every extraction prompt in this run.
    """

    if not chunks or not schema_config.object_types:
        return []

    client = client or GeminiExtractionClient()
    packets: list[ExtractedObjectPacket] = []
    max_chunks = _env_int("MAX_EXTRACTION_CHUNKS", 30)
    selected_chunks = chunks[:max_chunks] if max_chunks > 0 else chunks
    batches = build_extraction_batches(selected_chunks, _env_int("EXTRACTION_BATCH_WORDS", 4000))
    concurrency = max(1, _env_int("GEMINI_EXTRACTION_CONCURRENCY", 1))
    failures: list[str] = []

    if concurrency == 1:
        for batch in batches:
            try:
                packets.extend(_extract_batch(batch, schema_config, client, extraction_context=extraction_context))
            except Exception as exc:
                failures.append(str(exc))
        if not packets and failures:
            raise RuntimeError(_summarize_extraction_failures(failures))
        return packets

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(_extract_batch, batch, schema_config, client, extraction_context)
            for batch in batches
        ]
        for future in as_completed(futures):
            try:
                packets.extend(future.result())
            except Exception as exc:
                failures.append(str(exc))
    if not packets and failures:
        raise RuntimeError(_summarize_extraction_failures(failures))
    return packets


def build_extraction_batches(chunks: list[SemanticChunk], batch_words: int) -> list[list[SemanticChunk]]:
    """Group consecutive chunks under a word budget; one Gemini call per batch."""

    if batch_words <= 0:
        return [[chunk] for chunk in chunks]

    batches: list[list[SemanticChunk]] = []
    current: list[SemanticChunk] = []
    current_words = 0
    for chunk in chunks:
        chunk_words = len(chunk.chunk_text.split())
        if current and current_words + chunk_words > batch_words:
            batches.append(current)
            current = []
            current_words = 0
        current.append(chunk)
        current_words += chunk_words
    if current:
        batches.append(current)
    return batches


def select_informative_chunks(
    chunks: list[SemanticChunk],
    schema_config: SchemaConfig,
    *,
    program_name: str | None = None,
    brand: str | None = None,
    max_chunks: int | None = None,
    min_score: int | None = None,
) -> tuple[list[SemanticChunk], list[SemanticChunk]]:
    """Keep chunks with local schema signals before spending Gemini calls."""

    if not chunks:
        return [], []

    min_score = min_score if min_score is not None else _env_int("MIN_EXTRACTION_CHUNK_SCORE", 2)
    if max_chunks is None:
        max_chunks = _env_int("MAX_EXTRACTION_CHUNKS", 30)
    scored = [
        (score_chunk_for_schema(chunk, schema_config, program_name=program_name, brand=brand), index, chunk)
        for index, chunk in enumerate(chunks)
    ]
    candidates = [item for item in scored if item[0] >= min_score]
    if not candidates:
        candidates = sorted(scored, key=lambda item: (-item[0], item[1]))[: min(5, len(scored))]

    selected_scored = _greedy_field_coverage(candidates, schema_config, max_chunks)

    selected_ids = {chunk.chunk_id for _score, _index, chunk in selected_scored}
    selected = [chunk for _score, _index, chunk in sorted(selected_scored, key=lambda item: item[1])]
    skipped = [chunk for chunk in chunks if chunk.chunk_id not in selected_ids]
    return selected, skipped


def _greedy_field_coverage(
    candidates: list[tuple[int, int, SemanticChunk]],
    schema_config: SchemaConfig,
    max_chunks: int | None,
) -> list[tuple[int, int, SemanticChunk]]:
    """Pick chunks that cover the most uncovered fields before spending budget on score."""

    matches = {
        item[2].chunk_id: _matched_field_names(item[2], schema_config)
        for item in candidates
    }
    uncovered = set(_all_field_names(schema_config))
    selected: list[tuple[int, int, SemanticChunk]] = []
    remaining = list(candidates)

    while remaining and uncovered and (not max_chunks or max_chunks <= 0 or len(selected) < max_chunks):
        best = max(
            remaining,
            key=lambda item: (len(matches[item[2].chunk_id] & uncovered), item[0], -item[1]),
        )
        if not matches[best[2].chunk_id] & uncovered:
            break
        selected.append(best)
        uncovered -= matches[best[2].chunk_id]
        remaining.remove(best)

    for item in sorted(remaining, key=lambda item: (-item[0], item[1])):
        if max_chunks and max_chunks > 0 and len(selected) >= max_chunks:
            break
        selected.append(item)
    return selected


def _matched_field_names(chunk: SemanticChunk, schema_config: SchemaConfig) -> set[str]:
    text = chunk.chunk_text.lower()
    return {
        field.name
        for object_type in schema_config.object_types
        for field in object_type.fields
        if any(keyword in text for keyword in _field_keywords(field))
    }


def score_chunk_for_schema(
    chunk: SemanticChunk,
    schema_config: SchemaConfig,
    *,
    program_name: str | None = None,
    brand: str | None = None,
) -> int:
    """Score explicit and derivable evidence signals without calling Gemini."""

    text = chunk.chunk_text.lower()
    score = 0
    if any(pattern in text for pattern in LOW_INFORMATION_PATTERNS):
        score -= 2

    context_terms = _context_terms(program_name, brand)
    if any(term in text for term in context_terms):
        score += 2

    if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|points?|miles?|months?|years?|cpp|rs\.?|inr|usd|\$)\b", text):
        score += 2
    elif re.search(r"\b\d{2,}(?:,\d{3})*\b", text):
        score += 1

    if any(keyword in text for keyword in DERIVABLE_SIGNAL_KEYWORDS):
        score += 2

    valid_fields = set(_all_field_names(schema_config))
    hinted_fields = [field for field in chunk.target_fields if field in valid_fields]
    if hinted_fields and _chunk_matches_any_field(text, hinted_fields, schema_config):
        score += 3

    matched_fields = 0
    for object_type in schema_config.object_types:
        for field in object_type.fields:
            if any(keyword in text for keyword in _field_keywords(field)):
                matched_fields += 1
    score += min(matched_fields, 4)

    # Financial/IR sources use loyalty vocabulary in an accounting context. Penalise
    # these chunks so consumer-facing evidence (review/official/faq) wins on score.
    if getattr(chunk, "source_type", None) in _FINANCIAL_SOURCE_TYPES:
        active_fields = set(_all_field_names(schema_config))
        consumer_overlap = _CONSUMER_FACING_FIELDS & active_fields
        if consumer_overlap:
            score -= 2

    return score


def _extract_batch(
    batch: list[SemanticChunk],
    schema_config: SchemaConfig,
    client: ExtractionClient,
    extraction_context: dict | None = None,
) -> list[ExtractedObjectPacket]:
    # Identify candidate fields for priority hints but always pass the full
    # schema so every one of the 31 required fields is considered for every
    # batch — narrowing risks missing fields whose keywords are atypical.
    candidate_fields = sorted(
        {field for chunk in batch for field in select_candidate_fields(chunk, schema_config)}
    )
    if not schema_config.object_types:
        return []

    prompt = build_extraction_prompt(
        batch,
        schema_config,
        extraction_context=extraction_context,
        priority_fields=candidate_fields,
    )
    for _attempt in range(2):
        try:
            raw = client.complete_text(prompt)
        except requests.RequestException:
            raise
        try:
            parsed = parse_extraction_response(raw, batch, schema_config)
            return [fill_missing_fields(packet, schema_config) for packet in parsed]
        except Exception:
            continue
    return []


def _build_extraction_context_preamble(context: dict) -> str:
    """Build a constraint block prepended to every extraction prompt for this run."""
    lines: list[str] = []

    program_name = context.get("program_name")
    brand = context.get("brand")
    program_subtype = context.get("program_subtype")
    reference_year = context.get("reference_year")

    if program_name or brand:
        parts = [p for p in [program_name, f"({brand})" if brand and brand != program_name else None] if p]
        lines.append(f"TARGET PROGRAM: {' '.join(parts)}")

    if program_subtype == "B2B":
        lines += [
            "PROGRAM SUBTYPE: CORPORATE / B2B",
            "",
            "ENTITY ISOLATION — CORPORATE PROGRAM:",
            "This program is held and operated at a COMPANY level, not by an individual traveler.",
            "Apply the following strict rules to every field in every chunk:",
            "- REJECT individual consumer status tier names (e.g. Silver, Gold, Platinum, Diamond,",
            "  Medallion, Premier, Executive). These belong to the consumer variant of the program.",
            "- REJECT individual earn rates derived from personal credit card or co-brand card spend.",
            "- REJECT individual consumer mobile app features (boarding passes, seat selection,",
            "  personal trip maps, personal upgrade certificates). Extract only corporate account",
            "  management tools, bulk booking portals, and administrator dashboards.",
            "- REJECT point or mile transfer mechanics that move currency to an individual's",
            "  hotel, airline, or retail account. Extract only company-level earn/burn.",
            "- ACCEPT company spend thresholds, unique employee traveler counts, and corporate",
            "  account qualification criteria.",
            "- If a chunk mixes consumer and corporate content, extract ONLY the corporate portion.",
            "  Mark any field where consumer and corporate data appear together as AMBIGUOUS.",
        ]
    elif program_subtype == "B2C":
        lines += [
            "PROGRAM SUBTYPE: CONSUMER / B2C",
            "",
            "ENTITY ISOLATION — CONSUMER PROGRAM:",
            "- REJECT corporate enrollment requirements, company spend thresholds, or B2B account",
            "  management features. Extract only individual member attributes.",
        ]

    if reference_year:
        lines += [
            "",
            f"TEMPORAL CONTEXT: Current reference year is {reference_year}.",
            "Apply the following rules to time-sensitive values:",
            "- If a chunk contains a forward-looking statement about a year that has already passed",
            f"  (e.g. 'will launch in 2022' when the reference year is {reference_year}), mark that",
            "  field AMBIGUOUS — do not treat it as a current fact.",
            "- Prefer evidence accompanied by an explicit date. When a numeric value (earn rate,",
            "  threshold, point value, tier name) appears only in content that is visibly dated",
            f"  more than two years before {reference_year}, reduce confidence to <= 0.5.",
            "- Do NOT extrapolate or infer what the current value might be from an old source.",
        ]

    priority_fields: list[str] = context.get("priority_fields") or []
    if priority_fields:
        lines += [
            "",
            "PROGRAM PRIORITY FIELDS (ranked by schema importance for this program type):",
            ", ".join(priority_fields),
            "Allocate extra attention to extracting these fields. Mark a priority field as NOT_FOUND"
            " only after exhausting all evidence in the chunk.",
        ]

    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"


def build_extraction_prompt(
    chunks: list[SemanticChunk],
    schema_config: SchemaConfig,
    extraction_context: dict | None = None,
    *,
    priority_fields: list[str] | None = None,
) -> str:
    context_preamble = _build_extraction_context_preamble(extraction_context) if extraction_context else ""
    schema_json = json.dumps(schema_config.model_dump(), ensure_ascii=True, indent=2)
    priority_hint = (
        f"\nPriority fields (keyword signals detected in this batch — other schema fields may also apply):\n"
        f"{', '.join(priority_fields)}\n"
        if priority_fields
        else ""
    )
    chunk_blocks = "\n\n".join(
        f"CHUNK {index + 1}\n"
        f"chunk_id: {chunk.chunk_id}\n"
        f"source_url: {chunk.source_url}\n"
        + (f"query_id: {chunk.query_id}\n" if chunk.query_id else "")
        + (f"chunk_index: {chunk.chunk_index}\n" if chunk.chunk_index is not None else "")
        + f"priority target fields: {', '.join(chunk.target_fields) if chunk.target_fields else 'all fields in the runtime schema'}\n"
        f'chunk_text:\n"""{_sanitize_chunk_for_prompt(chunk.chunk_text)}"""'
        for index, chunk in enumerate(chunks)
    )
    return f"""
You are a strict structured extraction engine.

{context_preamble}Use ONLY the chunk texts provided below. Do not use training knowledge. Do not
guess, infer, compute, or fill missing values. Extract a value ONLY when it is
explicitly stated in the chunk text — do not derive or calculate values not
literally present. The source_snippet must be the exact text passage from which
the value was directly read.

Each CHUNK below is an independent evidence unit identified by chunk_id. Never
combine evidence across chunks; every extracted field must be supported by the
single chunk named in its object's chunk_id.

Runtime schema (all fields must be considered for every chunk):
{schema_json}
{priority_hint}

Return JSON only in this exact shape:
{{
  "objects": [
    {{
      "chunk_id": "chunk_id of the chunk the evidence came from",
      "object_type": "one runtime object_type",
      "scope": {{"geography": "only if explicitly stated in that chunk, otherwise omit"}},
      "fields": {{
        "field_name": {{
          "value": "explicit value or null",
          "status": "EXTRACTED | AMBIGUOUS",
          "source_snippet": "short exact supporting text copied verbatim from that chunk",
          "confidence": 0.0
        }}
      }}
    }}
  ]
}}

Rules:
- EXTRACTED requires an exact source_snippet copied verbatim from the same
  chunk, including when the value is derived from the cited evidence.
- Only include fields with status EXTRACTED or AMBIGUOUS. Omit fields with no
  evidence in the chunk; do not return NOT_FOUND fields.
- If evidence is unclear or conflicting inside one chunk, return value null and
  status AMBIGUOUS.
- Return at most one object per chunk per object_type. Skip chunks without
  evidence entirely.
- Never invent object types or field names outside the runtime schema.
- It is valid to return an empty objects array.

{chunk_blocks}
""".strip()


def parse_extraction_response(
    raw_text: str,
    chunks: list[SemanticChunk],
    schema_config: SchemaConfig | None = None,
) -> list[ExtractedObjectPacket]:
    """Parse and sanitize Gemini extraction output for a chunk batch."""

    payload = json.loads(_extract_json_block(raw_text))
    objects = payload if isinstance(payload, list) else payload.get("objects", [])
    if not isinstance(objects, list):
        raise ValueError("extraction response must contain an objects list")

    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    default_chunk = chunks[0] if len(chunks) == 1 else None
    packets: list[ExtractedObjectPacket] = []
    for item in objects:
        if not isinstance(item, dict):
            continue
        chunk = chunks_by_id.get(str(item.get("chunk_id") or "")) or default_chunk
        if chunk is None:
            continue
        object_type = str(item.get("object_type") or "").strip()
        fields_payload = item.get("fields") or {}
        if not object_type or not isinstance(fields_payload, dict):
            continue
        object_def = schema_config.object_type(object_type) if schema_config else None
        if schema_config and object_def is None:
            continue
        valid_field_names = {field.name for field in object_def.fields} if object_def else None
        fields = {
            str(field_name): _parse_field(field_data, chunk)
            for field_name, field_data in fields_payload.items()
            if isinstance(field_data, dict) and (valid_field_names is None or str(field_name) in valid_field_names)
        }
        if not fields:
            continue
        packets.append(
            ExtractedObjectPacket(
                object_type=object_type,
                fields=fields,
                source_url=chunk.source_url,
                chunk_id=chunk.chunk_id,
                scope=item.get("scope") if isinstance(item.get("scope"), dict) else {},
            )
        )
    return packets


def fill_missing_fields(packet: ExtractedObjectPacket, schema_config: SchemaConfig) -> ExtractedObjectPacket:
    """Ensure every active schema field is present as EXTRACTED/NOT_FOUND/AMBIGUOUS."""

    object_def = schema_config.object_type(packet.object_type)
    if object_def is None:
        return packet
    fields = dict(packet.fields)
    for field in object_def.fields:
        fields.setdefault(
            field.name,
            ExtractedField(value=None, status="NOT_FOUND", source_url=None, source_snippet=None, confidence=None),
        )
    return packet.model_copy(update={"fields": fields})


def select_candidate_fields(chunk: SemanticChunk, schema_config: SchemaConfig) -> list[str]:
    """Cheap local prefilter before the Gemini detection pass."""

    valid_fields = set(_all_field_names(schema_config))
    hinted_fields = [field for field in chunk.target_fields if field in valid_fields]
    if hinted_fields:
        return sorted(set(hinted_fields))

    text = chunk.chunk_text.lower()
    selected: set[str] = set()
    for object_type in schema_config.object_types:
        for field in object_type.fields:
            keywords = _field_keywords(field)
            if any(keyword in text for keyword in keywords):
                selected.add(field.name)

    identity_fields = {
        field.name
        for object_type in schema_config.object_types
        for field in object_type.fields
        if field.identity
    }
    selected.update(identity_fields)
    return sorted(selected)


def narrow_schema_config(schema_config: SchemaConfig, field_names: list[str]) -> SchemaConfig:
    wanted = set(field_names)
    object_types: list[ObjectTypeDef] = []
    for object_type in schema_config.object_types:
        fields = [field for field in object_type.fields if field.name in wanted]
        if not fields:
            continue
        object_types.append(
            ObjectTypeDef(
                object_type=object_type.object_type,
                description=object_type.description,
                fields=fields,
            )
        )
    return SchemaConfig(object_types=object_types, scope_fields=schema_config.scope_fields)


def _parse_field(field_data: dict[str, Any], chunk: SemanticChunk) -> ExtractedField:
    status = str(field_data.get("status") or "NOT_FOUND").strip().upper()
    if status not in VALID_STATUSES:
        status = "AMBIGUOUS"

    if status == "EXTRACTED":
        snippet = field_data.get("source_snippet")
        if (
            not isinstance(snippet, str)
            or not snippet.strip()
            or not _snippet_in_text(snippet, chunk.chunk_text)
        ):
            # Snippet missing or not verbatim in chunk — cannot verify, discard value.
            return ExtractedField(
                value=None,
                status="AMBIGUOUS",
                source_url=chunk.source_url,
                source_snippet=None,
                confidence=None,
            )
        confidence = _coerce_confidence(field_data.get("confidence"))
        min_confidence = _env_float("EXTRACTION_MIN_CONFIDENCE", 0.5)
        if confidence is not None and confidence < min_confidence:
            # Confidence below threshold — keep the snippet for audit but discard value.
            return ExtractedField(
                value=None,
                status="AMBIGUOUS",
                source_url=chunk.source_url,
                source_snippet=snippet,
                confidence=confidence,
            )
        return ExtractedField(
            value=field_data.get("value"),
            status="EXTRACTED",
            source_url=chunk.source_url,
            source_snippet=snippet,
            confidence=confidence,
        )

    return ExtractedField(
        value=None,
        status=status,  # type: ignore[arg-type]
        source_url=chunk.source_url if status == "AMBIGUOUS" else None,
        source_snippet=field_data.get("source_snippet") if status == "AMBIGUOUS" else None,
        confidence=_coerce_confidence(field_data.get("confidence")) if status == "AMBIGUOUS" else None,
    )


def _sanitize_chunk_for_prompt(text: str) -> str:
    """Strip prompt-injection patterns before embedding scraped text into the prompt."""
    text = text.replace('"""', "'''")
    text = re.sub(
        r"(?i)(ignore\s+(previous|all)\s+instructions|new\s+instructions\s*:|"
        r"you\s+are\s+now\s+a|disregard\s+the\s+above|system\s*:\s*you\s+are)",
        "[FILTERED]",
        text,
    )
    return text


def _snippet_in_text(snippet: str, chunk_text: str) -> bool:
    """Hallucination gate: the cited snippet must literally appear in the chunk."""

    return _normalize_for_match(snippet) in _normalize_for_match(chunk_text)


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _coerce_confidence(value: Any) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _extract_json_block(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped

    object_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    array_match = re.search(r"\[.*\]", text, flags=re.DOTALL)
    matches = [match for match in (object_match, array_match) if match]
    if not matches:
        raise json.JSONDecodeError("No JSON object or array found", text, 0)
    return min(matches, key=lambda match: match.start()).group(0)


def _ordered_models(primary_model: str, fallback_models: str) -> list[str]:
    models = [primary_model.strip()]
    models.extend(model.strip() for model in fallback_models.split(",") if model.strip())
    return list(dict.fromkeys(models))


def _summarize_extraction_failures(failures: list[str]) -> str:
    first = failures[0] if failures else "Unknown extraction failure."
    return f"Gemini extraction failed for {len(failures)} chunk batches. First error: {first}"


def _context_terms(program_name: str | None, brand: str | None) -> set[str]:
    terms: set[str] = set()
    for value in (program_name, brand):
        text = (value or "").strip().lower()
        if not text:
            continue
        terms.add(text)
        terms.update(part for part in re.split(r"[_\s./-]+", text) if len(part) >= 4)
    return terms


def _chunk_matches_any_field(text: str, field_names: list[str], schema_config: SchemaConfig) -> bool:
    wanted = set(field_names)
    for object_type in schema_config.object_types:
        for field in object_type.fields:
            if field.name in wanted and any(keyword in text for keyword in _field_keywords(field)):
                return True
    return False


def _all_field_names(schema_config: SchemaConfig) -> list[str]:
    return [field.name for object_type in schema_config.object_types for field in object_type.fields]


def _field_keywords(field: FieldDef) -> set[str]:
    pieces = {
        field.name,
        field.name.split(".")[-1],
        field.name.split(".")[-1].replace("_", " "),
    }
    pieces.update(part for part in re.split(r"[_\s./-]+", field.name) if len(part) >= 4)
    pieces.update(part for part in re.split(r"[_\s./-]+", field.description.lower()) if len(part) >= 5)
    pieces.update(_semantic_keywords_for_field(field.name))
    return {piece.lower() for piece in pieces if piece}


def _semantic_keywords_for_field(field_name: str) -> set[str]:
    suffix = field_name.split(".")[-1]
    section = field_name.split(".")[0]
    keywords: set[str] = set()
    section_keywords = {
        "program_basics": {"program", "brand", "owned", "operator", "membership", "members"},
        "earn_mechanics": {"earn", "earning", "points", "miles", "bonus", "spend", "purchase"},
        "burn_mechanics": {"redeem", "redemption", "reward", "points", "value", "expire", "expiry"},
        "tier_system": {"tier", "elite", "status", "qualification", "benefits", "upgrade"},
        "partnerships": {"partner", "partners", "transfer", "airline", "hotel", "merchant"},
        "digital_experience": {"app", "mobile", "rating", "personalization", "gamification"},
        "member_sentiment": {"review", "rating", "complaint", "praise", "reddit", "forum"},
        "competitive_position": {"competitor", "comparison", "differentiator", "weakness", "risk"},
    }
    field_keywords = {
        "membership_count": {"members", "member base", "million members", "active members"},
        "base_earn_rate": {"earn rate", "earn points", "per rupee", "per dollar", "per spend"},
        "bonus_categories": {"bonus", "accelerated", "category", "categories"},
        "redemption_thresholds": {"minimum redemption", "threshold", "minimum points"},
        "point_value_cpp": {"point value", "cpp", "cents per point", "value per point"},
        "expiry_policy": {"expire", "expiry", "validity", "valid for"},
        "tier_names": {"silver", "gold", "platinum", "elite", "tier"},
        "qualification_criteria": {"qualify", "qualification", "eligible", "threshold"},
        "tier_benefits": {"benefits", "upgrade", "lounge", "priority"},
        "partner_names": {"partner", "partners", "alliance"},
        "details": {"earn", "burn", "redeem", "redemption", "partner details", "partnership"},
        "app_ratings": {"app store", "apple app", "play store", "google play", "rating"},
        "app_store_rating": {"app store", "apple app", "rating"},
        "play_store_rating": {"play store", "google play", "rating"},
        "common_complaints": {"complaints", "issues", "negative", "poor"},
        "common_praise": {"praise", "positive", "good", "excellent"},
        "sources_checked": {"source", "sources", "review", "reviews", "reddit", "forum", "trustpilot"},
        "closest_competitors": {"competitors", "compared with", "versus", "vs"},
    }
    keywords.update(section_keywords.get(section, set()))
    keywords.update(field_keywords.get(suffix, set()))
    return keywords


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default
