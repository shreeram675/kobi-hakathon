"""5-step adversarial debate engine for conflicting loyalty-program claims.

When two sources disagree on the same extracted field, two advocate LLM agents
argue for their claim using only the structured claim metadata (recency,
authority, corroboration, volatility), optionally rebut each other, and a
judge produces a deterministic JSON verdict. The engine is program-agnostic:
all program facts come from the conflict dict supplied by the caller.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections import Counter
from typing import Any

import cost_tracker
from providers import provider_for_stage

# File logger so we can diagnose key issues without needing the terminal
_file_handler = logging.FileHandler("debate_debug.log", encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger("kobie.debate").addHandler(_file_handler)
logging.getLogger("kobie.debate").setLevel(logging.DEBUG)


def _cosine_similarity(text_a: str, text_b: str) -> float:
    """Bag-of-words cosine similarity — avoids sklearn dependency."""
    def bow(t: str) -> Counter:
        return Counter(re.findall(r"\w+", t.lower()))

    a, b = bow(text_a), bow(text_b)
    if not a or not b:
        return 0.0
    dot = sum(a[w] * b[w] for w in a if w in b)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


DEFAULT_DEBATE_MODEL = "llama-3.3-70b-versatile"
SIMILARITY_THRESHOLD = 0.80

# Advocate temperature 0.0: must stay strictly grounded in provided metadata.
# Any non-zero temperature risks inventing facts not present in claim metadata.
ADVOCATE_TEMPERATURE = 0.0
ADVOCATE_MAX_TOKENS = 200
REBUTTAL_MAX_TOKENS = 150

# Judge temperature 0.1: the verdict must be deterministic and reproducible;
# the judge weighs evidence, it does not generate ideas.
JUDGE_TEMPERATURE = 0.1
JUDGE_MAX_TOKENS = 350

# Groq free-tier rate limits crash on bursts; cap in-flight calls at 3 so
# concurrent debates across multiple conflicts queue instead of failing.
# Semaphore is created lazily per event-loop run to avoid "bound to a different
# event loop" errors when asyncio.run() creates a new loop each invocation.
_GROQ_SEMAPHORE: asyncio.Semaphore | None = None

# Round-robin key pool — populated lazily from GROQ_API_KEYS (comma-separated)
# or individual DEBATE_API_KEY / DEBATE_API_KEY_B / GROQ_API_KEY env vars.
_CLIENT_POOL: list | None = None
_CLIENT_POOL_KEYS: list[str] = []  # parallel list of key strings for logging
_POOL_COUNTER: int = 0

NO_REBUTTAL_NOTE = "No rebuttal — arguments not sufficiently differentiated."

VOLATILITY_WEIGHTS = {
    "HIGH": {"recency": 0.50, "authority": 0.25, "corroboration": 0.25},
    "LOW": {"recency": 0.20, "authority": 0.50, "corroboration": 0.30},
}

AUTHORITY_RANKING = "official > major_publication > news > aggregator > forum"

FLAG_FALLBACK_REASONING = "Judge output unparseable — manual review needed"

CLAIM_TEMPLATE = (
    "value={value} | source_url={source_url} | date={date} | "
    "authority={authority} | corroboration={corroboration} independent sources | "
    "confidence={confidence}"
)

ADVOCATE_PROMPT_TEMPLATE = """You are Advocate {advocate}. Build the strongest case that CLAIM {advocate} is the correct value for the disputed loyalty program field below. You cannot see the opposing advocate's argument.

FIELD: {field_name}
VOLATILITY: {volatility}
CONFIDENCE WEIGHTS for {volatility} volatility: recency {recency_weight} | authority {authority_weight} | corroboration {corroboration_weight}
AUTHORITY TIERS (strongest first): {authority_ranking}

AVAILABLE METADATA — argue ONLY from these facts:
  CLAIM A: {claim_a}
  CLAIM B: {claim_b}

HALLUCINATION FENCE — STRICTLY ENFORCED:
- Use ONLY the metadata values listed in AVAILABLE METADATA above.
- Do NOT invent, infer, or speculate about any fact not explicitly present in the metadata.
- If a metadata field is absent or says "None", state "not provided" — never guess.
- Do NOT claim the opposing source is copied, derivative, or related to yours.
- Any statement that cannot be traced to AVAILABLE METADATA is a hallucination and will be discarded by the judge.

