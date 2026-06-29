import sqlite3
import requests

from core.db import connect, migrate
from pipeline.nodes.ingest_node import ingest_node
from pipeline.nodes.ingest_node import _target_fields_by_query_id
from pipeline.schema_config import FOCUSED_SCHEMA_FIELD_PATHS, default_arcguide_schema_config
from pipeline.stages.chunker import semantic_chunk
from pipeline.stages.extractor import (
    FieldDef,
    ObjectTypeDef,
    SchemaConfig,
    extract_from_chunks,
    select_informative_chunks,
)
from pipeline.stages.field_report import build_field_report
from pipeline.stages.normalizer import generate_identity_hash, normalize_packet
from pipeline.stages.raw_store import hash_url, store_firecrawl_output
from core.schemas import (
    ExtractedField,
    ExtractedObjectPacket,
    NormalizedObjectPacket,
    RawDocument,
    RetrievedUrl,
    ScrapedUrlBlock,
    SemanticChunk,
    SCHEMA_FIELD_PATHS,
    QueryGenerationOutput,
    SearchQuery,
    build_initial_state,
)


EXPECTED_FOCUSED_SCHEMA_FIELD_PATHS = (
    "program_basics.program_name",
    "program_basics.brand",
    "program_basics.industry",
    "program_basics.program_type",
    "program_basics.geography",
    "program_basics.membership_count",
    "earn_mechanics.base_earn_rate",
    "earn_mechanics.bonus_categories",
    "earn_mechanics.non_transactional_earn",
    "burn_mechanics.redemption_options",
    "burn_mechanics.redemption_thresholds",
    "burn_mechanics.point_value_cpp",
    "burn_mechanics.expiry_policy",
    "tier_system.tier_names",
    "tier_system.qualification_criteria",
    "tier_system.tier_benefits",
    "tier_system.qualification_period",
    "partnerships.partner_names",
    "partnerships.partnership_type",
    "partnerships.details",
    "digital_experience.mobile_app_available",
    "digital_experience.app_ratings",
    "digital_experience.personalization_features",
    "digital_experience.gamification_features",
    "member_sentiment.ratings",
    "member_sentiment.common_praise",
    "member_sentiment.common_complaints",
    "member_sentiment.sources_checked",
    "competitive_position.key_differentiators",
    "competitive_position.weaknesses",
    "competitive_position.closest_competitors",
)


def long_text(word: str, count: int) -> str:
    return " ".join([word] * count)


def test_raw_store_skips_short_pages_and_is_idempotent(tmp_path):
    db_path = tmp_path / "kobie.sqlite3"
    url = "https://example.com/a"
    block = ScrapedUrlBlock(url=url, canonical_url=url, content=long_text("evidence", 120))
    short = ScrapedUrlBlock(url="https://example.com/short", canonical_url="https://example.com/short", content="too short")
    retrieved = [
        RetrievedUrl(
            url=url,
            canonical_url=url,
            score=0.82,
            query="example query",
            query_id="query_1",
            source_type="official",
        )
    ]

    first = store_firecrawl_output([block, short], entity_name="Entity", domain="Any", retrieved_urls=retrieved, db_path=db_path)
    second = store_firecrawl_output([block, short], entity_name="Entity", domain="Any", retrieved_urls=retrieved, db_path=db_path)

    assert len(first) == 1
    assert second[0].url_hash == hash_url(url)
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM raw_documents").fetchone()[0] == 1
    finally:
        conn.close()


