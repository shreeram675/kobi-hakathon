r"""Quick GroqCloud/Gemini LangGraph probe.

Usage:
    .\.venv\Scripts\python.exe test_input_validator.py "Air India"
    .\.venv\Scripts\python.exe test_input_validator.py "Marriott"
"""

from __future__ import annotations

import argparse
import json

from graph import run_validation_chat


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the Kobie validator -> query-generator LangGraph flow.")
    parser.add_argument("message", nargs="+", help="User input to validate, for example: Air India")
    args = parser.parse_args()

    user_input = " ".join(args.message)
    state = run_validation_chat([{"role": "user", "content": user_input}])
    result = state["validation_result"]

    print("\nINPUT VALIDATOR RESULT")
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=True))

    print("\nNEXT NODE")
    if result.status == "resolved" and result.identity:
        print("resolved -> query_generator")
        print(f"program_name: {result.identity.program_name}")
        print(f"domain: {result.identity.domain}")
        if state["query_generation_result"]:
            print("\nQUERY GENERATOR RESULT")
            print(json.dumps(state["query_generation_result"].model_dump(), indent=2, ensure_ascii=True))
        elif state["errors"]:
            print("\nQUERY GENERATOR ERROR")
            print(state["errors"][-1].message)
    else:
        print("needs_clarification -> END")
        for question in result.follow_up_questions:
            print(f"- {question}")


if __name__ == "__main__":
    main()