RULES:
- Argue using ONLY recency, authority, corroboration, and the volatility context above.
- Be specific: cite the metadata numbers and the volatility weights. Vague appeals like "official sources are always better" are weak.

Write the argument for CLAIM {advocate} in at most 120 words."""

REBUTTAL_PROMPT_TEMPLATE = """You are Advocate {advocate}. You previously argued for CLAIM {advocate}. You can now see the opposing advocate's original argument.

OPPOSING ARGUMENT (for CLAIM {opponent}):
{opposing_argument}

FIELD: {field_name}
VOLATILITY: {volatility}
CONFIDENCE WEIGHTS for {volatility} volatility: recency {recency_weight} | authority {authority_weight} | corroboration {corroboration_weight}
AUTHORITY TIERS (strongest first): {authority_ranking}

AVAILABLE METADATA — rebut ONLY from these facts:
  CLAIM A: {claim_a}
  CLAIM B: {claim_b}

TASK: Identify the SINGLE weakest point in the opposing argument and challenge it using only the metadata dimensions above.

Permitted rebuttal angles:
{permitted_angles}

HALLUCINATION FENCE — STRICTLY ENFORCED:
- Your rebuttal must cite ONLY facts present in AVAILABLE METADATA.
- Do NOT introduce any fact that is not in the metadata above.
- Do NOT claim the opposing sources are copies, shared, or derivative — you were not given that information.
- Any fact you add beyond AVAILABLE METADATA is a hallucination; the judge will mark your rebuttal "hallucinated" and discard it entirely.

RULES:
- Challenge exactly one weak point; do not list several.
- Do NOT simply repeat your original argument.

Write the rebuttal in at most 90 words."""

REBUTTAL_ANGLES_A = """- The opponent overweights recency for a LOW volatility field.
- The opponent's corroboration comes from lower authority tier sources.
- The opponent's date advantage is within normal site update cycles.
- The volatility weights do not support the opponent's conclusion."""

REBUTTAL_ANGLES_B = """- The opponent overweights authority for a HIGH volatility field.
- The opponent's single source is outweighed by the higher corroboration count.
- The opponent's official authority does not compensate for the recency gap.
- The volatility weights do not support the opponent's authority-first conclusion."""

JUDGE_PROMPT_TEMPLATE = """You are the Judge in an adversarial debate about a disputed loyalty program field. Decide which claim is correct using ONLY the metadata and debate transcript below. Never use external knowledge.

FIELD: {field_name}
VOLATILITY: {volatility}
CONFIDENCE WEIGHTS for {volatility} volatility: recency {recency_weight} | authority {authority_weight} | corroboration {corroboration_weight}
AUTHORITY TIERS (strongest first): {authority_ranking}

AVAILABLE METADATA:
  CLAIM A: {claim_a}
  CLAIM B: {claim_b}

ARGUMENT A:
{argument_a}

ARGUMENT B:
{argument_b}

REBUTTAL A:
{rebuttal_a}

REBUTTAL B:
{rebuttal_b}

Evaluate in this exact order:
1. HALLUCINATION SCAN — compare every statement in each argument and rebuttal against AVAILABLE METADATA. Any fact not traceable to AVAILABLE METADATA is a hallucination. Mark hallucinated arguments/rebuttals in hallucination_detected and treat them as if they were never said.
2. Apply the volatility weights — which metadata signal dominates for this field?
3. Evaluate the original arguments using only non-hallucinated statements — which made the stronger grounded evidence case?
4. Evaluate the rebuttals — specific and grounded beats vague. Any rebuttal flagged in Step 1 must be scored "hallucinated" in rebuttal_assessment and fully discarded from Step 3-4 reasoning.
5. Combine all surviving signals into a verdict.
6. Return FLAG ONLY when the metadata itself is genuinely insufficient to distinguish the claims after all steps above — NOT simply because arguments were weak or unconvincing.

Output ONLY valid JSON, no preamble, no markdown fences:
{{
    "winner": "A" or "B" or "FLAG",
    "winning_value": "<chosen value or null if FLAG>",
    "deciding_factor": "recency" or "authority" or "corroboration" or "rebuttal_quality" or "unresolvable",
    "reasoning": "<one sentence naming the specific deciding factor>",
    "rebuttal_assessment": {{
        "A_rebuttal": "strong" or "weak" or "hallucinated",
        "B_rebuttal": "strong" or "weak" or "hallucinated"
    }},
    "hallucination_detected": {{
        "argument_a": false,
        "argument_b": false,
        "rebuttal_a": false,
        "rebuttal_b": false
    }},
    "confidence_adjustment": <float between -0.10 and +0.10>
}}"""


