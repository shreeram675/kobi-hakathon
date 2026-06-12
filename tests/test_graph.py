import graph
from schemas import (
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
    monkeypatch.setattr(graph, "scrape_retrieved_urls", lambda urls: fake_firecrawl_output(urls))

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
    monkeypatch.setattr(graph, "scrape_retrieved_urls", lambda urls: fake_firecrawl_output(urls))

    state = graph.run_validation_chat([{"role": "user", "content": "Air India"}])
    state = graph.run_query_generation(state)

    assert state["search_queries"]


def test_firecrawl_url_selection_prioritizes_high_value_sources(monkeypatch):
    monkeypatch.setenv("MAX_FIRECRAWL_URLS", "2")
    urls = [
        RetrievedUrl(url="https://forum.example", canonical_url="https://forum.example", score=1.0, query="q", source_type="forums"),
        RetrievedUrl(url="https://official.example", canonical_url="https://official.example", score=0.4, query="q", source_type="official"),
        RetrievedUrl(url="https://terms.example", canonical_url="https://terms.example", score=0.8, query="q", source_type="terms"),
    ]

    selected = graph.select_urls_for_firecrawl(urls)

    assert [item.url for item in selected] == ["https://official.example", "https://terms.example"]


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
