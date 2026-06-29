import pipeline.graph as graph
from core.schemas import (
    FirecrawlScrapeOutput,
    QueryGenerationOutput,
    RetrievalOutput,
    RetrievedUrl,
    ScrapedUrlBlock,
    SearchQuery,
    ValidationResult,
)


def resolved_validation_result():
    return ValidationResult.model_validate(
        {
            "status": "resolved",
            "confidence": 0.95,
            "identity": {
                "raw_input": "Air India",
                "program_name": "Air India Maharaja Club",
                "brand": "Air India",
                "domain": "Airline",
                "country_or_region": "India",
                "confidence": 0.95,
                "status": "resolved",
            },
        }
    )


def fake_query_output():
    return QueryGenerationOutput(
        detected_category="Airline",
        query_strategy_summary="Prioritize valuation, partners, and sentiment.",
        priority_fields=["Point Value", "Partner Names"],
        queries=[
            SearchQuery(
                query="Air India Maharaja Club points value partners terms",
                source_type="valuation",
            )
        ],
    )


def fake_retrieval_output(queries):
    return RetrievalOutput(
        total_queries=len(queries),
        requested_results_per_query=5,
        raw_result_count=1,
        unique_result_count=1,
        urls=[
            RetrievedUrl(
                url="https://example.com/program",
                canonical_url="https://example.com/program",
                title="Program",
                score=0.91,
                query=queries[0].query,
                query_id=queries[0].query_id,
                source_type=queries[0].source_type,
            )
        ],
    )


def fake_firecrawl_output(urls):
    return FirecrawlScrapeOutput(
        total_urls=len(urls),
        successful_scrapes=1,
        failed_scrapes=0,
        blocks=[
            ScrapedUrlBlock(
                url=urls[0].url,
                canonical_url=urls[0].canonical_url,
                content="# Air India Maharaja Club\n\nProgram terms and benefits.",
            )
        ],
    )


def test_graph_routes_resolved_validator_output_to_query_generator(monkeypatch):
    monkeypatch.setattr(graph, "validate_conversation", lambda messages: resolved_validation_result())
    monkeypatch.setattr(graph, "generate_queries", lambda identity: fake_query_output())
    monkeypatch.setattr(graph, "retrieve_urls", lambda queries: fake_retrieval_output(queries))
    monkeypatch.setattr(graph, "scrape_retrieved_urls", lambda urls, on_progress=None: fake_firecrawl_output(urls))

    state = graph.run_validation_chat([{"role": "user", "content": "Air India"}])

    assert state["validation_result"].status == "resolved"
    assert state["program_name"] == "Air India Maharaja Club"
    assert state["domain"] == "Airline"
    assert state["query_generation_result"] is not None
    assert state["search_queries"]
    assert state["retrieval_result"] is not None
    assert state["retrieved_urls"]
    assert state["firecrawl_result"] is not None
    assert state["scraped_blocks"]


def test_query_generator_can_run_explicitly(monkeypatch):
    monkeypatch.setattr(graph, "validate_conversation", lambda messages: resolved_validation_result())
    monkeypatch.setattr(graph, "generate_queries", lambda identity: fake_query_output())
    monkeypatch.setattr(graph, "retrieve_urls", lambda queries: fake_retrieval_output(queries))
    monkeypatch.setattr(graph, "scrape_retrieved_urls", lambda urls, on_progress=None: fake_firecrawl_output(urls))

    state = graph.run_validation_chat([{"role": "user", "content": "Air India"}])
    state = graph.run_query_generation(state)

    assert state["search_queries"]


def test_firecrawl_url_selection_prioritizes_high_value_sources():
    urls = [
        RetrievedUrl(url="https://forum.example", canonical_url="https://forum.example", score=1.0, query="q", source_type="forums"),
        RetrievedUrl(url="https://official.example", canonical_url="https://official.example", score=0.4, query="q", source_type="official"),
        RetrievedUrl(url="https://terms.example", canonical_url="https://terms.example", score=0.8, query="q", source_type="terms"),
    ]

    selected = graph.select_urls_for_firecrawl(urls)

    # All URLs are returned; high-priority source types appear first.
    assert len(selected) == 3
    assert [item.url for item in selected[:2]] == ["https://official.example", "https://terms.example"]
    assert selected[-1].url == "https://forum.example"


def test_firecrawl_url_selection_covers_every_query_before_repeating():
    def retrieved(url, score, query_id, source_type):
        return RetrievedUrl(url=url, canonical_url=url, score=score, query="q", query_id=query_id, source_type=source_type)

    urls = [
        retrieved("https://official.example/1", 0.95, "q_official", "official"),
        retrieved("https://official.example/2", 0.94, "q_official", "official"),
        retrieved("https://official.example/3", 0.93, "q_official", "official"),
        retrieved("https://official.example/4", 0.92, "q_official", "official"),
        retrieved("https://forum.example/1", 0.80, "q_forum", "forum"),
        retrieved("https://review.example/1", 0.85, "q_review", "review"),
        retrieved("https://financial.example/1", 0.90, "q_financial", "financial"),
    ]

    selected = graph.select_urls_for_firecrawl(urls)

    # All 7 URLs are returned in priority order.
    assert len(selected) == 7
    # The first 4 positions cover all four distinct queries (round-robin interleaving).
    assert {item.query_id for item in selected[:4]} == {"q_official", "q_forum", "q_review", "q_financial"}
    assert selected[0].url == "https://official.example/1"


def test_graph_stops_after_input_validator_when_clarification_needed(monkeypatch):
    def fake_validate_conversation(messages):
        return ValidationResult.model_validate(
            {
                "status": "needs_clarification",
                "confidence": 0.72,
                "follow_up_questions": ["Are you referring to Marriott Bonvoy?"],
            }
        )

    monkeypatch.setattr(graph, "validate_conversation", fake_validate_conversation)

    state = graph.run_validation_chat([{"role": "user", "content": "Marriott"}])

    assert state["validation_result"].status == "needs_clarification"
    assert state["query_generation_result"] is None
    assert state["search_queries"] == []
    assert state["retrieval_result"] is None
    assert state["firecrawl_result"] is None
