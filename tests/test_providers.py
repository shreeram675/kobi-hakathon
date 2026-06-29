from core.providers import provider_for_stage


def test_stage_key_falls_back_to_shared_provider_key(monkeypatch):
    monkeypatch.delenv("EXTRACTION_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "shared-gemini-key")

    assert provider_for_stage("extraction").api_key == "shared-gemini-key"


def test_stage_key_overrides_shared_provider_key(monkeypatch):
    monkeypatch.setenv("EXTRACTION_API_KEY", "dedicated-extraction-key")
    monkeypatch.setenv("GEMINI_API_KEY", "shared-gemini-key")

    assert provider_for_stage("extraction").api_key == "dedicated-extraction-key"


def test_blank_and_placeholder_stage_keys_are_skipped(monkeypatch):
    monkeypatch.setenv("QUERY_GENERATOR_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_key")

    assert provider_for_stage("query_generator").api_key is None
    assert provider_for_stage("query_generator").configured is False


def test_debate_stage_uses_groq_fallback_and_model_override(monkeypatch):
    monkeypatch.delenv("DEBATE_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "shared-groq-key")
    monkeypatch.setenv("DEBATE_MODEL", "llama-3.3-70b-versatile")

    provider = provider_for_stage("debate")

    assert provider.api_key == "shared-groq-key"
    assert provider.resolved_model == "llama-3.3-70b-versatile"


def test_stage_api_base_falls_back_to_shared_base(monkeypatch):
    monkeypatch.delenv("EXTRACTION_API_BASE", raising=False)
    monkeypatch.setenv("GEMINI_API_BASE", "https://gemini.example/v1beta")

    assert provider_for_stage("extraction").api_base == "https://gemini.example/v1beta"
