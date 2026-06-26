"""LangGraph-compatible post-Firecrawl ingestion node."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import DEFAULT_DB_PATH, connect, migrate, upsert_normalized_packets
from schemas import AgentState, NormalizedObjectPacket, PipelineError, now_iso
from pipeline.schema_config import FIELD_ALIASES, default_arcguide_schema_config
from pipeline.stages.chunker import semantic_chunk
from pipeline.stages.extractor import ExtractionClient, SchemaConfig, extract_from_chunks, select_informative_chunks
from pipeline.stages.field_report import build_field_report
from pipeline.stages.normalizer import normalize_packet
from pipeline.stages.raw_store import store_firecrawl_output


def ingest_node(
    state: AgentState,
    *,
    schema_config: SchemaConfig | dict[str, Any] | None = None,
    extractor_client: ExtractionClient | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Run raw store, chunking, extraction, normalization, and packet storage."""

    firecrawl_blocks = state.get("scraped_blocks", [])
    additional_blocks = list(state.get("additional_blocks") or [])
    # additional_blocks (Wikipedia, etc.) go first so extraction sees high-quality
    # structured text before noisy scraped content.
    blocks = [*additional_blocks, *firecrawl_blocks]
    if not blocks:
        return {
            "errors": [
                *state["errors"],
                PipelineError(stage="ingest", message="Ingest skipped because no Firecrawl blocks exist."),
            ],
            "updated_at": now_iso(),
        }

    config_payload = schema_config if schema_config is not None else state.get("schema_config")
    config = (
        config_payload
        if isinstance(config_payload, SchemaConfig)
        else SchemaConfig.model_validate(config_payload)
        if config_payload
        else default_arcguide_schema_config()
    )

    raw_documents = store_firecrawl_output(
        blocks,
        entity_name=state.get("program_name"),
        domain=state.get("domain"),
        retrieved_urls=state.get("retrieved_urls", []),
        db_path=db_path,
    )
    chunks = semantic_chunk(
        raw_documents,
        target_fields_by_query_id=_target_fields_by_query_id(state, config),
        default_target_fields=_all_schema_fields(config),
    )
    extraction_chunks, skipped_chunks = select_informative_chunks(
        chunks,
        config,
        program_name=state.get("program_name"),
        brand=state.get("brand"),
    )

    extraction_context = _build_extraction_context(state)
    extracted_packets = extract_from_chunks(
        extraction_chunks,
        config,
        client=extractor_client,
        extraction_context=extraction_context,
    )
    normalized_packets = [normalize_packet(packet, config) for packet in extracted_packets]
    prefetched_ratings = state.get("prefetched_app_ratings")
    if prefetched_ratings is not None:
        normalized_packets = [prefetched_ratings, *normalized_packets]
    persist_normalized_packets(normalized_packets, db_path=db_path)
    field_report = build_field_report(normalized_packets, config, entity_name=state.get("program_name"))

    return {
        "raw_documents": raw_documents,
        "semantic_chunks": chunks,
        "extraction_chunks": extraction_chunks,
        "skipped_chunks": skipped_chunks,
        "extracted_packets": extracted_packets,
        "normalized_packets": normalized_packets,
        "field_report": field_report,
        "updated_at": now_iso(),
    }


def persist_normalized_packets(
    packets: list[NormalizedObjectPacket],
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    """Persist normalized packets to SQLite."""

    conn = connect(db_path)
    try:
        migrate(conn)
        upsert_normalized_packets(conn, packets)
    finally:
        conn.close()


def _target_fields_by_query_id(state: AgentState, schema_config: SchemaConfig) -> dict[str, list[str]]:
    result = state.get("query_generation_result")
    if not result:
        return {}

    valid_fields = {
        field.name
        for object_type in schema_config.object_types
        for field in object_type.fields
    }
    fields_by_query: dict[str, list[str]] = {}
    for field_name, query_ids in result.field_query_map.items():
        resolved_fields = _resolve_target_fields(field_name, valid_fields)
        if not resolved_fields:
            continue
        for query_id in query_ids:
            fields_by_query.setdefault(query_id, []).extend(resolved_fields)
    return {query_id: sorted(set(fields)) for query_id, fields in fields_by_query.items()}


def _all_schema_fields(schema_config: SchemaConfig) -> list[str]:
    return sorted(
        {
            field.name
            for object_type in schema_config.object_types
            for field in object_type.fields
        }
    )


def _resolve_target_fields(field_name: str, valid_fields: set[str]) -> list[str]:
    normalized = field_name.strip()
    if normalized in valid_fields:
        return [normalized]
    alias_key = normalized.lower().replace(" ", "_")
    return [field for field in FIELD_ALIASES.get(alias_key, ()) if field in valid_fields]


def _build_extraction_context(state: AgentState) -> dict[str, Any]:
    """Build the context dict passed to the extraction prompt for every batch in this run."""
    ctx: dict[str, Any] = {"reference_year": datetime.now(timezone.utc).year}
    for key in ("program_name", "brand", "program_subtype"):
        value = state.get(key)
        if value is not None:
            ctx[key] = value
    result = state.get("query_generation_result")
    if result and result.priority_fields:
        ctx["priority_fields"] = result.priority_fields
    return ctx
