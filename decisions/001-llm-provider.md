# ADR-001: Use the Anthropic API as the LLM provider

**Status:** Accepted  
**Date:** 2026-06-19  
**Deciders:** San Lee

---

## Context

The classifier and generator both require an LLM. The main alternatives were:

- **Anthropic API** (`claude-sonnet-4-6`, the workhorse at the time of this decision) — strong instruction-following, native tool-use support for structured output, Python SDK
- **OpenAI API** (`gpt-4o`) — comparable capability, also has function-calling for structured output
- **Local model** (Ollama, llama.cpp) — no API cost, but weaker instruction-following and no reliable structured-output enforcement at this tier

The project needed reliable structured JSON output (valid enum values, no hallucinated labels) without application-level validation code as the primary safety net.

## Decision

Use the Anthropic Python SDK. The API key is read from the `ANTHROPIC_API_KEY` environment
variable.

**The provider is what this ADR decides. The model is a knob under it**, pinned in
`src/classify.py` as `MODEL` and standardized by
[SYS-002](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-002-model-tier-standard.md)
(exact IDs, no date suffixes). It was `claude-sonnet-4-6` at the 2026-06-19 decision date and
is `claude-sonnet-5` now. See Amendment 2026-08-20.

## Consequences

- **Tool use (`tool_choice: "tool"`)** forces the model to call a named tool with a defined JSON schema, so the response arrives as structured fields instead of free text to parse. *(Amended 2026-08-20: this bullet went on to describe enum membership as a client-side guard with a re-sample. [ADR-008](008-strict-structured-outputs.md) retired that. `CLASSIFY_TOOL` now carries `strict: true`, so the API's constrained decoding guarantees enum validity server-side, `classify()` makes exactly one call, and `_validate` / `InvalidLabelError` are kept as a defensive backstop rather than the primary guard.)*
- A capable mid-tier model is fast and inexpensive enough for the 330 API calls this project's v1 needed (30 generation + 300 eval), while being strong enough to follow nuanced label definitions. That reasoning is what the tier choice rests on, and it survives a model migration.
- Switching to OpenAI would require swapping the client and rewriting the tool-use schema to function-calling format, but the overall architecture would be unchanged.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| OpenAI `gpt-4o` | Anthropic key was available; no meaningful quality difference at this task |
| Local model | Structured output enforcement is unreliable at open-weight model tier; adds local GPU dependency |

---

> **Amended 2026-06-29:** the original Consequences said out-of-enum labels are rejected "at
> the API layer." They were not, at the time: tool use enforced the response *shape*, while
> enum membership was validated in client code (`classify.py`'s `_validate`, which re-sampled
> once). Corrected to match the code and the v1.1.0 doc sweep (see `CHANGELOG.md`).
> **This amendment is itself now historical** — see below.

> **Amended 2026-08-20, two corrections.** Both claims this ADR made about the code had gone
> stale, and one of them was the 2026-06-29 amendment above.
>
> 1. **The model.** The title and body named `claude-sonnet-4-6` as the model in use.
>    `src/classify.py` has run `claude-sonnet-5` since the 2026-07-19 workhorse migration
>    ([ADR-010](archive/010-rag-path-model-pin.md) records the migration and the
>    RAG-path regression it surfaced). The title now names the provider, which is the durable
>    decision, so the next migration does not re-stale it. `src/classify_rag.py` still pins
>    `claude-sonnet-4-6` deliberately, on the dormant grounding path; that is a live pin, not
>    a stale one.
> 2. **The enum guard.** The 2026-06-29 amendment describes a client-side re-sample. That
>    mechanism was retired by [ADR-008](008-strict-structured-outputs.md) when Structured
>    Outputs reached GA: `strict: true` moved enum enforcement server-side, and `classify()`
>    now makes exactly one call. [ADR-002](002-structured-output-via-tool-use.md) carried a
>    matching amendment at the time and this ADR did not, so the two disagreed for roughly
>    seven weeks.
>
> The general lesson, recorded because it is the second time it has bitten: an ADR that
> describes *how the code currently works* goes stale silently, because nothing tests prose.
> An ADR that records *what was decided and why* does not. Prefer the second shape.
