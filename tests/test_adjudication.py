from datetime import date

import asyncio

import pipeline.adjudication.conflict_adjudicator as conflict_adjudicator
import pipeline.adjudication.debate_engine as debate_engine
from pipeline.adjudication.conflict_adjudicator import (
    adjudicator_node,
    apply_adjudication_to_field_report,
    classify_volatility,
    detect_conflicts_from_packets,
)
from pipeline.adjudication.debate_engine import (
    NO_REBUTTAL_NOTE,
    arguments_are_differentiated,
    parse_judge_output,
    run_debate,
)
from core.schemas import (
    ExtractedField,
    FieldReport,
    FieldReportEntry,
    NormalizedObjectPacket,
    RawDocument,
    build_initial_state,
)


JUDGE_VERDICT_B = """
{
  "winner": "B",
  "winning_value": "1.0 Avios per pound",
  "deciding_factor": "recency",
  "reasoning": "HIGH volatility weights favor the newer corroborated claim.",
  "rebuttal_assessment": {"A_rebuttal": "weak", "B_rebuttal": "strong"},
  "confidence_adjustment": 0.05
}
"""


def ba_conflict() -> dict:
    return {
        "field_name": "earn_rate_base",
        "volatility": "HIGH",
        "claim_a": {
            "value": "1.5 Avios per pound",
            "source_url": "ba.com/executive-club",
            "date": date(2025, 3, 1),
            "authority": "official",
            "corroboration": 1,
            "confidence": 0.68,
        },
        "claim_b": {
            "value": "1.0 Avios per pound",
            "source_url": "headforpoints.com",
            "date": date(2025, 4, 15),
            "authority": "major_publication",
            "corroboration": 3,
            "confidence": 0.71,
        },
    }


def fake_call_groq(advocate_a: str, advocate_b: str, judge: str, rebuttal_a: str = "", rebuttal_b: str = ""):
    async def _call(prompt: str, temperature: float, max_tokens: int, **_kwargs) -> str:
        if "You are the Judge" in prompt:
            return judge
        if "Identify the SINGLE weakest point" in prompt:
            return rebuttal_a if "You are Advocate A" in prompt else rebuttal_b
        return advocate_a if "You are Advocate A" in prompt else advocate_b

    return _call


def test_arguments_are_differentiated_gates_on_similarity():
    same = "Recency carries 0.50 weight so the newer source wins this field."
    assert arguments_are_differentiated(same, same) is False
    assert arguments_are_differentiated("", "anything") is False
    assert (
        arguments_are_differentiated(
            "Official authority dominates because the claim comes from the program owner directly.",
            "Three independent corroborating sources with a six week recency advantage outweigh one stale page.",
        )
        is True
    )


def test_parse_judge_output_strips_fences_and_falls_back():
    fenced = "```json\n{\"winner\": \"A\", \"confidence_adjustment\": 0.02}\n```"
    assert parse_judge_output(fenced)["winner"] == "A"

    fallback = parse_judge_output("the judge rambled with no json at all")
    assert fallback["winner"] == "FLAG"
    assert fallback["reasoning"] == "Judge output unparseable — manual review needed"


def test_run_debate_full_five_steps(monkeypatch):
    monkeypatch.setattr(
        debate_engine,
        "call_groq",
        fake_call_groq(
            advocate_a="Official authority matters because the program owner publishes the canonical rate.",
            advocate_b="Recency carries 0.50 weight for HIGH volatility and three sources corroborate the newer value.",
            judge=JUDGE_VERDICT_B,
            rebuttal_a="B overweights recency within a normal site update cycle.",
            rebuttal_b="A's single official source is outweighed by corroboration count.",
        ),
    )

    result = asyncio.run(run_debate(ba_conflict(), use_rebuttal=True))

    assert result["winner"] == "B"
    assert result["winning_value"] == "1.0 Avios per pound"
    assert result["deciding_factor"] == "recency"
    assert result["steps_used"] == 5
    assert result["rebuttal_a"]
    assert result["rebuttal_b"]
    assert abs(result["final_confidence"] - 0.76) < 1e-9


