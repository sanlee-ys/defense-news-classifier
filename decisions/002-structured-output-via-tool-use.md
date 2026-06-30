# ADR-002: Enforce structured output via tool use, not prompt engineering

**Status:** Accepted  
**Date:** 2026-06-19  
**Deciders:** San Lee

---

## Context

The classifier must return exactly `{category, operational_domain}` with values drawn from fixed enum sets. There were two ways to achieve this:

1. **Prompt engineering** — instruct the model to "return JSON with these fields and only these values." Parse the response text in application code, validate the values, and handle failures.
2. **Tool use with JSON schema** — define a tool with an `input_schema` that enumerates valid values. Set `tool_choice: {"type": "tool", "name": "..."}` to force the model to call it. The schema guarantees the response *shape* and strongly biases valid labels; a thin enum check stays in client code.

## Decision

Use `tool_choice` with a named tool and a strict JSON schema (enums for both fields, both required). Applied to both `classify.py` and `generate.py`.

```python
tool_choice={"type": "tool", "name": "classify_article"}
```

## Consequences

- **Tool use guarantees the response *shape*.** The model returns a structured `tool_use` block with the schema's fields, so there is no free-text JSON to parse. The enums bias it strongly toward valid labels, but enum membership is *not* enforced server-side — an invalid label (e.g., `"aerial"` instead of `"air"`) is caught in client code by `classify.py`'s `_validate`, which re-samples once before raising `InvalidLabelError`.
- **Application code stays small.** `classify()` makes the call, pulls the `tool_use` block, and validates the labels against the enums — no brittle parsing of free-form JSON, just a thin guard over a structurally-guaranteed response.
- **The schema is the contract.** Adding or renaming a label requires updating both the enum and the system prompt — one place, not scattered across prompt text and validation code.
- **Minor tradeoff:** tool-use responses are slightly more expensive (extra tokens for the schema) and the API call signature is more verbose than a plain chat call.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Prompt + JSON parse | Validation burden falls on application code; model can still drift to synonyms or malformed output |
| Pydantic / instructor library | Adds a dependency and wraps the same mechanism; unnecessary for a two-field schema |
| OpenAI structured outputs (`response_format`) | Would require switching provider; equivalent mechanism |

---

> **Amended 2026-06-29:** corrected the "validation is at the API layer" and "no enum checking" claims — tool use enforces the response *shape*, while enum membership is validated in client code (`classify.py`). Matches the code and the v1.1.0 doc sweep (see `CHANGELOG.md`).
