"""Raw Firecrawl document storage.

This stage keeps the original scraped text before any semantic processing. It
is intentionally domain-agnostic: source authority and query metadata are
copied from retrieval results when available, not inferred from brand logic.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

from core.db import DEFAULT_DB_PATH, connect, migrate, upsert_raw_documents
from core.schemas import RawDocument, RetrievedUrl, ScrapedUrlBlock, now_iso


MIN_WORDS = 100
WORD_RE = re.compile(r"\b[\w'-]+\b")


def store_firecrawl_output(
    blocks: list[ScrapedUrlBlock],
    *,
    entity_name: str | None = None,
    domain: str | None = None,
    retrieved_urls: list[RetrievedUrl] | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> list[RawDocument]:
    """Persist usable Firecrawl documents and return their normalized records.

    Pages under 100 words are skipped because they rarely contain enough
    explicit evidence for schema extraction. The operation is idempotent by
    URL hash, so reprocessing the same URL updates the row instead of creating
    duplicates.
    """

    retrieved_by_url = _retrieval_lookup(retrieved_urls or [])
    retrieved_at = now_iso()
    documents: list[RawDocument] = []

    for block in blocks:
        if block.scrape_status != "success" or not block.content:
            continue

        word_count = count_words(block.content)
        if word_count < MIN_WORDS:
            continue

        source = retrieved_by_url.get(block.url) or retrieved_by_url.get(block.canonical_url)
        documents.append(
            RawDocument(
                url=block.url,
                url_hash=hash_url(block.url),
                content=block.content,
                word_count=word_count,
                query_id=source.query_id if source else None,
                entity_name=entity_name,
                domain=domain,
                retrieved_at=retrieved_at,
                source_authority=source.score if source else None,
                metadata={
                    "canonical_url": block.canonical_url,
                    "title": block.title or (source.title if source else None),
                    "source_type": source.source_type if source else None,
                    "external_query_id": source.external_query_id if source else None,
                    "query": source.query if source else None,
                    "published_date": block.published_date,
                },
            )
        )

    conn = connect(db_path)
    try:
        migrate(conn)
        upsert_raw_documents(conn, documents)
    finally:
        conn.close()

    return documents


def hash_url(url: str) -> str:
    """Return the stable 16-character URL hash required by the pipeline."""

    return sha256(url.encode("utf-8")).hexdigest()[:16]


def count_words(text: str) -> int:
    """Count words in markdown or plain text."""

    return len(WORD_RE.findall(text))


def _retrieval_lookup(retrieved_urls: list[RetrievedUrl]) -> dict[str, RetrievedUrl]:
    lookup: dict[str, RetrievedUrl] = {}
    for item in retrieved_urls:
        lookup[item.url] = item
        lookup[item.canonical_url] = item
    return lookup