def test_semantic_chunk_splits_headings_and_oversized_sections():
    content = (
        "# Small\n"
        f"{long_text('tiny', 10)}\n\n"
        "# Big Section\n"
        f"{long_text('alpha', 800)}\n\n"
        f"{long_text('beta', 800)}\n\n"
        "# Normal Section\n"
        f"{long_text('gamma', 40)}"
    )
    document = RawDocument(
        url="https://example.com/doc",
        url_hash="abc",
        content=content,
        word_count=1650,
        query_id="query_1",
    )

    chunks = semantic_chunk([document], target_fields_by_query_id={"query_1": ["field_a"]})

    assert len(chunks) == 3
    assert all(chunk.target_fields == ["field_a"] for chunk in chunks)
    assert all(len(chunk.chunk_text.split()) <= 1505 for chunk in chunks)
    assert all("tiny" not in chunk.chunk_text for chunk in chunks)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def complete_text(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


class RateLimitedExtractionClient:
    def complete_text(self, prompt: str) -> str:
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError(
            "Gemini extraction is temporarily unavailable (429) for model gemini-2.5-flash.",
            response=response,
        )


def runtime_schema() -> SchemaConfig:
    return SchemaConfig(
        object_types=[
            ObjectTypeDef(
                object_type="Company",
                fields=[
                    FieldDef(name="name", description="Company name", identity=True),
                    FieldDef(name="employees", description="Employee count", value_type="number"),
                ],
            )
        ]
    )


def test_extractor_returns_packets_and_requires_snippets():
    chunk = SemanticChunk(
        chunk_id="chunk_1",
        source_url="https://example.com",
        chunk_text="Acme has 42 employees.",
    )
    raw = """
    {
      "objects": [
        {
          "object_type": "Company",
          "scope": {"geography": "US"},
          "fields": {
            "name": {"value": "Acme", "status": "EXTRACTED", "source_snippet": "Acme has 42 employees.", "confidence": 0.9},
            "employees": {"value": 42, "status": "EXTRACTED", "confidence": 0.8}
          }
        }
      ]
    }
    """

    packets = extract_from_chunks([chunk], runtime_schema(), client=FakeClient([raw]))

    assert packets[0].fields["name"].status == "EXTRACTED"
    assert packets[0].fields["name"].source_url == "https://example.com"
    assert packets[0].fields["employees"].status == "AMBIGUOUS"
    assert packets[0].fields["employees"].source_url == "https://example.com"
    assert packets[0].fields["employees"].value is None


def test_extractor_filters_unknown_schema_fields():
    chunk = SemanticChunk(
        chunk_id="chunk_1",
        source_url="https://example.com",
        chunk_text="Acme has 42 employees.",
    )
    raw = """
    {
      "objects": [
        {
          "object_type": "Company",
          "fields": {
            "name": {"value": "Acme", "status": "EXTRACTED", "source_snippet": "Acme has 42 employees.", "confidence": 0.9},
            "invented": {"value": "Nope", "status": "EXTRACTED", "source_snippet": "Acme has 42 employees.", "confidence": 0.9}
          }
        },
        {
          "object_type": "Unknown",
          "fields": {
            "name": {"value": "Bad", "status": "EXTRACTED", "source_snippet": "Bad", "confidence": 0.9}
          }
        }
      ]
    }
    """

    packets = extract_from_chunks([chunk], runtime_schema(), client=FakeClient([raw]))

    assert len(packets) == 1
    assert set(packets[0].fields) == {"name", "employees"}
    assert packets[0].fields["employees"].status == "NOT_FOUND"


def test_extractor_retries_parse_failure_once_and_then_returns_empty():
    chunk = SemanticChunk(chunk_id="chunk_1", source_url="https://example.com", chunk_text="Text")
    valid = '{"objects":[]}'

    assert extract_from_chunks([chunk], runtime_schema(), client=FakeClient(["not json", valid])) == []
    assert extract_from_chunks([chunk], runtime_schema(), client=FakeClient(["bad", "still bad"])) == []


def test_extractor_surfaces_provider_failures():
    chunk = SemanticChunk(
        chunk_id="chunk_1",
        source_url="https://example.com",
        chunk_text="Acme has 42 employees.",
    )

    try:
        extract_from_chunks([chunk], runtime_schema(), client=RateLimitedExtractionClient())
    except RuntimeError as exc:
        assert "Gemini extraction failed for 1 chunk batches" in str(exc)
        assert "temporarily unavailable (429)" in str(exc)
    else:
        raise AssertionError("Expected provider failure to be surfaced")


def test_chunk_filter_keeps_derivable_schema_signals_and_skips_boilerplate():
    useful = SemanticChunk(
        chunk_id="chunk_useful",
        source_url="https://example.com/useful",
        chunk_text=(
            "Acme Rewards has more than 2 million members. "
            "Gold tier members earn 5 points per dollar and can redeem rewards."
        ),
        target_fields=[],
    )
    boilerplate = SemanticChunk(
        chunk_id="chunk_noise",
        source_url="https://example.com/noise",
        chunk_text="Accept cookies. Privacy policy. Sign in to subscribe to our newsletter.",
        target_fields=[],
    )

    selected, skipped = select_informative_chunks(
        [boilerplate, useful],
        default_arcguide_schema_config(),
        program_name="Acme Rewards",
        brand="Acme",
        max_chunks=10,
    )

    assert [chunk.chunk_id for chunk in selected] == ["chunk_useful"]
    assert [chunk.chunk_id for chunk in skipped] == ["chunk_noise"]


def test_normalizer_preserves_snippet_and_hashes_identity():
    packet = ExtractedObjectPacket(
        object_type="Company",
        source_url="https://example.com",
        chunk_id="chunk_1",
        scope={"geography": " US "},
        fields={
            "name": ExtractedField(value=" Acme ", status="EXTRACTED", source_snippet=" Acme ", confidence=0.9),
            "employees": ExtractedField(value="42", status="EXTRACTED", source_snippet="42 employees", confidence=0.9),
            "missing": ExtractedField(value=None, status="NOT_FOUND"),
        },
    )

    first = normalize_packet(packet, runtime_schema())
    second = normalize_packet(packet, runtime_schema())

    assert first.fields["name"].value == "acme"
    assert first.fields["name"].source_snippet == " Acme "
    assert first.fields["employees"].value == 42
    assert first.identity_hash == second.identity_hash


def test_generate_identity_hash_uses_uuid_when_no_identity_fields(monkeypatch):
    packet = ExtractedObjectPacket(
        object_type="Company",
        source_url="https://example.com",
        chunk_id="chunk_1",
        fields={"name": ExtractedField(value=None, status="NOT_FOUND")},
    )

    identity_hash = generate_identity_hash(packet, runtime_schema())

    assert len(identity_hash) == 24


def test_ingest_node_outputs_and_persists_normalized_packets(tmp_path):
    db_path = tmp_path / "kobie.sqlite3"
    state = build_initial_state("Acme")
    state["program_name"] = "Acme"
    state["domain"] = "SaaS"
    state["schema_config"] = runtime_schema().model_dump()
    state["scraped_blocks"] = [
        ScrapedUrlBlock(
            url="https://example.com/acme",
            canonical_url="https://example.com/acme",
            content="# Acme\n\nAcme has 42 employees. " + long_text("evidence", 120),
        )
    ]

    raw = """
    {"objects":[{"object_type":"Company","scope":{"geography":"US"},"fields":{"name":{"value":"Acme","status":"EXTRACTED","source_snippet":"Acme has 42 employees.","confidence":0.9}}}]}
    """
    update = ingest_node(state, extractor_client=FakeClient([raw]), db_path=db_path)

    assert update["normalized_packets"]
    assert update["extracted_packets"][0].fields["employees"].status == "NOT_FOUND"
    assert update["extracted_packets"][0].fields["employees"].value is None
    conn = connect(db_path)
    try:
        migrate(conn)
        assert conn.execute("SELECT COUNT(*) FROM normalized_packets").fetchone()[0] == 1
    finally:
        conn.close()


def test_default_arcguide_schema_contains_focused_report_fields():
    config = default_arcguide_schema_config()
    field_names = {field.name for object_type in config.object_types for field in object_type.fields}

    assert FOCUSED_SCHEMA_FIELD_PATHS == EXPECTED_FOCUSED_SCHEMA_FIELD_PATHS
    assert field_names == set(FOCUSED_SCHEMA_FIELD_PATHS)
    assert field_names < set(SCHEMA_FIELD_PATHS)
    assert "program_basics.program_name" in config.object_types[0].identity_fields


def test_ingest_node_uses_default_arcguide_schema_when_state_has_none(tmp_path):
    db_path = tmp_path / "kobie.sqlite3"
    state = build_initial_state("Acme Rewards")
    state["program_name"] = "Acme Rewards"
    state["domain"] = "Retail"
    state["scraped_blocks"] = [
        ScrapedUrlBlock(
            url="https://example.com/acme",
            canonical_url="https://example.com/acme",
            content="# Acme Rewards\n\nAcme Rewards is operated by Acme. " + long_text("evidence", 120),
        )
    ]
    raw = """
    {"objects":[{"object_type":"loyalty_intelligence","scope":{"geography":"US"},"fields":{"program_basics.program_name":{"value":"Acme Rewards","status":"EXTRACTED","source_snippet":"Acme Rewards is operated by Acme.","confidence":0.9}}}]}
    """

    update = ingest_node(
        state,
        extractor_client=FakeClient([raw]),
        db_path=db_path,
    )

    assert update["normalized_packets"]
    assert update["extraction_chunks"]
    assert "source_url" in update["normalized_packets"][0].fields["program_basics.program_name"].model_dump()
    assert "program_basics.program_name" in update["semantic_chunks"][0].target_fields


def test_extractor_batches_chunks_into_single_call():
    chunk_a = SemanticChunk(
        chunk_id="chunk_1",
        source_url="https://example.com/a",
        chunk_text="Acme has 42 employees.",
    )
    chunk_b = SemanticChunk(
        chunk_id="chunk_2",
        source_url="https://example.com/b",
        chunk_text="Beta Corp employs 7 staff employees.",
    )
    raw = """
    {
      "objects": [
        {"chunk_id": "chunk_1", "object_type": "Company", "fields": {"name": {"value": "Acme", "status": "EXTRACTED", "source_snippet": "Acme has 42 employees.", "confidence": 0.9}}},
        {"chunk_id": "chunk_2", "object_type": "Company", "fields": {"name": {"value": "Beta Corp", "status": "EXTRACTED", "source_snippet": "Beta Corp employs 7 staff employees.", "confidence": 0.8}}}
      ]
    }
    """
    client = FakeClient([raw])

    packets = extract_from_chunks([chunk_a, chunk_b], runtime_schema(), client=client)

    assert len(client.prompts) == 1
    assert len(packets) == 2
    by_chunk = {packet.chunk_id: packet for packet in packets}
    assert by_chunk["chunk_1"].fields["name"].source_url == "https://example.com/a"
    assert by_chunk["chunk_2"].fields["name"].source_url == "https://example.com/b"


def test_extractor_rejects_snippets_not_present_in_chunk():
    chunk = SemanticChunk(
        chunk_id="chunk_1",
        source_url="https://example.com",
        chunk_text="Acme has 42 employees.",
    )
    raw = """
    {
      "objects": [
        {
          "object_type": "Company",
          "fields": {
            "name": {"value": "Acme", "status": "EXTRACTED", "source_snippet": "Acme dominates the global market.", "confidence": 0.95}
          }
        }
      ]
    }
    """

    packets = extract_from_chunks([chunk], runtime_schema(), client=FakeClient([raw]))

    assert packets[0].fields["name"].status == "AMBIGUOUS"
    assert packets[0].fields["name"].value is None
    assert packets[0].fields["name"].source_snippet is None
    assert packets[0].fields["name"].source_url == "https://example.com"


def test_chunker_merges_small_sections_and_strips_boilerplate():
    content = "\n\n".join(
        ["Sign In", "![logo](https://example.com/logo.png)"]
        + [
            f"# Benefit {index}\n[Tier details](https://example.com/{index}) " + long_text("perk", 15)
            for index in range(6)
        ]
    )
    document = RawDocument(url="https://example.com/benefits", url_hash="abc", content=content, word_count=200)

    chunks = semantic_chunk([document])

    assert len(chunks) == 1
    assert "Sign In" not in chunks[0].chunk_text
    assert "https://example.com/logo.png" not in chunks[0].chunk_text
    assert "Tier details" in chunks[0].chunk_text
    assert "](https://example.com/0)" not in chunks[0].chunk_text
    assert all(f"Benefit {index}" in chunks[0].chunk_text for index in range(6))


def test_select_informative_chunks_prefers_field_coverage_over_score():
    schema = SchemaConfig(
        object_types=[
            ObjectTypeDef(
                object_type="Program",
                fields=[
                    FieldDef(name="earn_rate", description="Accrual amount per dollar"),
                    FieldDef(name="expiry_policy", description="Validity duration before forfeiture"),
                ],
            )
        ]
    )
    earn_a = SemanticChunk(
        chunk_id="earn_a",
        source_url="https://a.example",
        chunk_text="Members earn 5 points per dollar spent on purchases. " * 3,
    )
    earn_b = SemanticChunk(
        chunk_id="earn_b",
        source_url="https://b.example",
        chunk_text="Members earn 3 points per dollar spent on purchases. " * 2,
    )
    expiry = SemanticChunk(
        chunk_id="expiry",
        source_url="https://c.example",
        chunk_text="Points expire after 24 months of inactivity under the expiry policy.",
    )

    selected, skipped = select_informative_chunks([earn_a, earn_b, expiry], schema, max_chunks=2, min_score=0)

    assert {chunk.chunk_id for chunk in selected} == {"earn_a", "expiry"}
    assert [chunk.chunk_id for chunk in skipped] == ["earn_b"]


def test_field_report_aggregates_sources_and_statuses():
    packet_a = NormalizedObjectPacket(
        object_type="Company",
        source_url="https://a.example",
        chunk_id="c1",
        identity_hash="h1",
        fields={
            "name": ExtractedField(
                value="acme", status="EXTRACTED", source_url="https://a.example", source_snippet="Acme", confidence=0.8
            ),
            "employees": ExtractedField(value=None, status="AMBIGUOUS", source_url="https://a.example"),
        },
    )
    packet_b = NormalizedObjectPacket(
        object_type="Company",
        source_url="https://b.example",
        chunk_id="c2",
        identity_hash="h2",
        fields={
            "name": ExtractedField(
                value="acme", status="EXTRACTED", source_url="https://b.example", source_snippet="Acme", confidence=0.6
            ),
        },
    )
    packet_c = NormalizedObjectPacket(
        object_type="Company",
        source_url="https://c.example",
        chunk_id="c3",
        identity_hash="h3",
        fields={
            "name": ExtractedField(
                value="acme inc",
                status="EXTRACTED",
                source_url="https://c.example",
                source_snippet="Acme Inc",
                confidence=0.99,
            ),
        },
    )

    report = build_field_report([packet_a, packet_b, packet_c], runtime_schema(), entity_name="Acme")

    by_path = {entry.field_path: entry for entry in report.entries}
    assert by_path["name"].status == "extracted"
    assert by_path["name"].value == "acme"
    assert by_path["name"].source_urls == ["https://a.example", "https://b.example"]
    assert by_path["name"].corroboration_count == 2
    assert by_path["employees"].status == "ambiguous"
    assert by_path["employees"].source_urls == ["https://a.example"]
    assert report.extracted_count == 1
    assert report.ambiguous_count == 1
    assert report.not_found_count == 0


def test_ingest_node_returns_field_report_with_sources(tmp_path):
    db_path = tmp_path / "kobie.sqlite3"
    state = build_initial_state("Acme")
    state["program_name"] = "Acme"
    state["domain"] = "SaaS"
    state["schema_config"] = runtime_schema().model_dump()
    state["scraped_blocks"] = [
        ScrapedUrlBlock(
            url="https://example.com/acme",
            canonical_url="https://example.com/acme",
            content="# Acme\n\nAcme has 42 employees. " + long_text("evidence", 120),
        )
    ]
    raw = """
    {"objects":[{"object_type":"Company","fields":{"name":{"value":"Acme","status":"EXTRACTED","source_snippet":"Acme has 42 employees.","confidence":0.9}}}]}
    """

    update = ingest_node(state, extractor_client=FakeClient([raw]), db_path=db_path)

    report = update["field_report"]
    by_path = {entry.field_path: entry for entry in report.entries}
    assert by_path["name"].status == "extracted"
    assert by_path["name"].source_urls == ["https://example.com/acme"]
    assert by_path["employees"].status == "not_found"


def test_query_field_aliases_expand_to_focused_schema_paths():
    state = build_initial_state("Acme")
    query = SearchQuery(query="Acme point value tier structure", source_type="official")
    state["query_generation_result"] = QueryGenerationOutput(
        detected_category="Retail",
        query_strategy_summary="test",
        field_query_map={"point_value": [query.query_id], "tier_structure": [query.query_id]},
        queries=[query],
    )
    fields = _target_fields_by_query_id(state, default_arcguide_schema_config())

    assert fields[query.query_id] == [
        "burn_mechanics.point_value_cpp",
        "tier_system.qualification_criteria",
        "tier_system.qualification_period",
        "tier_system.tier_benefits",
        "tier_system.tier_names",
    ]
