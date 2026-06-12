"""Semantic markdown chunking.

The chunker uses document structure only. It does not know about brands,
domains, loyalty programs, or target schemas beyond copying optional
target-field hints through to downstream extraction.
"""

from __future__ import annotations

from hashlib import sha256
import re

from schemas import RawDocument, SemanticChunk
from .raw_store import count_words


MIN_SECTION_WORDS = 30
MAX_CHUNK_WORDS = 1500
HEADING_RE = re.compile(r"(?m)^(#{1,6}\s+.+)$")


def semantic_chunk(
    documents: list[RawDocument],
    *,
    target_fields_by_query_id: dict[str, list[str]] | None = None,
    default_target_fields: list[str] | None = None,
) -> list[SemanticChunk]:
    """Split raw markdown documents into evidence-sized chunks."""

    target_fields_by_query_id = target_fields_by_query_id or {}
    default_target_fields = default_target_fields or []
    chunks: list[SemanticChunk] = []

    for document in documents:
        target_fields = target_fields_by_query_id.get(document.query_id or "", default_target_fields)
        chunk_index = 0
        for section in _split_on_headings(document.content):
            if count_words(section) < MIN_SECTION_WORDS:
                continue
            for part in _split_oversized_section(section):
                if count_words(part) < MIN_SECTION_WORDS:
                    continue
                chunk_id = _chunk_id(document.url, chunk_index, part)
                chunks.append(
                    SemanticChunk(
                        chunk_id=chunk_id,
                        chunk_text=part,
                        source_url=document.url,
                        target_fields=target_fields,
                    )
                )
                chunk_index += 1

    return chunks


def _split_on_headings(markdown: str) -> list[str]:
    matches = list(HEADING_RE.finditer(markdown))
    if not matches:
        return [markdown.strip()] if markdown.strip() else []

    sections: list[str] = []
    preface = markdown[: matches[0].start()].strip()
    if preface:
        sections.append(preface)

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        section = markdown[match.start() : end].strip()
        if section:
            sections.append(section)
    return sections


def _split_oversized_section(section: str) -> list[str]:
    if count_words(section) <= MAX_CHUNK_WORDS:
        return [section.strip()]

    parts: list[str] = []
    current: list[str] = []
    current_words = 0

    for paragraph in re.split(r"\n\s*\n", section):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        paragraph_words = count_words(paragraph)
        if current and current_words + paragraph_words > MAX_CHUNK_WORDS:
            parts.append("\n\n".join(current).strip())
            current = []
            current_words = 0
        if paragraph_words > MAX_CHUNK_WORDS:
            parts.extend(_split_long_paragraph(paragraph))
            continue
        current.append(paragraph)
        current_words += paragraph_words

    if current:
        parts.append("\n\n".join(current).strip())
    return parts


def _split_long_paragraph(paragraph: str) -> list[str]:
    words = paragraph.split()
    return [" ".join(words[index : index + MAX_CHUNK_WORDS]) for index in range(0, len(words), MAX_CHUNK_WORDS)]


def _chunk_id(source_url: str, chunk_index: int, chunk_text: str) -> str:
    raw = f"{source_url}\n{chunk_index}\n{chunk_text}".encode("utf-8")
    return sha256(raw).hexdigest()[:24]
