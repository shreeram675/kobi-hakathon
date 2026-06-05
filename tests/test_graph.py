import graph
from schemas import QueryGenerationOutput, SearchQuery, ValidationResult


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


def test_graph_routes_resolved_validator_output_to_query_generator(monkeypatch):
    monkeypatch.setattr(graph, "validate_conversation", lambda messages: resolved_validation_result())
    monkeypatch.setattr(graph, "generate_queries", lambda identity: fake_query_output())

    state = graph.run_validation_chat([{"role": "user", "content": "Air India"}])

    assert state["validation_result"].status == "resolved"
    assert state["program_name"] == "Air India Maharaja Club"
    assert state["domain"] == "Airline"
    assert state["query_generation_result"] is not None
    assert state["search_queries"]


def test_query_generator_can_run_explicitly(monkeypatch):
    monkeypatch.setattr(graph, "validate_conversation", lambda messages: resolved_validation_result())
    monkeypatch.setattr(graph, "generate_queries", lambda identity: fake_query_output())

    state = graph.run_validation_chat([{"role": "user", "content": "Air India"}])
    state = graph.run_query_generation(state)

    assert state["search_queries"]


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
