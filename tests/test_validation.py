from pipeline.stages.validation import validate_conversation, validate_input


class FakeChatClient:
    def __init__(self, response):
        self.response = response

    def complete_json(self, messages):
        self.messages = messages
        return self.response


def test_llm_resolved_output_builds_identity():
    result = validate_input(
        "Air India",
        chat_client=FakeChatClient(
            {
                "status": "resolved",
                "program_name": "Air India Maharaja Club",
                "brand": "Air India",
                "domain": "Airline",
                "country_or_region": "India",
                "confidence": 0.95,
            }
        ),
    )

    assert result.status == "resolved"
    assert result.identity is not None
    assert result.identity.program_name == "Air India Maharaja Club"
    assert result.identity.domain == "Airline"
    assert result.confidence == 0.95


def test_low_confidence_llm_output_asks_clarification():
    result = validate_input(
        "Marriott",
        chat_client=FakeChatClient(
            {
                "status": "needs_clarification",
                "confidence": 0.72,
                "possible_matches": [
                    {
                        "program_name": "Marriott Bonvoy",
                        "brand": "Marriott",
                        "domain": "Hotel",
                    }
                ],
                "follow_up_questions": [
                    "Are you referring to Marriott Bonvoy, Marriott hotel brand information, or something else?"
                ],
            }
        ),
    )

    assert result.status == "needs_clarification"
    assert result.possible_matches[0].program_name == "Marriott Bonvoy"
    assert len(result.follow_up_questions) == 1


def test_empty_input_rejected_before_llm_call():
    result = validate_input("   ", chat_client=FakeChatClient({}))

    assert result.status == "rejected"
    assert result.confidence == 0


def test_single_possible_match_resolves_after_user_confirms():
    result = validate_conversation(
        [
            {"role": "user", "content": "american express"},
            {
                "role": "assistant",
                "content": '{"status": "needs_clarification", "possible_matches": [{"program_name": "American Express Membership Rewards", "brand": "American Express", "domain": "Banking/Credit Card"}], "follow_up_questions": ["Is this the rewards program?"], "confidence": 0.72}',
            },
            {"role": "user", "content": "yes rewards program"},
        ],
        chat_client=FakeChatClient(
            {
                "status": "needs_clarification",
                "confidence": 0.78,
                "possible_matches": [
                    {
                        "program_name": "American Express Membership Rewards",
                        "brand": "American Express",
                        "domain": "Banking/Credit Card",
                    }
                ],
                "follow_up_questions": ["Is it related to a credit card?"],
            }
        ),
    )

    assert result.status == "needs_clarification"
    assert result.identity is None


def test_rejected_output_stays_rejected():
    result = validate_input(
        "cockroach janata party",
        chat_client=FakeChatClient(
            {
                "status": "rejected",
                "confidence": 0,
                "reason": "No known loyalty program exists for this input.",
            }
        ),
    )

    assert result.status == "rejected"
    assert result.identity is None


def test_synthetic_rewards_hallucination_is_rejected():
    result = validate_input(
        "cockroach janata party",
        chat_client=FakeChatClient(
            {
                "status": "resolved",
                "program_name": "Cockroach Rewards",
                "brand": "Cockroach",
                "domain": "Food Delivery",
                "country_or_region": None,
                "confidence": 0.95,
            }
        ),
    )

    assert result.status == "rejected"
    assert result.identity is None


def test_synthetic_possible_match_is_filtered_and_rejected_for_fake_input():
    result = validate_input(
        "cockroach janata party",
        chat_client=FakeChatClient(
            {
                "status": "needs_clarification",
                "confidence": 0.70,
                "possible_matches": [
                    {
                        "program_name": "Cockroach Rewards",
                        "brand": "Cockroach",
                        "domain": "Food Delivery",
                    }
                ],
                "follow_up_questions": ["Is this related to a food delivery service?"],
            }
        ),
    )

    assert result.status == "rejected"
    assert result.possible_matches == []