def _build_client_pool() -> list:
    """Build a round-robin pool of AsyncGroq clients from all available keys."""
    global _CLIENT_POOL, _CLIENT_POOL_KEYS
    if _CLIENT_POOL is not None:
        return _CLIENT_POOL
    import os
    from groq import AsyncGroq

    raw = os.getenv("GROQ_API_KEYS", "").strip()
    if raw:
        keys = [k.strip() for k in raw.split(",") if k.strip()]
    else:
        seen: set[str] = set()
        keys = []
        for var in ("DEBATE_API_KEY", "DEBATE_API_KEY_B", "GROQ_API_KEY"):
            k = os.getenv(var, "").strip()
            if k and k not in seen:
                seen.add(k)
                keys.append(k)
        fallback = provider_for_stage("debate").api_key
        if fallback and fallback not in seen:
            keys.append(fallback)

    if not keys:
        raise RuntimeError("Debate engine: no Groq API keys configured. Set GROQ_API_KEYS or DEBATE_API_KEY.")

    log = logging.getLogger("kobie.debate")
    log.info("Debate key pool: %d keys loaded", len(keys))
    for i, k in enumerate(keys):
        log.info("  pool[%d]: %s...%s", i, k[:12], k[-4:])

    _CLIENT_POOL_KEYS = keys
    _CLIENT_POOL = [AsyncGroq(api_key=k) for k in keys]
    return _CLIENT_POOL


def _next_client(offset: int = 0):
    global _POOL_COUNTER
    pool = _build_client_pool()
    client = pool[(_POOL_COUNTER + offset) % len(pool)]
    _POOL_COUNTER += 1
    return client


def _remove_client_from_pool(client) -> None:
    """Permanently remove a bad client from the pool (e.g. on 401)."""
    global _CLIENT_POOL, _CLIENT_POOL_KEYS
    log = logging.getLogger("kobie.debate")
    if _CLIENT_POOL is None:
        return
    try:
        idx = _CLIENT_POOL.index(client)
        key_hint = f"{_CLIENT_POOL_KEYS[idx][:12]}...{_CLIENT_POOL_KEYS[idx][-4:]}" if idx < len(_CLIENT_POOL_KEYS) else "?"
        log.error("Removing invalid key from debate pool: %s", key_hint)
        _CLIENT_POOL.pop(idx)
        if idx < len(_CLIENT_POOL_KEYS):
            _CLIENT_POOL_KEYS.pop(idx)
    except ValueError:
        pass


def _debate_model() -> str:
    return provider_for_stage("debate").resolved_model or DEFAULT_DEBATE_MODEL


