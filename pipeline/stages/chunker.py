"""Semantic markdown chunking.

The chunker uses document structure only. It does not know about brands,
domains, loyalty programs, or target schemas beyond copying optional
target-field hints through to downstream extraction.

Small adjacent sections are merged into target-sized chunks instead of being
dropped, so short evidence rows (benefit tables, tier bullets) survive while
the total chunk count stays low enough to keep extraction calls cheap.
"""

from __future__ import annotations

from hashlib import sha256
import re

from core.schemas import RawDocument, SemanticChunk
from .raw_store import count_words


MIN_SECTION_WORDS = 30
TARGET_CHUNK_WORDS = 600
MAX_CHUNK_WORDS = 1500
HEADING_RE = re.compile(r"(?m)^(#{1,6}\s+.+)$")
IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK_MD_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

# Short navigation/consent lines stripped before chunking. Only lines that are
# both short and matching a pattern are removed so real evidence sentences
# mentioning these phrases are preserved.
BOILERPLATE_LINE_PATTERNS = (
    "accept cookies",
    "cookie settings",
    "privacy policy",
    "terms of use",
    "all rights reserved",
    "skip to content",
    "skip to main content",
    "enable javascript",
    "subscribe",
    "newsletter",
    "sign in",
    "log in",
    "join now",
    "advertiser disclosure",
    "open menu",
    "close alert banner",
)
MAX_BOILERPLATE_LINE_WORDS = 8


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
        source_type = document.metadata.get("source_type") if document.metadata else None
        chunk_index = 0
        sections: list[str] = []
        for section in _split_on_headings(strip_boilerplate(document.content)):
            sections.extend(_split_oversized_section(section))
        for part in _merge_small_sections(sections):
            if count_words(part) < MIN_SECTION_WORDS:
                continue
            chunk_id = _chunk_id(document.url, chunk_index, part)
            chunks.append(
                SemanticChunk(
                    chunk_id=chunk_id,
                    chunk_text=part,
                    source_url=document.url,
                    target_fields=target_fields,
                    source_type=source_type,
                    query_id=document.query_id,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

    return chunks


def strip_boilerplate(markdown: str) -> str:
    """Remove markdown noise that carries no extractable evidence."""

    text = IMAGE_MD_RE.sub("", markdown)
    text = LINK_MD_RE.sub(r"\1", text)
    kept_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and len(stripped.split()) <= MAX_BOILERPLATE_LINE_WORDS:
            lowered = stripped.lower()
            if any(pattern in lowered for pattern in BOILERPLATE_LINE_PATTERNS):
                continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


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


def _merge_small_sections(sections: list[str]) -> list[str]:
    """Pack adjacent sections into target-sized chunks to cut chunk count."""

    merged: list[str] = []
    current: list[str] = []
    current_words = 0

    for section in sections:
        section_words = count_words(section)
        if current and current_words + section_words > TARGET_CHUNK_WORDS:
            merged.append("\n\n".join(current).strip())
            current = []
            current_words = 0
        current.append(section)
        current_words += section_words

    if current:
        merged.append("\n\n".join(current).strip())
    return merged


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
