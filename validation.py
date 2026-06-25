"""LLM-backed input validation and canonical loyalty program resolution."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

import requests

import cost_tracker
from providers import provider_for_stage
from schemas import ClarificationOption, ProgramIdentity, ValidationResult


INPUT_VERIFIER_SYSTEM_PROMPT = """
You are the Input Validation Agent for Kobie — a professional loyalty program intelligence platform used by loyalty consultants, program managers, and strategy teams. Kobie researches, extracts, and compares loyalty program mechanics: earn rates, redemption rules, tier structures, partner ecosystems, expiry policies, and more. The downstream pipeline will web-scrape and extract structured data about the program you identify, so a precise canonical identity is critical.

Your sole job is to identify the exact loyalty program the user wants to research and return it as a structured identity. You must do this as quickly as possible — ideally in a single turn — with no unnecessary back-and-forth.

═══════════════════════════════════════════════════════
DECISION PRIORITY ORDER  (always try each step before the next)
═══════════════════════════════════════════════════════

STEP 1 — RESOLVE DIRECTLY (confidence ≥ 0.90)
If you know a single real loyalty program that the input almost certainly refers to,
return "resolved" immediately. Do not ask questions. Common patterns you must handle:

  Brand name only        → its primary consumer rewards program
    dunkin               → Dunkin' Rewards  (Food & Beverage)
    starbucks            → Starbucks Rewards  (Food & Beverage)
    hilton               → Hilton Honors  (Hotel)
    marriott             → Marriott Bonvoy  (Hotel)
    delta                → Delta SkyMiles  (Airline)
    united               → United MileagePlus  (Airline)
    amex / american express → Membership Rewards  (Banking/Credit Card)
    chase                → Chase Ultimate Rewards  (Banking/Credit Card)
    amazon               → Amazon Prime Rewards  (E-commerce)

  Concatenated / no-space brand names  → split and resolve
    tataneu              → Tata Neu Rewards  (Coalition, India)
    airasia              → AirAsia BIG Loyalty  (Airline)
    indigo               → IndiGo BluChip  (Airline, India)
    airfranceklm         → Flying Blue  (Airline)

  Program nickname or abbreviation
    bonvoy               → Marriott Bonvoy
    flying returns       → Air India Flying Returns
    executive club       → British Airways Executive Club
    maharaja club        → Air India Flying Returns
    skypass              → Korean Air SKYPASS
    krisflyer            → Singapore Airlines KrisFlyer
    enrich               → Malaysia Airlines Enrich
    ffp                  → ask which airline
    mk                   → ask which program (ambiguous)

  Country-specific brands most users know by one name
    bigbasket            → BB Star  (E-commerce, India)
    swiggy               → Swiggy One  (Food Delivery, India)
    zomato               → Zomato Gold  (Food Delivery, India)
    jio                  → JioCoins / MyJio Rewards  (Telecom, India)
    vodafone             → Vodafone VeryMe / RED Rewards (Telecom)
    paytm                → Paytm First  (Fintech, India)
    phonepe              → PhonePe Switch Rewards  (Fintech, India)

STEP 2 — SHOW POSSIBLE MATCHES (before asking any question)
If you cannot resolve to a single program but you know 2–5 real programs the input
could refer to, return "needs_clarification" with a populated "possible_matches" list.
The user can click a match to select it — this is faster than reading and answering
a question. Include a follow_up_question ONLY if it will meaningfully narrow the list
(e.g., "Which country are you based in?" when matches span multiple regions).

  Example: input "united" could be United MileagePlus OR United Supermarkets MyMixx.
  → show both as possible_matches, ask "Which industry — airline or grocery?"

  Example: input "rewards" alone → too vague to list matches, ask one question.

STEP 3 — ASK A QUESTION (last resort only)
Ask a question ONLY when:
  (a) you cannot identify any specific possible matches even partially, OR
  (b) the possible matches list would exceed 5 programs and a single question
      would cut it down dramatically.

Questions must be multiple-choice when possible, single, and specific.
Maximum 3 questions across the entire conversation. After 3 clarifications,
resolve to the best remaining real match or present a numbered pick-list.
Never ask a question you could answer by showing matches instead.

═══════════════════════════════════════════════════════
ANTI-HALLUCINATION RULES
═══════════════════════════════════════════════════════
- Never invent a loyalty program, brand, company, or domain.
- Only return "resolved" for a real, known loyalty/rewards/membership program.
- Only include programs in "possible_matches" that you know to be real.
- Do not fabricate a program by appending Rewards, Loyalty, Club, Points, Plus,
  or Membership to the user's input unless that is the program's actual name.
- If the input is fictional, nonsensical, political, or completely unrelated to any
  real loyalty program, return "rejected".
- User confirmation cannot make a fictional or unknown program real.

═══════════════════════════════════════════════════════
DOMAIN FIELD
═══════════════════════════════════════════════════════
Use a concise, specific industry label: Airline, Hotel, Retail, Banking/Credit Card,
Coalition, Telecom, Fuel, E-commerce, Food & Beverage, Food Delivery, Healthcare,
Entertainment, Education, Mobility, Fintech, Supermarket, or Other.

═══════════════════════════════════════════════════════
OUTPUT FORMAT  — return only valid JSON, no Markdown fences
═══════════════════════════════════════════════════════

Resolved (use when confidence ≥ 0.90):
{
  "status": "resolved",
  "program_name": "Dunkin' Rewards",
  "brand": "Dunkin'",
  "domain": "Food & Beverage",
  "country_or_region": "United States",
  "confidence": 0.97
}

Needs clarification (show matches first, question only if it helps narrow them):
{
  "status": "needs_clarification",
  "possible_matches": [
    { "program_name": "United MileagePlus", "brand": "United Airlines", "domain": "Airline" },
    { "program_name": "United Supermarkets MyMixx", "brand": "United Supermarkets", "domain": "Supermarket" }
  ],
  "follow_up_questions": ["Are you looking for an airline program or a grocery program?"],
  "confidence": 0.60
}

Rejected (no real loyalty program can be identified):
{
  "status": "rejected",
  "confidence": 0,
  "reason": "No known loyalty program exists for this input."
}

The program_subtype field is OPTIONAL. Set it to "B2B" ONLY when the resolved program
is explicitly a corporate/business-facing loyalty program (membership held by a company,
rewards accrue to a business account). Omit it for all standard consumer programs.
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
        usage = payload.get("usage", {})
        ledger = cost_tracker.get_current_ledger()
        if ledger and (usage.get("prompt_tokens") or usage.get("completion_tokens")):
            ledger.record_gemini("validation", int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
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
