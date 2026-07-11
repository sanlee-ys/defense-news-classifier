# ADR-008: Enforce enum validity server-side with `strict: true`, retire the client-side re-sample

**Status:** Accepted
**Date:** 2026-07-11
**Deciders:** San Lee

---

## Context

[ADR-002](002-structured-output-via-tool-use.md) forced structured output via `tool_choice` with an
enum-constrained JSON schema, and documented that enum membership was **not** hard-enforced
server-side: the enum strongly biased the model toward valid labels, but a rare out-of-enum
response (e.g. `category="cyber"`, which is a valid domain but not a category) could still get
through. `classify.py` compensated with a client-side guard: `_validate()` checked the result
against `CATEGORIES`/`DOMAINS`, and `classify()` re-sampled up to three times (four attempts
total) before raising `InvalidLabelError`.

Anthropic's Structured Outputs feature is now GA on `claude-sonnet-4-6` and supports `strict: true`
on tool definitions. With `strict: true`, the API performs **constrained decoding**: the model is
mechanically restricted to tokens that keep the output valid against the schema, including enum
membership, before the response is ever returned. This is a stronger guarantee than "the model was
told the enum and usually complies" — it changes enum validity from a training-time bias to a
decoding-time constraint enforced by the server.

## Decision

Add `"strict": true` to both enum-constrained tool definitions:

- `classify.py`'s `CLASSIFY_TOOL` (the classifier's `{category, operational_domain}` schema)
- `generate.py`'s `GENERATE_TOOL` (the synthetic-dataset generator's schema, per ADR-002's original
  "applied to both `classify.py` and `generate.py`")

Both schemas also gained `"additionalProperties": false` at every object level (`CLASSIFY_TOOL`'s
top level; `GENERATE_TOOL`'s top level and its nested `items` schema) — the API requires this
alongside `strict: true`.

`classify()`'s re-sample-on-invalid-label loop is removed. It now makes exactly one call, still
validates the result through `_validate()`, and still raises `InvalidLabelError` on an out-of-enum
label — but as a defensive backstop rather than an expected-to-fire recovery path. There is nothing
left for a client-side retry to routinely fix: if `strict: true`'s guarantee ever fails (e.g. an
API regression), re-sampling the same request under the same guarantee is not a rational response
to that failure anyway.

Both changes were smoke-tested live against `claude-sonnet-4-6` (see the PR) before landing: a
single `classify()` call, and a direct `GENERATE_TOOL` call with the nested-array schema, both
returned strict-schema-conformant tool input with no errors.

## Consequences

- **Enum validity is now a server-side guarantee, not a client-side workaround.** `_validate()` /
  `InvalidLabelError` stay in `classify.py` as a defensive check, matching the project's general
  posture of not silently trusting the wire, but they are no longer load-bearing for the common
  case.
- **One fewer network round trip on the (rare) invalid-label path.** The removed loop could cost up
  to three extra API calls per article; those are gone. This has no effect on the common case,
  where the loop never fired anyway.
- **`optimize.py` is unaffected.** It catches `classify.InvalidLabelError` from `classify()` and
  records an `UNCLASSIFIED` sentinel rather than aborting the run (see its `_classify_retry` /
  `AnthropicBackend.score()` docstrings) — that contract (the exception type, and what it means)
  is unchanged; only the *frequency* it's expected to fire drops.
- **Tests updated accordingly.** `tests/test_classify.py`'s multi-attempt re-sample tests
  (`test_classify_resamples_once...`, `..._up_to_three_times...`, `..._raises_after_four_invalid`)
  are replaced with a single-attempt test proving no re-sample happens, plus direct tests of the
  `strict`/`additionalProperties` fields on `CLASSIFY_TOOL`.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Keep the re-sample loop alongside `strict: true` | Redundant defense-in-depth for a failure mode `strict: true` is specifically designed to eliminate; keeping it obscures that the guarantee changed and leaves dead code implying the workaround is still load-bearing |
| Drop `_validate()`/`InvalidLabelError` entirely | Removes the last line of defense against an API regression, and breaks `optimize.py`'s existing `except classify.InvalidLabelError` contract for no benefit |
| `output_config.format` (JSON Schema structured outputs) instead of strict tool use | Equivalent enforcement mechanism, but would mean dropping `tool_choice`/`tool_use` and reshaping every caller (`classify_rag.py`, `optimize.py`, tests) around a different response shape for no gain over the smaller `strict: true` tool-definition change |

---

**Downstream surfaces checked:** `classify_rag.py` reuses `classify()` verbatim and needed no
change. `gold_eval.py`, `eval.py`, and `optimize.py` all call `classify()`/`classify_retry()`
wrappers that only catch transient API errors, not `InvalidLabelError` — unaffected. `optimize.py`
is the one caller that catches `InvalidLabelError` itself; see Consequences above.
