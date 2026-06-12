"""Normalize extracted packets and assign identity hashes."""

from __future__ import annotations

from hashlib import sha256
import json
import logging
import re
from typing import Any
from uuid import uuid4

from schemas import ExtractedField, ExtractedObjectPacket, NormalizedObjectPacket, now_iso
from .extractor import SchemaConfig


LOGGER = logging.getLogger(__name__)
NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def normalize_packet(packet: ExtractedObjectPacket, schema_config: SchemaConfig) -> NormalizedObjectPacket:
    """Normalize extracted values while preserving source evidence verbatim."""

    normalized_fields: dict[str, ExtractedField] = {}
    for field_name, field_value in packet.fields.items():
        if field_value.status == "EXTRACTED":
            normalized_fields[field_name] = field_value.model_copy(
                update={"value": _normalize_value(field_value.value)}
            )
        else:
            normalized_fields[field_name] = field_value

    normalized_packet = NormalizedObjectPacket(
        object_type=packet.object_type.strip().lower(),
        fields=normalized_fields,
        source_url=packet.source_url,
        chunk_id=packet.chunk_id,
        scope=_normalize_scope(packet.scope),
        identity_hash="",
        normalized_at=now_iso(),
    )
    return normalized_packet.model_copy(
        update={"identity_hash": generate_identity_hash(normalized_packet, schema_config)}
    )


def generate_identity_hash(packet: ExtractedObjectPacket, schema_config: SchemaConfig) -> str:
    """Generate a deterministic identity hash from extracted identity fields."""

    object_def = schema_config.object_type(packet.object_type)
    identity_fields = object_def.identity_fields if object_def else []
    identity_values: dict[str, Any] = {}

    for field_name in identity_fields:
        field_value = packet.fields.get(field_name)
        if field_value and field_value.status == "EXTRACTED":
            identity_values[field_name] = field_value.value

    geography = packet.scope.get("geography") if isinstance(packet.scope, dict) else None
    if geography:
        identity_values["scope.geography"] = geography

    if not identity_values:
        LOGGER.warning("No extracted identity fields for object_type=%s; generated UUID identity hash.", packet.object_type)
        return uuid4().hex[:24]

    payload = {
        "object_type": packet.object_type.strip().lower(),
        "identity": identity_values,
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()[:24]


def _normalize_scope(scope: dict[str, Any]) -> dict[str, Any]:
    return {str(key).strip().lower(): _normalize_value(value) for key, value in scope.items()}


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if NUMERIC_RE.fullmatch(stripped):
            return float(stripped) if "." in stripped else int(stripped)
        return stripped.lower()
    if isinstance(value, list):
        normalized = [_normalize_value(item) for item in value]
        deduped = {_stable_key(item): item for item in normalized}
        return [deduped[key] for key in sorted(deduped)]
    if isinstance(value, dict):
        return {str(key).strip().lower(): _normalize_value(item) for key, item in value.items()}
    return value


def _stable_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)

