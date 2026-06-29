"""Normalize extracted packets and assign identity hashes."""

from __future__ import annotations

from hashlib import sha256
import json
import logging
import re
from typing import Any
from uuid import uuid4

from core.schemas import ExtractedField, ExtractedObjectPacket, NormalizedObjectPacket, now_iso
from .extractor import SchemaConfig


LOGGER = logging.getLogger(__name__)
NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")

# Matches "City, CC" pattern (e.g. "Dallas, US", "Mumbai, IN") — never a valid program scope.
_CITY_COUNTRY_RE = re.compile(r"^[\w\s\-]+,\s*[A-Z]{2}$")

# Non-member count nouns that appear in the same sentence as large numbers in IR filings.
_NON_MEMBER_COUNT_RE = re.compile(
    r"\b(rooms?|propert(?:y|ies)|hotels?|stores?|branch(?:es)?|ATMs?|fleet|"
    r"destinations?|flights?|aircraft|outlets?|locations?)\b",
    re.IGNORECASE,
)

# Phrases that describe ELITE STATUS validity, not point expiry.
_STATUS_VALIDITY_RE = re.compile(
    r"\b(calendar year in which you earned|valid for the rest of the calendar year|"
    r"additional \d+ months after that|status is valid|earned it and an additional)\b",
    re.IGNORECASE,
)

# Phrases that describe genuine POINT expiry (inactivity-based).
_POINT_EXPIRY_RE = re.compile(
    r"\b(inactiv|no earn|no burn|no activity|earning or redeeming|account activity)\b",
    re.IGNORECASE,
)


def normalize_packet(packet: ExtractedObjectPacket, schema_config: SchemaConfig) -> NormalizedObjectPacket:
    """Normalize extracted values while preserving source evidence verbatim."""

    normalized_fields: dict[str, ExtractedField] = {}
    for field_name, field_value in packet.fields.items():
        if field_value.status == "EXTRACTED":
            normalized = field_value.model_copy(update={"value": _normalize_value(field_value.value)})
            normalized_fields[field_name] = _validate_extracted_field(field_name, normalized)
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


def _validate_extracted_field(field_name: str, field: ExtractedField) -> ExtractedField:
    """Downgrade implausible extracted values to AMBIGUOUS before they enter the field report.

    These rules fire on structural patterns that are universally wrong regardless of the
    program being researched — they do not encode Marriott-specific knowledge.
    """

    if field.status != "EXTRACTED" or field.value is None:
        return field

    value_str = str(field.value).strip()
    snippet = field.source_snippet or ""

    if field_name == "program_basics.geography":
        # A city+country-code pattern (e.g. "Dallas, US") is a member or property location,
        # never the program's operational footprint.
        if _CITY_COUNTRY_RE.match(value_str):
            LOGGER.warning(
                "geography value %r looks like a city location, not program scope — "
                "downgrading to AMBIGUOUS",
                value_str,
            )
            return field.model_copy(update={"status": "AMBIGUOUS", "confidence": 0.0})

    elif field_name == "program_basics.membership_count":
        # IR filings mention room/property/store counts alongside member counts.
        # If the supporting snippet contains a non-member count noun, the extractor
        # grabbed the wrong number.
        if _NON_MEMBER_COUNT_RE.search(snippet):
            LOGGER.warning(
                "membership_count snippet contains non-member count noun — "
                "downgrading value %r to AMBIGUOUS",
                value_str,
            )
            return field.model_copy(update={"status": "AMBIGUOUS", "confidence": 0.0})

    elif field_name == "burn_mechanics.expiry_policy":
        # Elite status validity phrases appear on the same T&C pages as point expiry.
        # If the snippet describes status duration without mentioning inactivity, it is
        # the wrong validity concept.
        if _STATUS_VALIDITY_RE.search(snippet) and not _POINT_EXPIRY_RE.search(snippet):
            LOGGER.warning(
                "expiry_policy snippet describes status validity, not point inactivity expiry — "
                "downgrading value %r to AMBIGUOUS",
                value_str,
            )
            return field.model_copy(update={"status": "AMBIGUOUS", "confidence": 0.0})

    return field