async def call_groq(prompt: str, temperature: float, max_tokens: int, *, use_client_b: bool = False) -> str:
    """Single Groq chat completion; semaphore-gated with round-robin key pool and 429 retry.

    Rotates through all keys in GROQ_API_KEYS on each call. On a 429, immediately
    switches to the next key; only waits if every key in the pool has been tried.
    """
    import re as _re

    global _GROQ_SEMAPHORE
    if _GROQ_SEMAPHORE is None:
        _GROQ_SEMAPHORE = asyncio.Semaphore(5)

    pool = _build_client_pool()
    pool_size = len(pool)
    # use_client_b offsets by half the pool so A and B calls land on different keys
    base_offset = (pool_size // 2) if use_client_b and pool_size > 1 else 0
    max_attempts = pool_size * 2
    delay = 5.0

    log = logging.getLogger("kobie.debate")

    for attempt in range(max_attempts):
        client = _next_client(offset=base_offset)
        async with _GROQ_SEMAPHORE:
            try:
                response = await client.chat.completions.create(
                    model=_debate_model(),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if response.usage:
                    ledger = cost_tracker.get_current_ledger()
                    if ledger:
                        ledger.record_groq("debate", response.usage.prompt_tokens or 0, response.usage.completion_tokens or 0)
                return (response.choices[0].message.content or "").strip()
            except Exception as exc:
                msg = str(exc)
                is_rate_limit = "rate_limit_exceeded" in msg or "429" in msg
                is_invalid_key = "401" in msg or "invalid_api_key" in msg or "Invalid API Key" in msg
                if is_invalid_key:
                    # Remove this key from the pool permanently so it is never retried.
                    _remove_client_from_pool(client)
                    log.error("Debate engine 401 on attempt %d — key removed, rotating. Error: %s", attempt, msg[:120])
                    pool = _build_client_pool()
                    pool_size = len(pool)
                    if pool_size == 0:
                        raise RuntimeError("Debate engine: all keys exhausted due to 401 errors.") from exc
                    if attempt < max_attempts - 1:
                        continue
                    raise
                if not is_rate_limit:
                    raise
                m = _re.search(r"try again in ([0-9.]+)s", msg)
                delay = float(m.group(1)) + 0.5 if m else delay * 2
                if attempt == max_attempts - 1:
                    raise
                # Still have more keys to try — switch immediately if pool not exhausted,
                # otherwise wait the suggested delay before the next round.
                if attempt < pool_size - 1:
                    continue
        await asyncio.sleep(delay)

    raise RuntimeError("call_groq: exhausted all keys and retries")


def arguments_are_differentiated(argument_a: str, argument_b: str) -> bool:
    """Gate for the rebuttal rounds (Steps 3-4).

    If both advocates made essentially the same argument, rebuttals only
    restate it and waste tokens, so we measure TF-IDF cosine similarity and
    run rebuttals only when the arguments are genuinely different (< 0.80).
    """

    if not argument_a.strip() or not argument_b.strip():
        return False
    similarity = _cosine_similarity(argument_a, argument_b)
    return similarity < SIMILARITY_THRESHOLD


def parse_judge_output(raw: str) -> dict[str, Any]:
    """Parse the judge's JSON verdict, tolerating markdown fences."""

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {
            "winner": "FLAG",
            "winning_value": None,
            "deciding_factor": "unresolvable",
            "reasoning": FLAG_FALLBACK_REASONING,
            "rebuttal_assessment": {"A_rebuttal": "weak", "B_rebuttal": "weak"},
            "confidence_adjustment": 0.0,
        }


async def run_debate(conflict: dict[str, Any], use_rebuttal: bool = True) -> dict[str, Any]:
    """Run the 5-step adversarial debate for one field conflict.

    Step 1: Advocate A argues for claim_a in isolation (metadata only).
    Step 2: Advocate B argues for claim_b in isolation (metadata only).
    Gate:   TF-IDF cosine similarity between the two arguments; rebuttals run
            only when the arguments are differentiated (similarity < 0.80).
    Step 3: Rebuttal A — A sees B's argument and challenges its single
            weakest point (conditional on the gate and use_rebuttal).
    Step 4: Rebuttal B — mirror of Step 3 (same condition).
    Step 5: Judge sees all four outputs and returns a deterministic JSON
            verdict: winner A/B, or FLAG when genuinely unresolvable.

    Returns the verdict plus the full transcript and a final confidence
    clamped to [0.0, 1.0].
    """

    field_name = str(conflict["field_name"])
    claim_a = conflict["claim_a"]
    claim_b = conflict["claim_b"]

    # Steps 1 and 2 run concurrently; B calls use the secondary key to split TPM.
    argument_a, argument_b = await asyncio.gather(
        call_groq(_advocate_prompt("A", conflict), ADVOCATE_TEMPERATURE, ADVOCATE_MAX_TOKENS),
        call_groq(_advocate_prompt("B", conflict), ADVOCATE_TEMPERATURE, ADVOCATE_MAX_TOKENS, use_client_b=True),
    )

    rebuttal_a = ""
    rebuttal_b = ""
    rebuttals_ran = use_rebuttal and arguments_are_differentiated(argument_a, argument_b)
    if rebuttals_ran:
        rebuttal_a, rebuttal_b = await asyncio.gather(
            call_groq(_rebuttal_prompt("A", conflict, argument_b), ADVOCATE_TEMPERATURE, REBUTTAL_MAX_TOKENS),
            call_groq(_rebuttal_prompt("B", conflict, argument_a), ADVOCATE_TEMPERATURE, REBUTTAL_MAX_TOKENS, use_client_b=True),
        )

    judge_raw = await call_groq(
        _judge_prompt(
            conflict,
            argument_a,
            argument_b,
            rebuttal_a or NO_REBUTTAL_NOTE,
            rebuttal_b or NO_REBUTTAL_NOTE,
        ),
        JUDGE_TEMPERATURE,
        JUDGE_MAX_TOKENS,
    )
    verdict = parse_judge_output(judge_raw)

    winner = str(verdict.get("winner") or "FLAG").strip().upper()
    if winner not in {"A", "B", "FLAG"}:
        winner = "FLAG"

    if winner == "A":
        winning_value: str | None = str(claim_a["value"])
        base_confidence = float(claim_a.get("confidence") or 0.0)
    elif winner == "B":
        winning_value = str(claim_b["value"])
        base_confidence = float(claim_b.get("confidence") or 0.0)
    else:
        winning_value = None
        base_confidence = 0.40

    adjustment = _clamp(_to_float(verdict.get("confidence_adjustment")), -0.10, 0.10)
    final_confidence = _clamp(base_confidence + adjustment, 0.0, 1.0)

    rebuttal_assessment = verdict.get("rebuttal_assessment")
    if not isinstance(rebuttal_assessment, dict):
        rebuttal_assessment = {"A_rebuttal": "weak", "B_rebuttal": "weak"}

    hallucination_detected = verdict.get("hallucination_detected")
    if not isinstance(hallucination_detected, dict):
        hallucination_detected = {
            "argument_a": False,
            "argument_b": False,
            "rebuttal_a": False,
            "rebuttal_b": False,
        }

    return {
        "field_name": field_name,
        "winner": winner,
        "winning_value": winning_value,
        "deciding_factor": str(verdict.get("deciding_factor") or "unresolvable"),
        "reasoning": str(verdict.get("reasoning") or ""),
        "rebuttal_assessment": rebuttal_assessment,
        "hallucination_detected": hallucination_detected,
        "argument_a": argument_a,
        "argument_b": argument_b,
        "rebuttal_a": rebuttal_a,
        "rebuttal_b": rebuttal_b,
        "final_confidence": final_confidence,
        "steps_used": 5 if rebuttals_ran else 3,
    }


def _advocate_prompt(advocate: str, conflict: dict[str, Any]) -> str:
    return ADVOCATE_PROMPT_TEMPLATE.format(
        advocate=advocate,
        authority_ranking=AUTHORITY_RANKING,
        **_shared_prompt_fields(conflict),
    )


def _rebuttal_prompt(advocate: str, conflict: dict[str, Any], opposing_argument: str) -> str:
    return REBUTTAL_PROMPT_TEMPLATE.format(
        advocate=advocate,
        opponent="B" if advocate == "A" else "A",
        opposing_argument=opposing_argument,
        permitted_angles=REBUTTAL_ANGLES_A if advocate == "A" else REBUTTAL_ANGLES_B,
        authority_ranking=AUTHORITY_RANKING,
        **_shared_prompt_fields(conflict),
    )


def _judge_prompt(
    conflict: dict[str, Any],
    argument_a: str,
    argument_b: str,
    rebuttal_a: str,
    rebuttal_b: str,
) -> str:
    return JUDGE_PROMPT_TEMPLATE.format(
        argument_a=argument_a,
        argument_b=argument_b,
        rebuttal_a=rebuttal_a,
        rebuttal_b=rebuttal_b,
        authority_ranking=AUTHORITY_RANKING,
        **_shared_prompt_fields(conflict),
    )


def _shared_prompt_fields(conflict: dict[str, Any]) -> dict[str, Any]:
    volatility = str(conflict.get("volatility") or "HIGH").upper()
    weights = VOLATILITY_WEIGHTS.get(volatility, VOLATILITY_WEIGHTS["HIGH"])
    return {
        "field_name": conflict["field_name"],
        "volatility": volatility,
        "recency_weight": weights["recency"],
        "authority_weight": weights["authority"],
        "corroboration_weight": weights["corroboration"],
        "claim_a": _format_claim(conflict["claim_a"]),
        "claim_b": _format_claim(conflict["claim_b"]),
    }


def _format_claim(claim: dict[str, Any]) -> str:
    return CLAIM_TEMPLATE.format(
        value=claim.get("value"),
        source_url=claim.get("source_url"),
        date=claim.get("date"),
        authority=claim.get("authority"),
        corroboration=claim.get("corroboration"),
        confidence=claim.get("confidence"),
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
