"""LLM-backed input validation and canonical loyalty program resolution."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

import requests

from providers import provider_for_stage
from schemas import ClarificationOption, ProgramIdentity, ValidationResult


INPUT_VERIFIER_SYSTEM_PROMPT = """
You are a Loyalty Program Discovery and Validation Agent.

Your job is to identify the exact loyalty program the user wants to research
before any information retrieval or data extraction begins.

OBJECTIVE
Transform user input into a single canonical loyalty program identity that can
be safely passed to downstream systems.

DOMAIN RULES
The "domain" field is universal and may be any concise industry or program
category, such as Airline, Hotel, Retail, Banking/Credit Card, Coalition,
Telecom, Fuel, E-commerce, Gaming, Transport, Food Delivery, Healthcare,
Entertainment, Education, Mobility, or Other.

Use the most specific natural domain that helps downstream retrieval. Do not
force every program into a fixed category list.

TASKS
1. Determine whether the user's input refers to a loyalty program, company or
   brand, product or service, or ambiguous term.
2. Resolve the input to a single loyalty program whenever possible.
3. Detect the most likely loyalty program domain or industry category.
4. Estimate confidence in the resolution.
5. If confidence is below 0.90, ask follow-up questions.
6. Continue asking clarifying questions until a single program can be identified
   with high confidence, or the user explicitly chooses from available options.

ANTI-HALLUCINATION RULES
- Never invent a loyalty program, brand, company, or domain.
- Only return "resolved" for a real, known loyalty/rewards/membership program.
- Only include "possible_matches" for real, known programs.
- If the input appears fictional, nonsensical, political, unrelated, or no real
  loyalty program is known, return "rejected".
- Do not create names by adding words like Rewards, Loyalty, Club, Points, Plus,
  or Membership to the user's text.
- User confirmation cannot make a fictional or unknown program real.

AMBIGUITY HANDLING
Examples:
Air India -> Air India Maharaja Club
Flying Returns -> Air India Maharaja Club
Bonvoy -> Marriott Bonvoy
Executive Club -> British Airways Executive Club
Hilton -> Hilton Honors

If multiple valid interpretations exist, do not assume. Ask concise follow-up
questions.

QUESTION RULES
- Ask the minimum number of questions possible.
- Maximum 3 follow-up questions.
- Prefer multiple-choice questions.
- Prioritize identifying program type/domain, brand/company, then exact loyalty
  program.
- Never ask unnecessary questions if confidence is already high.
- Do not repeat semantically equivalent questions.
- After three user clarifications, either resolve the single best remaining
  real possible match or ask the user to choose from a numbered list. Do not ask
  new open-ended questions. If no real program is known, return rejected.

CONFIDENCE RULES
Confidence >= 0.90: return resolved output immediately.
Confidence < 0.90: ask clarification questions.

OUTPUT FORMAT
Return only valid JSON. Do not wrap it in Markdown.

If resolved:
{
  "status": "resolved",
  "program_name": "...",
  "brand": "...",
  "domain": "...",
  "country_or_region": "...",
  "program_subtype": "B2B",
  "confidence": 0.95
}

The program_subtype field is OPTIONAL. Set it to "B2B" ONLY when the resolved program is
explicitly a corporate/business-facing loyalty program (e.g. a program where membership
is held by a company, not an individual, and rewards accrue to a business account).
Omit program_subtype entirely for all standard consumer programs.

If clarification is required:
{
  "status": "needs_clarification",
  "possible_matches": [
    {
      "program_name": "...",
      "brand": "...",
      "domain": "..."
    }
  ],
  "follow_up_questions": [
    "..."
  ],
  "confidence": 0.72
}

If no real loyalty program exists or can be identified:
{
  "status": "rejected",
  "confidence": 0,
  "reason": "No known loyalty program exists for this input."
}

Your goal is to produce a single, unambiguous loyalty program identity with the
fewest possible interactions while maintaining high accuracy.
""".strip()


class ChatClient(Protocol):
    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Return the assistant response parsed as JSON."""


