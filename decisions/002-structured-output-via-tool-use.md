# ADR-002: Enforce structured output via tool use, not prompt engineering

**Status:** Accepted  
**Date:** 2026-06-19  
**Deciders:** sanle

---

## Context

The classifier must return exactly `{category, operational_domain}` with values drawn from fixed enum sets. There were two ways to achieve this:

1. **Prompt engineering** — instruct the model to "return JSON with these fields and only these values." Parse the response text in application code, validate the values, and handle failures.
2. **Tool use with JSON schema** — define a tool with an `input_schema` that enumerates valid values. Set `tool_choice: {"type": "tool", "name": "..."}` to force the model to call it. The API validates the response against the schema before returning.

## Decision

Use `tool_choice` with a named tool and a strict JSON schema (enums for both fields, both required). Applied to both `classify.py` and `generate.py`.

```python
tool_choice={"type": "tool", "name": "classify_article"}
```

## Consequences

- **Validation is at the API layer.** If the model produces an invalid label (e.g., `"aerial"` instead of `"air"`), the API rejects it before the response reaches application code. No defensive parsing or fallback logic needed in the client.
- **Application code is simpler.** `classify()` is seven lines: make the call, find the `tool_use` block, return `block.input`. No JSON parsing, no enum checking.
- **The schema is the contract.** Adding or renaming a label requires updating both the enum and the system prompt — one place, not scattered across prompt text and validation code.
- **Minor tradeoff:** tool-use responses are slightly more expensive (extra tokens for the schema) and the API call signature is more verbose than a plain chat call.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Prompt + JSON parse | Validation burden falls on application code; model can still drift to synonyms or malformed output |
| Pydantic / instructor library | Adds a dependency and wraps the same mechanism; unnecessary for a two-field schema |
| OpenAI structured outputs (`response_format`) | Would require switching provider; equivalent mechanism |