def test_run_debate_skips_rebuttals_for_similar_arguments(monkeypatch):
    captured_prompts = []
    same_argument = "Recency carries 0.50 weight so the newer corroborated source wins."

    async def _call(prompt: str, temperature: float, max_tokens: int, **_kwargs) -> str:
        captured_prompts.append(prompt)
        if "You are the Judge" in prompt:
            return JUDGE_VERDICT_B
        return same_argument

    monkeypatch.setattr(debate_engine, "call_groq", _call)

    result = asyncio.run(run_debate(ba_conflict(), use_rebuttal=True))

    assert result["steps_used"] == 3
    assert result["rebuttal_a"] == ""
    assert result["rebuttal_b"] == ""
    judge_prompt = next(prompt for prompt in captured_prompts if "You are the Judge" in prompt)
    assert NO_REBUTTAL_NOTE in judge_prompt


def test_run_debate_clamps_confidence_adjustment(monkeypatch):
    inflated = JUDGE_VERDICT_B.replace("0.05", "0.9")
    monkeypatch.setattr(
        debate_engine,
        "call_groq",
        fake_call_groq(
            advocate_a="Authority of the official source dominates this dispute entirely.",
            advocate_b="Recency and corroboration metadata clearly favor the newer claim instead.",
            judge=inflated,
        ),
    )

    result = asyncio.run(run_debate(ba_conflict(), use_rebuttal=True))

    assert abs(result["final_confidence"] - (0.71 + 0.10)) < 1e-9


def test_adjudicator_auto_resolves_large_score_gap(monkeypatch):
    async def _no_debate(conflict, use_rebuttal=True):
        raise AssertionError("Debate must not run when score gap > 0.20")

    monkeypatch.setattr(conflict_adjudicator, "run_debate", _no_debate)

    conflict = ba_conflict()
    conflict["claim_a"]["confidence"] = 0.95
    conflict["claim_b"]["confidence"] = 0.50
    state = build_initial_state("Any Program")
    state["conflicts"] = [conflict]

    updated = adjudicator_node(state)

    assert len(updated["adjudicated"]) == 1
    entry = updated["adjudicated"][0]
    assert entry["resolution"] == "auto"
    assert entry["winner"] == "A"
    assert entry["value"] == "1.5 Avios per pound"
    assert entry["confidence"] == 0.95


def test_adjudicator_flags_unresolvable_debate(monkeypatch):
    async def _flagged(conflict, use_rebuttal=True):
        return {
            "field_name": conflict["field_name"],
            "winner": "FLAG",
            "winning_value": None,
            "deciding_factor": "unresolvable",
            "reasoning": "Sources are evenly matched.",
            "rebuttal_assessment": {"A_rebuttal": "weak", "B_rebuttal": "weak"},
            "argument_a": "a",
            "argument_b": "b",
            "rebuttal_a": "",
            "rebuttal_b": "",
            "final_confidence": 0.40,
            "steps_used": 3,
        }

    monkeypatch.setattr(conflict_adjudicator, "run_debate", _flagged)

    state = build_initial_state("Any Program")
    state["conflicts"] = [ba_conflict()]

    updated = adjudicator_node(state)

    assert len(updated["adjudicated"]) == 2
    assert all(entry["confidence"] == 0.40 for entry in updated["adjudicated"])
    assert all(entry["flag"] == "CONFLICTING SOURCES — verify manually" for entry in updated["adjudicated"])
    values = {entry["value"] for entry in updated["adjudicated"]}
    assert values == {"1.5 Avios per pound", "1.0 Avios per pound"}
    assert len(updated["human_review_queue"]) == 1
    review = updated["human_review_queue"][0]
    assert review["field_name"] == "earn_rate_base"
    assert "debate_transcript" in review
    assert "judge_verdict" in review


def packet(chunk_id: str, source_url: str, field: str, value, confidence: float) -> NormalizedObjectPacket:
    return NormalizedObjectPacket(
        object_type="loyalty_intelligence",
        source_url=source_url,
        chunk_id=chunk_id,
        identity_hash=chunk_id,
        fields={
            field: ExtractedField(
                value=value,
                status="EXTRACTED",
                source_url=source_url,
                source_snippet="evidence",
                confidence=confidence,
            )
        },
    )


