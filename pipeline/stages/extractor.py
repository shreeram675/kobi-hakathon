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
import time
from typing import Any, Protocol

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

from providers import provider_for_stage
from schemas import ExtractedField, ExtractedObjectPacket, SemanticChunk


VALID_STATUSES = {"EXTRACTED", "NOT_FOUND", "AMBIGUOUS"}
TRANSIENT_GEMINI_STATUS_CODES = {429, 500, 502, 503, 504}
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


class ExtractionClient(Protocol):
    """Small protocol for test doubles and Gemini clients."""

    def complete_text(self, prompt: str) -> str:
        ...


class GeminiExtractionClient:
    """Minimal Gemini REST client for structured extraction prompts."""

    def __init__(self) -> None:
        provider = provider_for_stage("extraction")
        if not provider.api_key:
            raise RuntimeError("Gemini extraction is not configured. Set GEMINI_API_KEY.")
        self.api_key = provider.api_key
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
        response = self._post_with_fallbacks(prompt)
        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts)

    def _post_with_fallbacks(self, prompt: str) -> requests.Response:
        last_error: requests.HTTPError | None = None
        for model_index, model in enumerate(self.models):
            for attempt in range(self.max_retries + 1):
                response = requests.post(
                    f"{self.api_base}/{model}:generateContent",
                    params={"key": self.api_key},
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

                last_error = requests.HTTPError(
                    f"Gemini extraction is temporarily unavailable ({response.status_code}) for model {model}.",
                    response=response,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep_seconds * (attempt + 1))
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
) -> list[ExtractedObjectPacket]:
    """Extract runtime-schema object packets from chunks using Gemini."""

    if not chunks or not schema_config.object_types:
        return []

    client = client or GeminiExtractionClient()
    packets: list[ExtractedObjectPacket] = []
    max_chunks = _env_int("MAX_EXTRACTION_CHUNKS", 30)
    selected_chunks = chunks[:max_chunks] if max_chunks > 0 else chunks
    concurrency = max(1, _env_int("GEMINI_EXTRACTION_CONCURRENCY", 1))
    failures: list[str] = []

    if concurrency == 1:
        for chunk in selected_chunks:
            try:
                packets.extend(_extract_chunk(chunk, schema_config, client))
            except Exception as exc:
                failures.append(str(exc))
        if not packets and failures:
            raise RuntimeError(_summarize_extraction_failures(failures))
        return packets

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_extract_chunk, chunk, schema_config, client) for chunk in selected_chunks]
        for future in as_completed(futures):
            try:
                packets.extend(future.result())
            except Exception as exc:
                failures.append(str(exc))
    if not packets and failures:
        raise RuntimeError(_summarize_extraction_failures(failures))
    return packets


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
    scored = [
        (score_chunk_for_schema(chunk, schema_config, program_name=program_name, brand=brand), index, chunk)
        for index, chunk in enumerate(chunks)
    ]
    selected_scored = [item for item in scored if item[0] >= min_score]
    if not selected_scored:
        selected_scored = sorted(scored, key=lambda item: (-item[0], item[1]))[: min(5, len(scored))]

    selected_scored = sorted(selected_scored, key=lambda item: (-item[0], item[1]))
    if max_chunks and max_chunks > 0:
        selected_scored = selected_scored[:max_chunks]

    selected_ids = {chunk.chunk_id for _score, _index, chunk in selected_scored}
    selected = [chunk for _score, _index, chunk in sorted(selected_scored, key=lambda item: item[1])]
    skipped = [chunk for chunk in chunks if chunk.chunk_id not in selected_ids]
    return selected, skipped


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
    return score


def _extract_chunk(
    chunk: SemanticChunk,
    schema_config: SchemaConfig,
    client: ExtractionClient,
) -> list[ExtractedObjectPacket]:
    candidate_fields = select_candidate_fields(chunk, schema_config)
    candidate_schema = narrow_schema_config(schema_config, candidate_fields)
    detected_fields = detect_present_fields(chunk, candidate_schema, client)
    if not detected_fields:
        return []

    extraction_schema = candidate_schema
    prompt = build_extraction_prompt(chunk, extraction_schema)
    for _attempt in range(2):
        try:
            raw = client.complete_text(prompt)
            parsed = parse_extraction_response(raw, chunk, extraction_schema)
            return [fill_missing_fields(packet, extraction_schema) for packet in parsed]
        except Exception:
            continue
    return []


def detect_present_fields(
    chunk: SemanticChunk,
    schema_config: SchemaConfig,
    client: ExtractionClient,
) -> list[str]:
    """Two-pass first step: ask Gemini which candidate fields are evidenced."""

    fields = _all_field_names(schema_config)
    if not fields:
        return []
    prompt = build_field_detection_prompt(chunk, schema_config)
    for _attempt in range(2):
        try:
            payload = json.loads(_extract_json_block(client.complete_text(prompt)))
            present = payload.get("present_fields", [])
            if not isinstance(present, list):
                return []
            valid_fields = set(fields)
            return sorted({str(field) for field in present if str(field) in valid_fields})
        except requests.HTTPError:
            raise
        except Exception:
            continue
    return []


