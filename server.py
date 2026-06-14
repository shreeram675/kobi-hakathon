"""FastAPI REST backend for the Kobie Next.js frontend.

Endpoints:
  POST /api/run               → start a pipeline run (background thread)
  POST /api/run?mock=true     → skip to claims stage with pre-built mock data
  GET  /api/run               → list all run summaries
  GET  /api/run/{run_id}      → poll a single run (includes stage_status, status, conversation)
  POST /api/run/{run_id}/clarify  → submit a clarification answer for the input validator
  POST /api/run/{run_id}/converse → answer a grounded question
"""
from __future__ import annotations

import json
import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel as _PydanticBase

from schemas import (
    AgentState,
    BriefOutput,
    FieldReport,
    FieldReportEntry,
    FirecrawlScrapeOutput,
    build_initial_state,
    new_id,
    now_iso,
    RunMode,
)
from graph import (
    input_validator_node,
    query_generator_node,
    retrieval_node,
    firecrawl_node,
    ingest_node,
    adjudication_node,
    narrator_node,
)
from comparison import compare_claim_sets
from converse import answer_question

app = FastAPI(title="Kobie API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000",
                   "http://localhost:3001", "http://127.0.0.1:3001"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# UI stage IDs matching frontend schema.ts PIPELINE_STAGES
UI_STAGES = [
    "input_validator",
    "query_generator",
    "retrieval",
    "firecrawl_scraper",
    "chunking",
    "extraction",
    "claims",
    "adjudication",
    "output",
]


# ── Run record ─────────────────────────────────────────────────────────────────
class RunRecord:
    def __init__(
        self,
        run_id: str,
        user_input: str,
        mode: str,
        user_input_b: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.user_input = user_input
        self.user_input_b = user_input_b
        self.mode = mode
        self.state: AgentState = build_initial_state(user_input, RunMode(mode))
        self.state["run_id"] = run_id
        self.stage_status: dict[str, str] = {s: "idle" for s in UI_STAGES}
        self.active_stage: str | None = None
        self.run_status: str = "running"
        self.conversation: list[dict[str, Any]] = []
        self.compare_b: dict[str, Any] | None = None
        self.lock = threading.Lock()
        self.clarification_event = threading.Event()


STORE: dict[str, RunRecord] = {}
STORE_LOCK = threading.Lock()


# ── Serialization ─────────────────────────────────────────────────────────────
def _ser(v: Any) -> Any:
    if hasattr(v, "model_dump"):
        return v.model_dump()
    if isinstance(v, list):
        return [_ser(i) for i in v]
    if isinstance(v, dict):
        return {k: _ser(vv) for k, vv in v.items()}
    return v


def build_run_response(record: RunRecord) -> dict[str, Any]:
    with record.lock:
        result: dict[str, Any] = {k: _ser(v) for k, v in record.state.items()}
        result["stage_status"] = dict(record.stage_status)
        result["active_stage"] = record.active_stage
        result["status"] = record.run_status
        result["conversation"] = list(record.conversation)
        if record.compare_b is not None:
            result["compare_b"] = record.compare_b
    return result


def build_summary(record: RunRecord) -> dict[str, Any]:
    with record.lock:
        return {
            "run_id": record.run_id,
            "user_input": record.user_input,
            "mode": record.mode,
            "data_quality": record.state.get("data_quality", 0.0),
            "status": record.run_status,
            "created_at": record.state.get("created_at", ""),
        }


# ── Stage helpers ─────────────────────────────────────────────────────────────
def _mark(record: RunRecord, stage: str, status: str) -> None:
    with record.lock:
        record.stage_status[stage] = status
        if status == "running":
            record.active_stage = stage
        elif status in ("done", "error") and record.active_stage == stage:
            record.active_stage = None


def _apply(record: RunRecord, delta: dict) -> AgentState:
    with record.lock:
        record.state = {**record.state, **delta}
        return record.state


# ── Core pipeline (single program) ────────────────────────────────────────────
def _run_single_pipeline(record: RunRecord) -> bool:
    """Run one program through all pipeline stages. Returns True on success."""
    state = record.state

    # 1. Input Validator — loop until resolved, rejected, or clarification timeout
    _mark(record, "input_validator", "running")
    clarification_count = 0
    while True:
        try:
            delta = input_validator_node(state)
            state = _apply(record, delta)
        except Exception:
            _mark(record, "input_validator", "error")
            return False

        vr = state.get("validation_result")
        if vr and vr.status == "resolved":
            _mark(record, "input_validator", "done")
            break
        elif vr and vr.status == "needs_clarification" and clarification_count < 3:
            clarification_count += 1
            with record.lock:
                record.run_status = "clarification_needed"
            record.clarification_event.clear()
            if not record.clarification_event.wait(timeout=300):
                # User did not respond within 5 minutes
                _mark(record, "input_validator", "error")
                return False
            with record.lock:
                state = record.state
                record.run_status = "running"
        else:
            _mark(record, "input_validator", "error")
            return False

    # 2. Query Generator
    _mark(record, "query_generator", "running")
    try:
        delta = query_generator_node(state)
        state = _apply(record, delta)
        if state.get("query_generation_result"):
            _mark(record, "query_generator", "done")
        else:
            _mark(record, "query_generator", "error")
            return False
    except Exception:
        _mark(record, "query_generator", "error")
        return False

    # 3. Retrieval
    _mark(record, "retrieval", "running")
    try:
        delta = retrieval_node(state)
        state = _apply(record, delta)
        if state.get("retrieval_result"):
            _mark(record, "retrieval", "done")
        else:
            _mark(record, "retrieval", "error")
            return False
    except Exception:
        _mark(record, "retrieval", "error")
        return False

    # 4. Firecrawl Scraper
    _mark(record, "firecrawl_scraper", "running")
    total_scrape_urls = len(state.get("retrieved_urls", []))

    def _on_scrape_progress(completed_blocks, total):
        successful = sum(1 for b in completed_blocks if b.scrape_status == "success" and b.content)
        partial = FirecrawlScrapeOutput(
            total_urls=total,
            successful_scrapes=successful,
            failed_scrapes=len(completed_blocks) - successful,
            blocks=completed_blocks,
        )
        _apply(record, {"scraped_blocks": completed_blocks, "firecrawl_result": partial})

    try:
        delta = firecrawl_node(state, on_progress=_on_scrape_progress)
        state = _apply(record, delta)
        fc = state.get("firecrawl_result")
        if fc and fc.successful_scrapes > 0:
            _mark(record, "firecrawl_scraper", "done")
        else:
            _mark(record, "firecrawl_scraper", "error")
            return False
    except Exception:
        _mark(record, "firecrawl_scraper", "error")
        return False

    # 5–7. Ingest (raw store → chunking → extraction → claims)
    _mark(record, "chunking", "running")
    try:
        delta = ingest_node(state)
        state = _apply(record, delta)
        chunks = state.get("semantic_chunks", [])
        packets = state.get("normalized_packets", [])
        fr = state.get("field_report")

        if chunks:
            _mark(record, "chunking", "done")
        else:
            _mark(record, "chunking", "error")
            _mark(record, "extraction", "error")
            _mark(record, "claims", "error")
            return False

        if packets:
            _mark(record, "extraction", "done")
        else:
            _mark(record, "extraction", "error")
            _mark(record, "claims", "error")
            return False

        if fr:
            _mark(record, "claims", "done")
        else:
            _mark(record, "claims", "error")
            return False
    except Exception:
        _mark(record, "chunking", "error")
        _mark(record, "extraction", "error")
        _mark(record, "claims", "error")
        return False

    # 8. Adjudication
    _mark(record, "adjudication", "running")
    try:
        delta = adjudication_node(state)
        state = _apply(record, delta)
        _mark(record, "adjudication", "done")
    except Exception:
        _mark(record, "adjudication", "error")
        return False

    # 9. Narration → output
    _mark(record, "output", "running")
    try:
        delta = narrator_node(state)
        state = _apply(record, delta)
        if state.get("final_brief"):
            _mark(record, "output", "done")
        else:
            _mark(record, "output", "error")
            return False
    except Exception:
        _mark(record, "output", "error")
        return False

    return True


# ── Pipeline thread entry points ──────────────────────────────────────────────
def run_pipeline(record: RunRecord) -> None:
    """Thread entry point — handles single, compare, and converse modes."""
    if record.mode == "compare" and record.user_input_b:
        # Run program A
        success_a = _run_single_pipeline(record)

        # Run program B in parallel (separate record, not in STORE)
        record_b = RunRecord(record.run_id + "_b", record.user_input_b, "compare")
        thread_b = threading.Thread(
            target=_run_single_pipeline, args=(record_b,), daemon=True
        )
        thread_b.start()
        thread_b.join()

        if success_a and record_b.run_status != "error":
            a_state = record.state
            b_state = record_b.state
            try:
                comparison = compare_claim_sets(
                    record.run_id,
                    a_state.get("program_name") or record.user_input,
                    b_state.get("program_name") or record.user_input_b,
                    a_state.get("adjudicated_claims", []),
                    b_state.get("adjudicated_claims", []),
                )
                with record.lock:
                    record.state = {**record.state, "comparison_output": comparison}
            except Exception:
                pass

            with record.lock:
                record.compare_b = build_run_response(record_b)

        with record.lock:
            record.run_status = "done" if success_a else "error"

    else:
        success = _run_single_pipeline(record)

        if success:
            program_name = record.state.get("program_name") or record.user_input
            with record.lock:
                record.conversation = [
                    {
                        "role": "assistant",
                        "message": (
                            f"I've analysed {program_name}. Ask me anything about its earn "
                            "rates, tiers, partners, or member sentiment — I'll answer only "
                            "from the extracted claims."
                        ),
                        "created_at": now_iso(),
                    }
                ]

        with record.lock:
            record.run_status = "done" if success else "error"


# ── Mock field-report data ────────────────────────────────────────────────────
_MOCK_PROFILES: dict[str, dict[str, Any]] = {
    "delta skymiles": {
        "program_name": "Delta SkyMiles",
        "brand": "Delta Air Lines",
        "fields": {
            "program_basics.program_name": ("Delta SkyMiles", "extracted", 0.99, 4),
            "program_basics.brand": ("Delta Air Lines", "extracted", 0.99, 4),
            "program_basics.industry": ("Airline", "extracted", 0.98, 3),
            "program_basics.program_type": ("Frequent Flyer", "extracted", 0.97, 3),
            "program_basics.geography": ("Global", "extracted", 0.95, 3),
            "program_basics.membership_count": ("Over 100 million members", "extracted", 0.82, 2),
            "earn_mechanics.base_earn_rate": ("5 miles per $1 on Delta flights", "extracted", 0.93, 3),
            "earn_mechanics.bonus_categories": ("First class earns 8 miles/$ ; Medallion bonus up to 11x", "extracted", 0.88, 2),
            "earn_mechanics.non_transactional_earn": ("Miles earned via Amex credit cards, hotel stays, car rentals", "extracted", 0.85, 2),
            "burn_mechanics.redemption_options": ("Award flights, upgrades, seat upgrades, partner hotels, gift cards", "extracted", 0.92, 3),
            "burn_mechanics.redemption_thresholds": ("No fixed redemption chart — dynamic pricing; flights start ~5,000 miles", "ambiguous", 0.68, 2),
            "burn_mechanics.point_value_cpp": ("~1.1–1.3 cents per mile on average", "extracted", 0.74, 2),
            "burn_mechanics.expiry_policy": ("Miles expire after 24 months of account inactivity", "extracted", 0.91, 3),
            "tier_system.tier_names": ("Silver Medallion, Gold Medallion, Platinum Medallion, Diamond Medallion", "extracted", 0.97, 4),
            "tier_system.qualification_criteria": ("Medallion Qualifying Dollars (MQDs) + Medallion Qualifying Miles (MQMs) or segments", "extracted", 0.90, 3),
            "tier_system.tier_benefits": ("Priority boarding, complimentary upgrades, lounge access (Diamond), bonus miles", "extracted", 0.88, 3),
            "tier_system.qualification_period": ("January 1 – December 31 calendar year", "extracted", 0.95, 3),
            "partnerships.partner_names": ("American Express, Lyft, Starbucks, Airbnb, Hertz, Hilton, Marriott", "extracted", 0.87, 3),
            "partnerships.partnership_type": ("Credit card (Amex), hotel, rideshare, car rental, retail", "extracted", 0.85, 2),
            "partnerships.details": ("Amex Delta cards earn 2–3x miles on Delta purchases; Starbucks earns 1 mile per $1", "extracted", 0.80, 2),
            "digital_experience.mobile_app_available": ("Yes — Fly Delta app on iOS and Android", "extracted", 0.99, 4),
            "digital_experience.app_ratings": ("4.8 / 5 App Store ; 4.5 / 5 Play Store", "extracted", 0.88, 3),
            "digital_experience.personalization_features": ("Personalized upgrade offers, trip recommendations, real-time flight updates", "extracted", 0.78, 2),
            "digital_experience.gamification_features": ("SkyMiles Shopping portal with bonus earn events; limited-time promotions", "extracted", 0.72, 2),
            "member_sentiment.ratings": ("Generally positive — praised for upgrade availability at top tiers", "extracted", 0.76, 2),
            "member_sentiment.common_praise": ("Strong domestic network, reliable Amex partnership, easy miles earning", "extracted", 0.80, 3),
            "member_sentiment.common_complaints": ("Dynamic award pricing seen as unpredictable; miles devalued over time", "extracted", 0.83, 3),
            "member_sentiment.sources_checked": ("FlyerTalk, Reddit r/delta, Trustpilot, App Store reviews", "extracted", 0.90, 3),
            "competitive_position.key_differentiators": ("Largest domestic US network, strong Amex co-brand, high app satisfaction", "extracted", 0.85, 2),
            "competitive_position.weaknesses": ("No fixed award chart; miles value eroded by dynamic pricing", "extracted", 0.82, 2),
            "competitive_position.closest_competitors": ("United MileagePlus, American AAdvantage, Southwest Rapid Rewards", "extracted", 0.90, 3),
        },
    },
    "marriott bonvoy": {
        "program_name": "Marriott Bonvoy",
        "brand": "Marriott International",
        "fields": {
            "program_basics.program_name": ("Marriott Bonvoy", "extracted", 0.99, 5),
            "program_basics.brand": ("Marriott International", "extracted", 0.99, 5),
            "program_basics.industry": ("Hotel", "extracted", 0.98, 4),
            "program_basics.program_type": ("Hotel Loyalty", "extracted", 0.97, 4),
            "program_basics.geography": ("Global — 140+ countries", "extracted", 0.96, 4),
            "program_basics.membership_count": ("Over 196 million members", "extracted", 0.88, 3),
            "earn_mechanics.base_earn_rate": ("10 points per $1 at Marriott hotels", "extracted", 0.95, 4),
            "earn_mechanics.bonus_categories": ("Elite status earns 25–75% bonus; co-brand card earns 6x at hotels", "extracted", 0.90, 3),
            "earn_mechanics.non_transactional_earn": ("Points via Chase/Amex Bonvoy cards, dining, car rentals, retail partners", "extracted", 0.84, 3),
            "burn_mechanics.redemption_options": ("Free nights, room upgrades, airline miles transfer (39 partners), experiences", "extracted", 0.93, 4),
            "burn_mechanics.redemption_thresholds": ("Category 1 hotels from 7,500 pts/night; Category 8 up to 100,000 pts/night", "extracted", 0.89, 3),
            "burn_mechanics.point_value_cpp": ("~0.7–0.9 cents per point", "extracted", 0.77, 2),
            "burn_mechanics.expiry_policy": ("Points expire after 24 months of inactivity", "extracted", 0.92, 3),
            "tier_system.tier_names": ("Member, Silver Elite, Gold Elite, Platinum Elite, Titanium Elite, Ambassador Elite", "extracted", 0.97, 5),
            "tier_system.qualification_criteria": ("Nights stayed per calendar year: Silver 10, Gold 25, Platinum 50, Titanium 75, Ambassador 100", "extracted", 0.95, 4),
            "tier_system.tier_benefits": ("Room upgrades, lounge access (Platinum+), Welcome Gift, late checkout, dedicated Ambassador service", "extracted", 0.90, 4),
            "tier_system.qualification_period": ("January 1 – December 31", "extracted", 0.97, 4),
            "partnerships.partner_names": ("Chase, American Express, United, Delta, Air Canada, Hertz, Uber", "extracted", 0.88, 3),
            "partnerships.partnership_type": ("Credit card, airline transfer, car rental, rideshare", "extracted", 0.86, 3),
            "partnerships.details": ("Transfer to 39 airlines at 3:1 ratio with 5,000-pt bonus on 60,000+ transfer", "extracted", 0.82, 3),
            "digital_experience.mobile_app_available": ("Yes — Marriott Bonvoy app on iOS and Android", "extracted", 0.99, 5),
            "digital_experience.app_ratings": ("4.8 / 5 App Store ; 4.2 / 5 Play Store", "extracted", 0.85, 3),
            "digital_experience.personalization_features": ("Mobile check-in/out, digital key, room preference selection", "extracted", 0.85, 3),
            "digital_experience.gamification_features": ("Marriott Bonvoy Moments (experiences auction), limited earning promotions", "extracted", 0.74, 2),
            "member_sentiment.ratings": ("Mixed — elites satisfied, general members critical of award inflation", "ambiguous", 0.70, 2),
            "member_sentiment.common_praise": ("Vast property portfolio, airline transfer flexibility, strong elite benefits", "extracted", 0.82, 3),
            "member_sentiment.common_complaints": ("Point devaluation after merger, inconsistent elite recognition at properties", "extracted", 0.85, 3),
            "member_sentiment.sources_checked": ("FlyerTalk, Reddit r/marriott, Trustpilot, App Store", "extracted", 0.90, 3),
            "competitive_position.key_differentiators": ("Largest hotel portfolio globally, airline transfer to 39 carriers", "extracted", 0.88, 3),
            "competitive_position.weaknesses": ("Post-merger inconsistency; ~0.7 cpp point value trails Hyatt World of Hyatt", "extracted", 0.80, 2),
            "competitive_position.closest_competitors": ("Hilton Honors, World of Hyatt, IHG One Rewards", "extracted", 0.91, 4),
        },
    },
    "hilton honors": {
        "program_name": "Hilton Honors",
        "brand": "Hilton Worldwide",
        "fields": {
            "program_basics.program_name": ("Hilton Honors", "extracted", 0.99, 5),
            "program_basics.brand": ("Hilton Worldwide", "extracted", 0.99, 4),
            "program_basics.industry": ("Hotel", "extracted", 0.98, 4),
            "program_basics.program_type": ("Hotel Loyalty", "extracted", 0.97, 4),
            "program_basics.geography": ("Global — 122+ countries", "extracted", 0.95, 4),
            "program_basics.membership_count": ("Over 180 million members", "extracted", 0.86, 3),
            "earn_mechanics.base_earn_rate": ("10 points per $1 at Hilton hotels", "extracted", 0.95, 4),
            "earn_mechanics.bonus_categories": ("Elite bonus 25–100%; Amex Hilton Surpass earns 12x at Hilton", "extracted", 0.88, 3),
            "earn_mechanics.non_transactional_earn": ("Amex co-brand cards, dining via Hilton Honors Dining, partner earn", "extracted", 0.82, 3),
            "burn_mechanics.redemption_options": ("Free nights (Points & Money available), room upgrades, Amazon, charity", "extracted", 0.90, 3),
            "burn_mechanics.redemption_thresholds": ("Standard rewards start ~5,000 pts; premium properties up to 150,000 pts/night", "extracted", 0.85, 3),
            "burn_mechanics.point_value_cpp": ("~0.5–0.6 cents per point — lower than Marriott", "extracted", 0.75, 2),
            "burn_mechanics.expiry_policy": ("Points expire after 12 months of inactivity", "extracted", 0.91, 3),
            "tier_system.tier_names": ("Member, Silver, Gold, Diamond", "extracted", 0.97, 5),
            "tier_system.qualification_criteria": ("Nights: Silver 10, Gold 40, Diamond 60 per year", "extracted", 0.94, 4),
            "tier_system.tier_benefits": ("Executive Lounge (Diamond), complimentary breakfast (Diamond), room upgrades, 100% bonus points", "extracted", 0.89, 4),
            "tier_system.qualification_period": ("January 1 – December 31", "extracted", 0.97, 4),
            "partnerships.partner_names": ("American Express, Amazon, Lyft, CarRentals.com, Ticketmaster", "extracted", 0.85, 3),
            "partnerships.partnership_type": ("Credit card, retail, rideshare, car rental, entertainment", "extracted", 0.83, 2),
            "partnerships.details": ("Amex Hilton cards offer 7–14x at Hilton; Amazon earn via Hilton portal; no airline transfer", "extracted", 0.80, 2),
            "digital_experience.mobile_app_available": ("Yes — Hilton Honors app on iOS and Android", "extracted", 0.99, 5),
            "digital_experience.app_ratings": ("4.8 / 5 App Store ; 4.6 / 5 Play Store", "extracted", 0.88, 3),
            "digital_experience.personalization_features": ("Digital key, room selection, mobile check-in/out, Connected Room (IoT control)", "extracted", 0.87, 3),
            "digital_experience.gamification_features": ("Hilton Honors Challenges, bonus point promotions, seasonal offers", "extracted", 0.76, 2),
            "member_sentiment.ratings": ("Positive — Diamond members highly satisfied with breakfast and lounge benefits", "extracted", 0.79, 3),
            "member_sentiment.common_praise": ("Consistent complimentary breakfast for Diamond, strong app experience, broad portfolio", "extracted", 0.83, 3),
            "member_sentiment.common_complaints": ("Lower point value vs competitors; no airline transfer partners", "extracted", 0.81, 3),
            "member_sentiment.sources_checked": ("FlyerTalk, Reddit r/hilton, Trustpilot, App Store", "extracted", 0.90, 3),
            "competitive_position.key_differentiators": ("Complimentary Diamond breakfast globally, strong Connected Room tech, Amex partnership", "extracted", 0.86, 3),
            "competitive_position.weaknesses": ("No airline miles transfer; ~0.5 cpp among lowest in hotel space", "extracted", 0.82, 2),
            "competitive_position.closest_competitors": ("Marriott Bonvoy, World of Hyatt, IHG One Rewards", "extracted", 0.91, 4),
        },
    },
}


from datetime import date as _date

_TODAY = str(_date.today())

# Raw conflicts injected into state["conflicts"] before adjudication_node runs.
# claim_a / claim_b must match the dict shape produced by _claim_from_group():
#   value, source_url, date, authority, corroboration, confidence
# Score gap ≤ 0.20  → real Groq debate  |  gap > 0.20 → auto-resolved
_MOCK_CONFLICTS: dict[str, list[dict[str, Any]]] = {
    "delta skymiles": [
        # ① Close gap → real debate
        {
            "field_name": "burn_mechanics.point_value_cpp",
            "volatility": "HIGH",
            "claim_a": {
                "value": "~1.3 cents per mile (based on flight redemptions)",
                "source_url": "https://thepointsguy.com/guide/monthly-valuations/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 3,
                "confidence": 0.74,
            },
            "claim_b": {
                "value": "~0.9–1.1 cents per mile (average across all redemptions)",
                "source_url": "https://nerdwallet.com/article/travel/delta-skymiles-value",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.68,
            },
        },
        # ② Close gap → real debate
        {
            "field_name": "earn_mechanics.base_earn_rate",
            "volatility": "HIGH",
            "claim_a": {
                "value": "5 miles per $1 on Delta flights (Main Cabin)",
                "source_url": "https://www.delta.com/us/en/skymiles/how-to-earn-miles",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.93,
            },
            "claim_b": {
                "value": "5–10 miles per $1 depending on fare class and Medallion status",
                "source_url": "https://thepointsguy.com/guide/delta-skymiles-earning/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.80,
            },
        },
        # ③ Wide gap → auto-resolved
        {
            "field_name": "burn_mechanics.expiry_policy",
            "volatility": "LOW",
            "claim_a": {
                "value": "Miles never expire",
                "source_url": "https://old-blog.example.com/delta-miles-expire",
                "date": "2019-01-15",
                "authority": "blog",
                "corroboration": 1,
                "confidence": 0.30,
            },
            "claim_b": {
                "value": "Miles expire after 24 months of account inactivity",
                "source_url": "https://www.delta.com/us/en/skymiles/skymiles-program-overview",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 3,
                "confidence": 0.91,
            },
        },
        # ④ Close gap → real debate
        {
            "field_name": "tier_system.tier_thresholds",
            "volatility": "HIGH",
            "claim_a": {
                "value": "Silver: $3,000 MQD; Gold: $8,000 MQD; Platinum: $12,000 MQD; Diamond: $20,000 MQD",
                "source_url": "https://www.delta.com/us/en/skymiles/medallion-program",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 3,
                "confidence": 0.88,
            },
            "claim_b": {
                "value": "Silver: $3,000 MQD; Gold: $8,000 MQD; Platinum: $15,000 MQD; Diamond: $28,000 MQD (2024 revised)",
                "source_url": "https://thepointsguy.com/news/delta-medallion-2024-changes/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.76,
            },
        },
    ],
    "marriott bonvoy": [
        # ① Close gap → real debate
        {
            "field_name": "burn_mechanics.point_value_cpp",
            "volatility": "HIGH",
            "claim_a": {
                "value": "~0.9 cents per point on free night redemptions",
                "source_url": "https://thepointsguy.com/guide/monthly-valuations/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 3,
                "confidence": 0.77,
            },
            "claim_b": {
                "value": "~0.7 cents per point (average across all redemption types)",
                "source_url": "https://nerdwallet.com/article/travel/marriott-bonvoy-points-value",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.68,
            },
        },
        # ② Close gap → real debate
        {
            "field_name": "tier_system.qualification_criteria",
            "volatility": "LOW",
            "claim_a": {
                "value": "Nights only: Silver 10, Gold 25, Platinum 50, Titanium 75, Ambassador 100",
                "source_url": "https://www.marriott.com/loyalty/member-benefits/eliteMemberBenefits.mi",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.91,
            },
            "claim_b": {
                "value": "Nights or revenue: Silver 10 nights or $3,000; Gold 25 nights or $10,000 spend",
                "source_url": "https://thepointsguy.com/guide/marriott-bonvoy-status/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.78,
            },
        },
        # ③ Wide gap → auto-resolved
        {
            "field_name": "burn_mechanics.expiry_policy",
            "volatility": "LOW",
            "claim_a": {
                "value": "Points expire after 12 months of inactivity",
                "source_url": "https://old-travel-blog.example.com/bonvoy-expiry",
                "date": "2020-03-10",
                "authority": "blog",
                "corroboration": 1,
                "confidence": 0.35,
            },
            "claim_b": {
                "value": "Points expire after 24 months of account inactivity",
                "source_url": "https://www.marriott.com/loyalty/terms/default.mi",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.95,
            },
        },
        # ④ Close gap → real debate
        {
            "field_name": "partnerships.transfer_ratios",
            "volatility": "LOW",
            "claim_a": {
                "value": "3:1 Marriott points to airline miles (e.g. 3,000 pts = 1,000 miles)",
                "source_url": "https://www.marriott.com/loyalty/redeem/travel/air.mi",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.89,
            },
            "claim_b": {
                "value": "3:1 ratio with a 5,000-mile bonus per 60,000-point transfer block",
                "source_url": "https://thepointsguy.com/guide/transfer-marriott-to-airlines/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 3,
                "confidence": 0.82,
            },
        },
    ],
    "hilton honors": [
        # ① Close gap → real debate
        {
            "field_name": "burn_mechanics.point_value_cpp",
            "volatility": "HIGH",
            "claim_a": {
                "value": "~0.6 cents per point for standard room redemptions",
                "source_url": "https://thepointsguy.com/guide/monthly-valuations/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 3,
                "confidence": 0.72,
            },
            "claim_b": {
                "value": "~0.5 cents per point on average across all redemption types",
                "source_url": "https://nerdwallet.com/article/travel/hilton-honors-points-value",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.65,
            },
        },
        # ② Close gap → real debate
        {
            "field_name": "tier_system.tier_benefits",
            "volatility": "LOW",
            "claim_a": {
                "value": "Diamond: complimentary breakfast, executive lounge, 100% bonus points, suite upgrades",
                "source_url": "https://www.hilton.com/en/hilton-honors/member-benefits/",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.90,
            },
            "claim_b": {
                "value": "Diamond: breakfast at select properties only; lounge access not guaranteed at all brands",
                "source_url": "https://thepointsguy.com/guide/hilton-diamond-benefits/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 3,
                "confidence": 0.78,
            },
        },
        # ③ Wide gap → auto-resolved
        {
            "field_name": "burn_mechanics.expiry_policy",
            "volatility": "LOW",
            "claim_a": {
                "value": "Points expire after 24 months of inactivity",
                "source_url": "https://old-hilton-blog.example.com/expiry",
                "date": "2018-06-01",
                "authority": "blog",
                "corroboration": 1,
                "confidence": 0.28,
            },
            "claim_b": {
                "value": "Points expire after 12 months of account inactivity",
                "source_url": "https://www.hilton.com/en/hilton-honors/terms-conditions/",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 4,
                "confidence": 0.94,
            },
        },
        # ④ Close gap → real debate
        {
            "field_name": "earn_mechanics.base_earn_rate",
            "volatility": "HIGH",
            "claim_a": {
                "value": "10 points per $1 spent at Hilton portfolio properties",
                "source_url": "https://www.hilton.com/en/hilton-honors/earn-points/",
                "date": _TODAY,
                "authority": "official",
                "corroboration": 5,
                "confidence": 0.95,
            },
            "claim_b": {
                "value": "10 base points per $1 plus 5x bonus points = 15 points per $1 effective rate",
                "source_url": "https://thepointsguy.com/guide/hilton-honors-earn/",
                "date": _TODAY,
                "authority": "blog",
                "corroboration": 2,
                "confidence": 0.80,
            },
        },
    ],
}


def _fuzzy_match_profile(user_input: str) -> str | None:
    """Match user input to a known mock profile key."""
    needle = user_input.lower().strip()
    for key in _MOCK_PROFILES:
        if key in needle or any(word in needle for word in key.split()):
            return key
    return None


def _build_mock_field_report(profile_key: str) -> FieldReport:
    profile = _MOCK_PROFILES[profile_key]
    entries: list[FieldReportEntry] = []
    extracted = ambiguous = not_found = 0
    for field_path, (value, status, confidence, corroboration) in profile["fields"].items():
        category = field_path.split(".")[0]
        entry = FieldReportEntry(
            field_path=field_path,
            category=category,
            status=status,
            value=value,
            confidence=confidence,
            corroboration_count=corroboration,
            source_urls=[f"https://mock-source.example/{profile_key.replace(' ', '-')}/{field_path}"],
            source_snippet=f"Mock source for {field_path}: {value}",
        )
        entries.append(entry)
        if status == "extracted":
            extracted += 1
        elif status == "ambiguous":
            ambiguous += 1
        else:
            not_found += 1

    return FieldReport(
        entity_name=profile["program_name"],
        entries=entries,
        extracted_count=extracted,
        ambiguous_count=ambiguous,
        not_found_count=not_found,
        flagged_count=0,
    )


def _run_mock_pipeline(record: RunRecord) -> None:
    """Skip retrieval/extraction; inject mock field_report and run from claims onward."""
    program_key = _fuzzy_match_profile(record.user_input)
    if program_key is None:
        # Fall back to Delta SkyMiles as default
        program_key = "delta skymiles"

    profile = _MOCK_PROFILES[program_key]

    # Mark all pre-claims stages as done instantly
    for stage in ["input_validator", "query_generator", "retrieval", "firecrawl_scraper", "chunking", "extraction"]:
        _mark(record, stage, "done")

    _mark(record, "claims", "running")
    field_report = _build_mock_field_report(program_key)
    raw_conflicts = _MOCK_CONFLICTS.get(program_key, [])
    _apply(record, {
        "program_name": profile["program_name"],
        "brand": profile["brand"],
        "field_report": field_report,
        "conflicts": raw_conflicts,   # real adjudication/debate runs from here
        "adjudicated": [],
    })
    _mark(record, "claims", "done")

    state = record.state

    # Adjudication
    _mark(record, "adjudication", "running")
    try:
        delta = adjudication_node(state)
        state = _apply(record, delta)
        _mark(record, "adjudication", "done")
    except Exception as exc:
        _apply(record, {"errors": [*state.get("errors", []), {"stage": "adjudication", "message": str(exc)}]})
        _mark(record, "adjudication", "error")

    # Narration → output
    _mark(record, "output", "running")
    try:
        delta = narrator_node(state)
        state = _apply(record, delta)
        _mark(record, "output", "done")
    except Exception as exc:
        _apply(record, {"errors": [*state.get("errors", []), {"stage": "output", "message": str(exc)}]})
        _mark(record, "output", "error")

    with record.lock:
        record.run_status = "done"


# ── Request / response models ─────────────────────────────────────────────────
class CreateRunBody(_PydanticBase):
    user_input: str
    mode: str = "single"
    user_input_b: str | None = None
    mock: bool = False


class ConverseRequest(_PydanticBase):
    message: str


class ClarifyRequest(_PydanticBase):
    answer: str


# ── Routes ────────────────────────────────────────────────────────────────────
@app.post("/api/run", status_code=201)
def create_run(body: CreateRunBody) -> dict[str, str]:
    if not body.user_input.strip():
        raise HTTPException(status_code=400, detail="user_input is required")

    mode = body.mode if body.mode in ("single", "compare", "converse") else "single"
    run_id = new_id("run")

    record = RunRecord(run_id, body.user_input.strip(), mode, body.user_input_b)
    with STORE_LOCK:
        STORE[run_id] = record

    target = _run_mock_pipeline if body.mock else run_pipeline
    threading.Thread(target=target, args=(record,), daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/run")
def list_runs() -> list[dict[str, Any]]:
    with STORE_LOCK:
        records = list(STORE.values())
    return sorted(
        [build_summary(r) for r in records],
        key=lambda s: s["created_at"],
        reverse=True,
    )


@app.get("/api/run/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with STORE_LOCK:
        record = STORE.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return build_run_response(record)


@app.post("/api/run/{run_id}/clarify")
def clarify(run_id: str, body: ClarifyRequest) -> dict[str, Any]:
    with STORE_LOCK:
        record = STORE.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not body.answer.strip():
        raise HTTPException(status_code=400, detail="answer is required")

    with record.lock:
        if record.run_status != "clarification_needed":
            raise HTTPException(status_code=400, detail="run is not waiting for clarification")
        messages: list[dict[str, str]] = list(record.state.get("validation_messages") or [])
        vr = record.state.get("validation_result")
        if vr is not None:
            messages.append({"role": "assistant", "content": json.dumps(vr.model_dump())})
        messages.append({"role": "user", "content": body.answer.strip()})
        record.state["validation_messages"] = messages

    record.clarification_event.set()
    return {"ok": True}


@app.post("/api/run/{run_id}/converse")
def converse(run_id: str, body: ConverseRequest) -> dict[str, Any]:
    with STORE_LOCK:
        record = STORE.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    with record.lock:
        final_brief: BriefOutput | None = record.state.get("final_brief")
        field_report: FieldReport | None = record.state.get("field_report")

    if final_brief is None:
        raise HTTPException(status_code=400, detail="Pipeline has not completed — no brief available yet.")

    try:
        answer = answer_question(body.message.strip(), final_brief, field_report)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    created_at = now_iso()
    with record.lock:
        record.conversation.append(
            {"role": "user", "message": body.message.strip(), "created_at": created_at}
        )
        record.conversation.append(
            {
                "role": "assistant",
                "message": answer.answer,
                "answer": answer.model_dump(),
                "created_at": created_at,
            }
        )

    return answer.model_dump()
