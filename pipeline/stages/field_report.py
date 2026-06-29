"""Aggregate normalized packets into the final per-field evidence report.

This stage only reorganizes evidence that the extractor already grounded in
scraped chunks. It never invents values: a field with no EXTRACTED packet is
reported as ambiguous (unclear evidence seen) or not_found (searched, absent).
"""

from __future__ import annotations

import json
from typing import Any

from core.schemas import ExtractedField, FieldReport, FieldReportEntry, NormalizedObjectPacket
from pipeline.stages.extractor import SchemaConfig


def build_field_report(
    packets: list[NormalizedObjectPacket],
    schema_config: SchemaConfig,
    *,
    entity_name: str | None = None,
) -> FieldReport:
    """Merge per-chunk packets into one entry per schema field with sources."""

    field_paths = [
        field.name
        for object_type in schema_config.object_types
        for field in object_type.fields
    ]
    entries = [_build_entry(field_path, packets) for field_path in field_paths]
    return FieldReport(
        entity_name=entity_name,
        entries=entries,
        extracted_count=sum(1 for entry in entries if entry.status == "extracted"),
        ambiguous_count=sum(1 for entry in entries if entry.status == "ambiguous"),
        not_found_count=sum(1 for entry in entries if entry.status == "not_found"),
    )


def _build_entry(field_path: str, packets: list[NormalizedObjectPacket]) -> FieldReportEntry:
    category = field_path.split(".", 1)[0]
    extracted: list[ExtractedField] = []
    ambiguous_urls: list[str] = []

    for packet in packets:
        field = packet.fields.get(field_path)
        if field is None:
            continue
        if field.status == "EXTRACTED" and field.value is not None and field.source_url:
            extracted.append(field)
        elif field.status == "AMBIGUOUS" and field.source_url:
            ambiguous_urls.append(field.source_url)

    if extracted:
        groups: dict[str, list[ExtractedField]] = {}
        for field in extracted:
            groups.setdefault(_value_key(field.value), []).append(field)

        winning_key = max(
            groups,
            key=lambda k: (
                len({f.source_url for f in groups[k]}),
                max(f.confidence or 0.0 for f in groups[k]),
            ),
        )
        winning_group = groups[winning_key]
        best = max(winning_group, key=lambda f: f.confidence or 0.0)
        source_urls = sorted({f.source_url for f in winning_group if f.source_url})

        rejected_alternatives = []
        for key, group in groups.items():
            if key == winning_key:
                continue
            rej_best = max(group, key=lambda f: f.confidence or 0.0)
            rej_urls = sorted({f.source_url for f in group if f.source_url})
            rejected_alternatives.append({
                "value": rej_best.value,
                "source_urls": rej_urls,
                "reason": "lower_confidence_or_corroboration",
            })

        return FieldReportEntry(
            field_path=field_path,
            category=category,
            status="extracted",
            value=best.value,
            source_urls=source_urls,
            source_snippet=best.source_snippet,
            confidence=best.confidence,
            corroboration_count=len(source_urls),
            rejected_alternatives=rejected_alternatives,
        )

    if ambiguous_urls:
        return FieldReportEntry(
            field_path=field_path,
            category=category,
            status="ambiguous",
            source_urls=sorted(set(ambiguous_urls)),
        )

    return FieldReportEntry(field_path=field_path, category=category, status="not_found")


def _value_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
