"""Manual end-to-end test for the 5-step adversarial debate engine.

Requires GROQ_API_KEY in the environment. Run:
    python test_debate.py

Expected outcome: B wins (newer date, higher corroboration on a HIGH
volatility field), deciding factor recency or corroboration, steps used 5.
"""

from __future__ import annotations

import asyncio
from datetime import date

from pipeline.adjudication.debate_engine import run_debate


CONFLICT = {
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


def main() -> None:
    result = asyncio.run(run_debate(CONFLICT, use_rebuttal=True))

    print("=" * 70)
    print(f"Winner:              {result['winner']}")
    print(f"Winning value:       {result['winning_value']}")
    print(f"Deciding factor:     {result['deciding_factor']}")
    print(f"Reasoning:           {result['reasoning']}")
    print(f"Rebuttal assessment: {result['rebuttal_assessment']}")
    print(f"Steps used:          {result['steps_used']}")
    print(f"Final confidence:    {result['final_confidence']:.2f}")
    print("=" * 70)
    print("\n--- Argument A (official site) ---")
    print(result["argument_a"])
    print("\n--- Argument B (headforpoints) ---")
    print(result["argument_b"])
    print("\n--- Rebuttal A ---")
    print(result["rebuttal_a"] or "(skipped)")
    print("\n--- Rebuttal B ---")
    print(result["rebuttal_b"] or "(skipped)")


if __name__ == "__main__":
    main()
