# ADR-021: One API error taxonomy, and a truncated response is never a score

**Status:** Accepted
**Date:** 2026-08-01
**Deciders:** San Lee

**Related:** [ADR-008](008-strict-structured-outputs.md) (strict tool use — what this
backstops) · [ADR-013](archive/013-decline-tiered-routing.md) (cost is reported in relative
workhorse-call units, not dollars) · [ADR-007](007-evals-as-ci-gate.md) (the gated floors
this must not move) · pi agent harness
([`packages/ai/src/utils/retry.ts`](https://github.com/earendil-works/pi/blob/main/packages/ai/src/utils/retry.ts),
[`packages/evals/src/pi-harness.ts`](https://github.com/earendil-works/pi/blob/main/packages/evals/src/pi-harness.ts),
[`packages/ai/src/models.ts`](https://github.com/earendil-works/pi/blob/main/packages/ai/src/models.ts))

---

## Context

Two patterns from the pi agent harness were read against this repo's eval/runtime layer.
Both found something real.

**1. Retry was five copies of the same wrong `except` tuple.** `eval.classify_with_retry`,
`gold_eval.classify_retry`, `gold_eval_rag.classify_retry`, `optimize._classify_retry`, and
`route_eval._classify_runner_up_retry` each caught `(InternalServerError, RateLimitError)`.
That tuple is wrong in both directions:

- **Too narrow.** `anthropic.OverloadedError` (HTTP 529) is a *sibling* of
  `InternalServerError` under `APIStatusError`, not a subclass. An overloaded API — the most
  common transient failure on a long unattended run — aborted the run instead of backing off.
  `APIConnectionError` and `APITimeoutError` were missed the same way.
- **Too wide.** A spend cap or exhausted credit balance can arrive as a **429**. The loops
  slept and retried it, which cannot succeed; on the optimization loop (~354 scoring calls
  per iteration) that is a long, quiet stall in front of a message the operator needed
  immediately.

**2. Nothing asserted that a call finished.** `classify()` guarded refusals but not
truncation. With forced tool use and `max_tokens=256`, a `stop_reason == "max_tokens"`
response can still carry a `ToolUseBlock` whose `input` was cut mid-object. Depending on
where the cut lands it either fails `_validate` (loud, fine) or **validates**, because the
axes that survived are individually legal labels — and a partial answer then gets scored
right-or-wrong against the gold set. pi bakes its stop-reason assertion into the harness for
exactly this reason: an errored or truncated run must be an eval *failure*, never a quiet
zero.

## Decision

**`src/api_retry.py` is the single taxonomy.** A non-retryable pattern (quota, billing,
credit balance, spend limit, auth) is tested **first** and wins over the exception type, so a
billing failure dressed as a 429 fails fast; then deterministic SDK types fail fast, then
transient types and wordings retry. An unrecognized error is **fail-fast**, not
retry — retrying an unknown failure silently triples spend on a bug. Backoff is byte-for-byte
the old policy (`2s`, `4s`, …), and every call site keeps its signature, so this is an upgrade
of the existing mechanism, not a second one alongside it. `gold_eval` keeps
`InvalidLabelError` as a caller-supplied `retry_on` extra — a repo-specific judgement, not a
provider-transport classification.

**`classify.IncompleteResponseError` + `_raise_if_incomplete`** assert the response finished,
on both the synchronous and the Message Batches paths. It is a **deny-list**
(`max_tokens`, `pause_turn`, `model_context_window_exceeded`), not an allow-list, so an
unrecognized or absent `stop_reason` never breaks a caller the day the API adds a terminal
value.

**`paired_compare` gains the landing spot.** `UNCLASSIFIED` generalizes to
`HARNESS_ERROR_SENTINELS = {__unclassified__, __incomplete__, __refused__}`, all mapped to
`Outcome.ERRORED` — excluded from the lift and enumerated in the harness-health section,
never scored as a miss.

**`src/run_isolation.atomic_write_text`** applies the isolation half: a whole-file report is
written to a temp file *in the destination directory* and moved into place, with the temp
file removed in a `finally`; if the write failed **and** cleanup failed, both are raised as an
`ExceptionGroup` (Python's `AggregateError`), so a leaked scratch file can never mask the
error that caused it.

### Design forks, and the least-invasive branch taken

1. **`mkdtemp` per eval run — declined.** pi relocates each run into a fresh temp workspace.
   This repo's eval runs deliberately append into `evals/` as they go so a crash costs at most
   one API call and the next run resumes. Moving them under `mkdtemp` would delete resume
   *and* change a published metric's generation path. **Taken:** apply the discipline only
   where there is no resume to recover a partial write — whole-file report writes.
   **Alternative:** a run-scoped temp workspace with a copy-back step, which buys nothing here
   and adds a failure mode.
2. **Is a truncated response retryable? — declined.** `max_tokens` truncation is
   deterministic: the same request truncates in the same place, so a retry spends money to
   reproduce the failure. **Taken:** fail fast and name the stop reason.
   **Alternative:** retry with a raised `max_tokens`, which changes the call shape mid-eval
   and would make two rows of one run not comparable.
3. **A USD cost subsystem — declined.** ADR-013 established that this repo prices in relative
   workhorse-call units; a pricing table would be a subsystem with no consumer and would go
   stale. **Taken:** the minimum that makes pricing *possible* downstream —
   `telemetry.set_usage_attributes` now emits the 5m/1h cache-write split
   (`cache_creation.ephemeral_{5m,1h}_input_tokens`) instead of collapsing both into
   `cache_creation_input_tokens`. That split is load-bearing because the two are not
   interchangeable: pi's `calculateCost` prices a 1h cache write at **2x base input** and a 5m
   write at roughly **1.25x**, with cache reads discounted, so the same total token count
   costs ~1.6x more at the 1h TTL. **Alternative:** a `calculate_cost()` with a pinned price
   table, rejected as scope.

## Consequences

- Long unattended runs (`optimize.py`, `gold_eval.py`, `scale_eval.py`, `route_eval.py`)
  survive HTTP 529 and connection drops, and stop immediately on an account-state failure.
- A truncated response can no longer enter a metric. It raises; harnesses that record rows
  can write `__incomplete__` and have it counted as a harness error rather than a miss.
- **No published number moves.** No prompt, model, threshold, prediction CSV, or metric
  generation path is touched; the eight gated floors are byte-identical.
- One new import edge per eval module (`api_retry`), and one new offline-testable module pair
  (`api_retry`, `run_isolation`).

## Downstream surfaces

- **Code:** `src/api_retry.py` (new), `src/run_isolation.py` (new), `src/classify.py`
  (`IncompleteResponseError`, `_raise_if_incomplete`, wired into `classify()` and
  `parse_batch_result()`), `src/eval.py`, `src/gold_eval.py`, `src/gold_eval_rag.py`,
  `src/optimize.py`, `src/route_eval.py` (retry loops delegated),
  `src/paired_compare.py` (`HARNESS_ERROR_SENTINELS`, atomic `--out`), `src/telemetry.py`
  (cache-write split).
- **Tests:** `tests/test_api_retry.py` (new), `tests/test_run_isolation.py` (new),
  `tests/test_classify.py` (truncation cases), `tests/test_paired_compare.py` (sentinel
  bucket).
- **Decisions:** ADR-008 (this is its truncation backstop), ADR-013 (the relative-cost
  stance this deliberately does not overturn).
- **Not touched, deliberately:** `evals/thresholds.toml`, every prediction CSV,
  `scripts/gen_*.py`, `src/eval_gate.py`, `README.md`'s metrics block, and
  `.github/workflows/` — no gated number and no generation path changes.