def build_field_detection_prompt(chunk: SemanticChunk, schema_config: SchemaConfig) -> str:
    schema_json = json.dumps(schema_config.model_dump(), ensure_ascii=True, indent=2)
    return f"""
You are a strict field-presence detector.

Use ONLY the chunk text. Do not extract values. Do not infer.
Return only fields that have explicit evidence in the chunk.
Also return fields that are source-grounded derivations from the chunk, such as
a tier field implied by a tier table, a points value implied by a redemption
example, or a program type implied by the page's own wording. Do not use
outside knowledge.

Runtime candidate schema:
{schema_json}

Return JSON only:
{{"present_fields": ["field.path"]}}

If no candidate fields are explicitly evidenced, return:
{{"present_fields": []}}

Chunk text:
\"\"\"{chunk.chunk_text}\"\"\"
""".strip()


def build_extraction_prompt(chunk: SemanticChunk, schema_config: SchemaConfig) -> str:
    schema_json = json.dumps(schema_config.model_dump(), ensure_ascii=True, indent=2)
    target_fields = ", ".join(chunk.target_fields) if chunk.target_fields else "all fields in the runtime schema"
    return f"""
You are a strict structured extraction engine.

Use ONLY the provided chunk text. Do not use training knowledge. Do not guess
or fill missing values. You may derive a value only when the chunk itself
contains enough evidence to support that derivation, and the field must still
include an exact supporting source_snippet from the chunk.

Priority target fields for this chunk: {target_fields}
You must still consider every field in the runtime schema when the chunk
explicitly contains evidence for it.

Runtime schema:
{schema_json}

Return JSON only in this exact shape:
{{
  "objects": [
    {{
      "object_type": "one runtime object_type",
      "scope": {{"geography": "only if explicitly stated, otherwise omit or null"}},
      "fields": {{
        "field_name": {{
          "value": "explicit value or null",
          "status": "EXTRACTED | NOT_FOUND | AMBIGUOUS",
          "source_url": "source URL for EXTRACTED or AMBIGUOUS evidence",
          "source_snippet": "short exact supporting text for EXTRACTED only",
          "confidence": 0.0
        }}
      }}
    }}
  ]
}}

Rules:
- EXTRACTED requires an exact source_snippet copied from the chunk, including
  when the value is derived from the cited evidence.
- Put the chunk source URL on every EXTRACTED or AMBIGUOUS field.
- For every field in the runtime schema, return one field object.
- If evidence is missing, return value null and status NOT_FOUND.
- If evidence is unclear or conflicting inside this chunk, return value null and status AMBIGUOUS.
- Never invent object types or field names outside the runtime schema.
- It is valid to return an empty objects array.

Chunk source URL: {chunk.source_url}
Chunk ID: {chunk.chunk_id}

Chunk text:
\"\"\"{chunk.chunk_text}\"\"\"
""".strip()


def parse_extraction_response(
    raw_text: str,
    chunk: SemanticChunk,
    schema_config: SchemaConfig | None = None,
) -> list[ExtractedObjectPacket]:
    """Parse and sanitize Gemini extraction output for one chunk."""

    payload = json.loads(_extract_json_block(raw_text))
    objects = payload if isinstance(payload, list) else payload.get("objects", [])
    if not isinstance(objects, list):
        raise ValueError("extraction response must contain an objects list")

    packets: list[ExtractedObjectPacket] = []
    for item in objects:
        if not isinstance(item, dict):
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
            str(field_name): _parse_field(field_data, chunk.source_url)
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


def _parse_field(field_data: dict[str, Any], fallback_source_url: str) -> ExtractedField:
    status = str(field_data.get("status") or "NOT_FOUND").strip().upper()
    if status not in VALID_STATUSES:
        status = "AMBIGUOUS"

    if status == "EXTRACTED":
        snippet = field_data.get("source_snippet")
        if not isinstance(snippet, str) or not snippet.strip():
            return ExtractedField(
                value=None,
                status="AMBIGUOUS",
                source_url=_field_source_url(field_data, fallback_source_url),
                source_snippet=None,
                confidence=0.0,
            )
        confidence = field_data.get("confidence")
        return ExtractedField(
            value=field_data.get("value"),
            status="EXTRACTED",
            source_url=_field_source_url(field_data, fallback_source_url),
            source_snippet=snippet,
            confidence=_coerce_confidence(confidence),
        )

    source_url = _field_source_url(field_data, fallback_source_url) if status == "AMBIGUOUS" else None
    return ExtractedField(
        value=None,
        status=status,  # type: ignore[arg-type]
        source_url=source_url,
        source_snippet=field_data.get("source_snippet") if status == "AMBIGUOUS" else None,
        confidence=_coerce_confidence(field_data.get("confidence")) if status == "AMBIGUOUS" else None,
    )


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


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
    return f"Gemini extraction failed for {len(failures)} chunks. First error: {first}"


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


def _field_source_url(field_data: dict[str, Any], fallback_source_url: str) -> str:
    source_url = field_data.get("source_url")
    if isinstance(source_url, str) and source_url.strip():
        return source_url.strip()
    return fallback_source_url


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