def raw_document(url: str, source_type: str) -> RawDocument:
    return RawDocument(
        url=url,
        url_hash=url[-8:],
        content="x " * 120,
        word_count=120,
        retrieved_at="2026-06-12T16:47:00+00:00",
        source_authority=0.9,
        metadata={"source_type": source_type},
    )


def test_detect_conflicts_builds_debate_ready_claims():
    field = "earn_mechanics.base_earn_rate"
    packets = [
        packet("c1", "https://official.example/rates", field, "10 points per dollar", 0.9),
        packet("c2", "https://blog.example/review", field, "5 points per dollar", 0.7),
        packet("c3", "https://forum.example/thread", field, "5 points per dollar", 0.6),
    ]
    documents = [
        raw_document("https://official.example/rates", "official"),
        raw_document("https://blog.example/review", "review"),
        raw_document("https://forum.example/thread", "forum"),
    ]

    conflicts = detect_conflicts_from_packets(packets, documents)

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["field_name"] == field
    assert conflict["volatility"] == "HIGH"
    assert conflict["claim_a"]["value"] == "5 points per dollar"
    assert conflict["claim_a"]["corroboration"] == 2
    assert conflict["claim_b"]["value"] == "10 points per dollar"
    assert conflict["claim_b"]["authority"] == "official"
    assert conflict["claim_b"]["date"] == date(2026, 6, 12)


def test_detect_conflicts_ignores_agreeing_sources():
    field = "program_basics.program_name"
    packets = [
        packet("c1", "https://a.example", field, "acme rewards", 0.9),
        packet("c2", "https://b.example", field, "acme rewards", 0.8),
    ]

    assert detect_conflicts_from_packets(packets, []) == []


def test_classify_volatility_is_universal():
    assert classify_volatility("earn_mechanics.base_earn_rate") == "HIGH"
    assert classify_volatility("burn_mechanics.point_value_cpp") == "HIGH"
    assert classify_volatility("burn_mechanics.expiry_policy") == "HIGH"
    assert classify_volatility("program_basics.program_name") == "LOW"
    assert classify_volatility("tier_system.tier_names") == "LOW"
    assert classify_volatility("cpp") == "HIGH"


def test_apply_adjudication_updates_field_report():
    report = FieldReport(
        entries=[
            FieldReportEntry(
                field_path="earn_mechanics.base_earn_rate",
                category="earn_mechanics",
                status="extracted",
                value="10 points per dollar",
                source_urls=["https://official.example"],
                confidence=0.7,
            ),
            FieldReportEntry(
                field_path="burn_mechanics.point_value_cpp",
                category="burn_mechanics",
                status="extracted",
                value=0.8,
                source_urls=["https://a.example"],
                confidence=0.6,
            ),
        ],
        extracted_count=2,
    )
    adjudicated = [
        {
            "field_name": "earn_mechanics.base_earn_rate",
            "winner": "B",
            "value": "5 points per dollar",
            "source_url": "https://blog.example",
            "confidence": 0.76,
            "resolution": "debate",
        },
        {
            "field_name": "burn_mechanics.point_value_cpp",
            "winner": "FLAG",
            "value": "0.8",
            "source_url": "https://a.example",
            "confidence": 0.40,
            "resolution": "flag",
        },
    ]

    updated = apply_adjudication_to_field_report(report, adjudicated)

    by_path = {entry.field_path: entry for entry in updated.entries}
    assert by_path["earn_mechanics.base_earn_rate"].value == "5 points per dollar"
    assert by_path["earn_mechanics.base_earn_rate"].source_urls == ["https://blog.example"]
    assert by_path["earn_mechanics.base_earn_rate"].confidence == 0.76
    assert by_path["burn_mechanics.point_value_cpp"].status == "flagged"
    assert by_path["burn_mechanics.point_value_cpp"].confidence == 0.40
    assert updated.extracted_count == 1
    assert updated.ambiguous_count == 0
    assert updated.flagged_count == 1
