"""Central provider configuration.

Actual API clients should be added here so graph nodes do not hard-code model or
retrieval provider choices.
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
    api_key_env: str | None = None
    api_base_env: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key_env is None or os.getenv(self.api_key_env))

    @property
    def api_base(self) -> str | None:
        return os.getenv(self.api_base_env) if self.api_base_env else None

    @property
    def api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        value = os.getenv(self.api_key_env)
        if not value or value.startswith("your_"):
            return None
        return value

    @property
    def resolved_model(self) -> str | None:
        return os.getenv(f"{self.name.upper()}_MODEL") or self.model


STAGE_PROVIDERS: dict[str, ProviderConfig] = {
    "validation": ProviderConfig(
        "input_verifier",
        model=os.getenv("INPUT_VERIFIER_MODEL"),
        api_key_env="INPUT_VERIFIER_API_KEY",
        api_base_env="INPUT_VERIFIER_API_BASE",
    ),
    "query_generator": ProviderConfig(
        "query_generator",
        model=os.getenv("QUERY_GENERATOR_MODEL", "gemini-2.5-flash"),
        api_key_env="GEMINI_API_KEY",
        api_base_env="GEMINI_API_BASE",
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
    "extraction": ProviderConfig("gemini", model="gemini-2.5-flash", api_key_env="GEMINI_API_KEY"),
    "verification": ProviderConfig("gemini", model="gemini-2.5-flash", api_key_env="GEMINI_API_KEY"),
    "narration": ProviderConfig("gemini", model="gemini-2.5-flash", api_key_env="GEMINI_API_KEY"),
    "converse": ProviderConfig("groq", model="llama-3.1-70b-versatile", api_key_env="GROQ_API_KEY"),
}


def provider_for_stage(stage: str) -> ProviderConfig:
    try:
        return STAGE_PROVIDERS[stage]
    except KeyError as exc:
        raise ValueError(f"unknown provider stage: {stage}") from exc
