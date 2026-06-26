"""Central provider configuration.

Actual API clients should be added here so graph nodes do not hard-code model or
retrieval provider choices.

Each stage can run on its own dedicated API key (for example a separate Gemini
key for extraction versus query generation to spread rate limits). When a
stage-specific env var is blank, the stage falls back to the shared provider
key, so a single GEMINI_API_KEY / GROQ_API_KEY setup keeps working unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str | None = None
    api_key_env: str | tuple[str, ...] | None = None
    api_base_env: str | tuple[str, ...] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key_env is None or self.api_key)

    @property
    def api_base(self) -> str | None:
        return _first_env_value(self.api_base_env)

    @property
    def api_key(self) -> str | None:
        return _first_env_value(self.api_key_env, reject_placeholders=True)

    @property
    def resolved_model(self) -> str | None:
        return os.getenv(f"{self.name.upper()}_MODEL") or self.model


def _first_env_value(
    env_names: str | tuple[str, ...] | None,
    *,
    reject_placeholders: bool = False,
) -> str | None:
    if not env_names:
        return None
    if isinstance(env_names, str):
        env_names = (env_names,)
    for env_name in env_names:
        value = os.getenv(env_name)
        if not value:
            continue
        if reject_placeholders and value.startswith("your_"):
            continue
        return value
    return None


STAGE_PROVIDERS: dict[str, ProviderConfig] = {
    "validation": ProviderConfig(
        "input_verifier",
        model=os.getenv("INPUT_VERIFIER_MODEL", "gemini-2.5-flash"),
        api_key_env=("INPUT_VERIFIER_API_KEY", "GEMINI_API_KEY"),
        api_base_env=("INPUT_VERIFIER_API_BASE", "GEMINI_API_BASE"),
    ),
    "query_generator": ProviderConfig(
        "query_generator",
        model=os.getenv("QUERY_GENERATOR_MODEL", "gemini-2.5-flash"),
        api_key_env=("QUERY_GENERATOR_API_KEY", "GEMINI_API_KEY"),
        api_base_env=("QUERY_GENERATOR_API_BASE", "GEMINI_API_BASE"),
    ),
    "retrieval_search": ProviderConfig(
        "tavily",
        api_key_env="TAVILY_API_KEY",
        api_base_env="TAVILY_API_BASE",
    ),
    "retrieval_fetch": ProviderConfig(
        "firecrawl",
        api_key_env="FIRECRAWL_API_KEY",
        api_base_env="FIRECRAWL_API_BASE",
    ),
    "extraction": ProviderConfig(
        "extraction",
        model="gemini-2.5-flash",
        api_key_env=("EXTRACTION_API_KEY", "GEMINI_API_KEY"),
        api_base_env=("EXTRACTION_API_BASE", "GEMINI_API_BASE"),
    ),
    "verification": ProviderConfig(
        "verification",
        model="gemini-2.5-flash",
        api_key_env=("VERIFICATION_API_KEY", "GEMINI_API_KEY"),
        api_base_env=("VERIFICATION_API_BASE", "GEMINI_API_BASE"),
    ),
    "narration": ProviderConfig(
        "narration",
        model="gemini-2.5-flash",
        api_key_env=("NARRATION_API_KEY", "GEMINI_API_KEY"),
        api_base_env=("NARRATION_API_BASE", "GEMINI_API_BASE"),
    ),
    "comparison_brief": ProviderConfig(
        "comparison_brief",
        model="gemini-2.5-flash",
        api_key_env=("NARRATION_API_KEY", "GEMINI_API_KEY"),
        api_base_env=("NARRATION_API_BASE", "GEMINI_API_BASE"),
    ),
    "converse": ProviderConfig(
        "converse",
        model="llama-3.3-70b-versatile",
        api_key_env=("CONVERSE_API_KEY", "GROQ_API_KEY"),
    ),
    "debate": ProviderConfig(
        "debate",
        model="llama-3.3-70b-versatile",
        api_key_env=("DEBATE_API_KEY", "GROQ_API_KEY"),
    ),
}


def provider_for_stage(stage: str) -> ProviderConfig:
    try:
        return STAGE_PROVIDERS[stage]
    except KeyError as exc:
        raise ValueError(f"unknown provider stage: {stage}") from exc
