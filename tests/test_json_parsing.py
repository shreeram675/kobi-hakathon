from pipeline.stages.validation import normalize_domain, parse_json_content


def test_parse_json_content_accepts_fenced_json():
    parsed = parse_json_content(
        """```json
        {"status": "resolved", "confidence": 0.95}
        ```"""
    )

    assert parsed["status"] == "resolved"
    assert parsed["confidence"] == 0.95


def test_normalize_domain_allows_universal_domains():
    assert normalize_domain("Transport") == "Transport"
    assert normalize_domain("Food Delivery") == "Food Delivery"
