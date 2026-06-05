# Kobie Phase 2 Competitive Intelligence Agent

Initial implementation scaffold based on the root-level `arcguide` reference.

## What This Project Is

Kobie researches loyalty programs with a grounded evidence pipeline:

1. Validate the input and resolve one canonical loyalty program identity.
2. Retrieve official and non-official sources.
3. Extract structured claims across the ArcGuide schema.
4. Verify confidence, conflicts, and unsupported claims.
5. Generate an analyst-grade brief.
6. Compare programs.
7. Answer follow-up questions only from stored extracted JSON.

The `arcguide` file remains the source of truth. Before changing any stage,
search the relevant `AG-*` section there.

## Setup

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

## Run

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

Open the `Input verifier` tab. The LangGraph flow starts with input validation.
When the validator resolves `program_name` and `domain`, the output flows into
the Gemini query-generator node and displays the Tavily query plan.

## Input Verifier LLM

`validation.py` no longer uses static aliases. It sends the user's input to a
chat LLM with the ArcGuide `INPUT verifier` prompt and expects JSON back.

The project includes a local `.env` template configured for GroqCloud:

```powershell
$env:INPUT_VERIFIER_API_BASE="https://api.groq.com/openai/v1/chat/completions"
$env:INPUT_VERIFIER_API_KEY="your_groqcloud_api_key"
$env:INPUT_VERIFIER_MODEL="llama-3.1-8b-instant"
```

Resolved validator output is converted into the downstream program identity,
especially `program_name` and `domain`. The `domain` value is universal
free-form text, so programs can belong to any industry category returned by the
input verifier.

## Query Generator LLM

`query_generator.py` uses Gemini 2.5 Flash through the Gemini `generateContent`
REST API. Add your Gemini key to `.env`:

```powershell
$env:GEMINI_API_KEY="your_gemini_api_key"
$env:GEMINI_API_BASE="https://generativelanguage.googleapis.com/v1beta"
$env:QUERY_GENERATOR_MODEL="gemini-2.5-flash"
```

The query generator receives only the validated program identity and returns a
maximum of 15 structured Tavily queries.

For a quick terminal test after adding your key to `.env`:

```powershell
.\.venv\Scripts\python.exe test_input_validator.py "Air India"
.\.venv\Scripts\python.exe test_input_validator.py "Marriott"
.\.venv\Scripts\python.exe test_input_validator.py "Flying Returns"
```

The output shows the validator JSON and whether the identity is ready for the
next node:

```text
resolved -> query_generator
```

or:

```text
needs_clarification -> END
```

## Key Rule

Never use LLM training memory as a source of loyalty-program facts. Supported
claims must include `source_url` and `access_date`; absent data should become
`not_found/manual_review_needed` rather than guessed values.
