# ADR-001: Use Anthropic API with claude-sonnet-4-6

**Status:** Accepted  
**Date:** 2026-06-19  
**Deciders:** San Lee

---

## Context

The classifier and generator both require an LLM. The main alternatives were:

- **Anthropic API** (`claude-sonnet-4-6`) — strong instruction-following, native tool-use support for structured output, Python SDK
- **OpenAI API** (`gpt-4o`) — comparable capability, also has function-calling for structured output
- **Local model** (Ollama, llama.cpp) — no API cost, but weaker instruction-following and no reliable structured-output enforcement at this tier

The project needed reliable structured JSON output (valid enum values, no hallucinated labels) without application-level validation code as the primary safety net.

## Decision

Use the Anthropic Python SDK with `claude-sonnet-4-6`. The API key is read from the `ANTHROPIC_API_KEY` environment variable.

## Consequences

- **Tool use (`tool_choice: "tool"`)** forces the model to call a named tool with a defined JSON schema, so the response arrives as structured fields instead of free text to parse. The schema's enums strongly bias the model toward valid labels, but they are a *guided prior*, not a hard server-side constraint — an out-of-enum label is still possible, so `classify.py` validates the returned labels in code (`_validate` / `InvalidLabelError`) and re-samples once before giving up. This shape-guarantee-plus-thin-guard is the key reliability mechanism for both `classify.py` and `generate.py`.
- `claude-sonnet-4-6` is a capable mid-tier model — fast and inexpensive enough for 330 API calls (30 generation + 300 eval) while being strong enough to follow nuanced label definitions.
- Switching to OpenAI would require swapping the client and rewriting the tool-use schema to function-calling format, but the overall architecture would be unchanged.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| OpenAI `gpt-4o` | Anthropic key was available; no meaningful quality difference at this task |
| Local model | Structured output enforcement is unreliable at open-weight model tier; adds local GPU dependency |

---

> **Amended 2026-06-29:** the original Consequences said out-of-enum labels are rejected "at the API layer." They are not — tool use enforces the response *shape*, while enum membership is validated in client code (`classify.py`'s `_validate`, which re-samples once). Corrected to match the code and the v1.1.0 doc sweep (see `CHANGELOG.md`).