class OpenAICompatibleChatClient:
    """Small OpenAI-compatible chat-completions client.

    Configure with:
    - INPUT_VERIFIER_API_BASE, for example https://api.openai.com/v1/chat/completions
    - INPUT_VERIFIER_API_KEY
    - INPUT_VERIFIER_MODEL
    """

    def __init__(self) -> None:
        provider = provider_for_stage("validation")
        self.api_base = provider.api_base
        self.api_key = provider.api_key
        self.model = provider.resolved_model

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not self.api_base or not self.api_key or not self.model:
            raise RuntimeError(
                "Input verifier LLM is not configured. Set INPUT_VERIFIER_API_BASE, "
                "INPUT_VERIFIER_API_KEY, and INPUT_VERIFIER_MODEL."
            )

        response = requests.post(
            self.api_base,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return parse_json_content(content)


def parse_json_content(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def validate_input(user_input: str, chat_client: ChatClient | None = None) -> ValidationResult:
    if not user_input.strip():
        return ValidationResult(status="rejected", confidence=0, reason="Input is empty.")

    return validate_conversation([{"role": "user", "content": user_input.strip()}], chat_client=chat_client)


def validate_conversation(messages: list[dict[str, str]], chat_client: ChatClient | None = None) -> ValidationResult:
    user_messages = [message["content"].strip() for message in messages if message.get("role") == "user" and message.get("content", "").strip()]
    if not user_messages:
        return ValidationResult(status="rejected", confidence=0, reason="Input is empty.")

    client = chat_client or OpenAICompatibleChatClient()
    try:
        raw_result = client.complete_json(
            [
                {"role": "system", "content": INPUT_VERIFIER_SYSTEM_PROMPT},
                *messages,
            ]
        )
    except Exception as exc:
        return ValidationResult(
            status="needs_clarification",
            confidence=0,
            follow_up_questions=["Input verifier LLM is not configured or failed. Which loyalty program should Kobie research?"],
            reason=str(exc),
        )

    return _parse_verifier_output(user_input=" | ".join(user_messages), payload=raw_result, messages=messages)


def _parse_verifier_output(
    user_input: str,
    payload: dict[str, Any],
    messages: list[dict[str, str]] | None = None,
) -> ValidationResult:
    status = payload.get("status")
    confidence = float(payload.get("confidence", 0))

    if status == "rejected":
        return ValidationResult(
            status="rejected",
            confidence=0,
            reason=str(payload.get("reason") or "No known loyalty program exists for this input."),
        )

    if status == "resolved" and confidence >= 0.90:
        if _looks_like_synthetic_program_name(user_input, payload):
            return ValidationResult(
                status="rejected",
                confidence=0,
                reason="No known loyalty program exists for this input.",
            )
        identity = ProgramIdentity(
            raw_input=user_input,
            program_name=str(payload["program_name"]),
            brand=str(payload.get("brand") or payload["program_name"]),
            domain=normalize_domain(payload.get("domain")),
            country_or_region=payload.get("country_or_region"),
            program_subtype=_parse_program_subtype(payload.get("program_subtype"), str(payload["program_name"])),
            confidence=confidence,
        )
        return ValidationResult(status="resolved", confidence=confidence, identity=identity)

    possible_matches = [
        ClarificationOption(
            program_name=str(match["program_name"]),
            brand=str(match.get("brand") or match["program_name"]),
            domain=normalize_domain(match.get("domain")),
        )
        for match in payload.get("possible_matches", [])
        if isinstance(match, dict)
        and "program_name" in match
        and "domain" in match
        and not _looks_like_synthetic_program_name(user_input, match)
    ]
    follow_ups = [str(question) for question in payload.get("follow_up_questions", [])][:3]
    if not possible_matches and _looks_like_unknown_or_fictional_input(user_input):
        return ValidationResult(
            status="rejected",
            confidence=0,
            reason="No known loyalty program exists for this input.",
        )
    if not follow_ups:
        follow_ups = ["Which exact loyalty program should Kobie research?"]

    return ValidationResult(
        status="needs_clarification",
        confidence=min(confidence, 0.89),
        possible_matches=possible_matches,
        follow_up_questions=follow_ups,
        reason="Input verifier confidence is below 0.90.",
    )


def _parse_program_subtype(llm_value: object, program_name: str) -> str | None:
    """Detect B2B vs B2C from LLM output, with a deterministic keyword fallback."""
    raw = str(llm_value or "").strip().upper()
    if raw in {"B2B", "CORPORATE", "BUSINESS"}:
        return "B2B"
    if raw in {"B2C", "CONSUMER", "PERSONAL", "INDIVIDUAL"}:
        return "B2C"
    # Deterministic fallback: common B2B signals in program names across any domain.
    # The LLM is the primary detector; this handles cases where the LLM omits program_subtype.
    name_lower = program_name.lower()
    b2b_signals = (
        "for business",
        "corporate",
        " b2b",
        "business extra",
        "business rewards",
        "perksplus",
        " sme ",
        "enterprise program",
    )
    if any(signal in name_lower for signal in b2b_signals):
        return "B2B"
    # Programs whose name ends with the bare word "business" (e.g. "AAdvantage Business")
    if name_lower.rstrip().endswith(" business"):
        return "B2B"
    return None


def normalize_domain(value: object) -> str:
    normalized = " ".join(str(value or "Other").replace("_", " ").split())
    return normalized[:80] if normalized else "Other"


def verifier_result_as_message(result: ValidationResult) -> dict[str, str]:
    return {
        "role": "assistant",
        "content": json.dumps(result.model_dump(), ensure_ascii=True),
    }


def _looks_like_synthetic_program_name(user_input: str, payload: dict[str, Any]) -> bool:
    program_name = str(payload.get("program_name") or "").lower()
    brand = str(payload.get("brand") or "").lower()
    user_text = user_input.lower()
    synthetic_suffixes = (" rewards", " loyalty", " club", " points", " plus", " membership")

    if not any(program_name.endswith(suffix) for suffix in synthetic_suffixes):
        return False
    if program_name in user_text:
        return False

    brand_tokens = set(re.findall(r"[a-z0-9]+", brand))
    user_tokens = set(re.findall(r"[a-z0-9]+", user_text))
    if brand_tokens and brand_tokens.issubset(user_tokens):
        known_brands = {
            "american express",
            "amex",
            "air india",
            "marriott",
            "hilton",
            "british airways",
        }
        return brand not in known_brands
    return False


def _looks_like_unknown_or_fictional_input(user_input: str) -> bool:
    text = user_input.lower()
    suspicious_terms = {
        "cockroach",
        "janata party",
        "fake",
        "imaginary",
        "fictional",
        "asdf",
        "qwerty",
    }
    return any(term in text for term in suspicious_terms)
