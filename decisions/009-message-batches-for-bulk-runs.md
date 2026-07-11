# ADR-009: Add a Message Batches API path for non-latency-sensitive bulk classification

**Status:** Accepted
**Date:** 2026-07-11
**Deciders:** San Lee

---

## Context

Three call sites classify a whole collection of articles by looping `classify()` once per row,
synchronously, with a small `time.sleep()` between calls to stay inside rate limits:

- `eval.py`'s `run_predictions()` — every row of `data/synthetic_articles.csv`.
- `gold_eval.py`'s `run_predictions()` — every gold row, on **two** models (the workhorse baseline
  and the Opus judge), so it makes 2N synchronous calls.
- `optimize.py`'s per-iteration scoring loop — out of scope here; see Alternatives Considered.

None of these are interactive: they're run manually or from CI, and nothing is waiting on a single
row's result in real time. Anthropic's Message Batches API is built for exactly this shape — submit
many `Messages` requests as one batch, poll until it finishes, then retrieve all results — at 50%
of the synchronous per-token price. Most batches finish within an hour (max 24h), and results stay
retrievable for 29 days.

## Decision

Add a Message Batches API path alongside the existing synchronous loop, opt-in via a `--batch` CLI
flag, in both corpus-wide runners:

- `eval.py`: `run_predictions_batch()`, wired to `main() --batch`.
- `gold_eval.py`: `run_predictions_batch()`, wired to `main() --batch` — submits **both** the
  workhorse and judge requests for every not-yet-done row as **one** batch (custom IDs
  `"{id}::workhorse"` / `"{id}::judge"`), rather than two separate batches, so the discount applies
  to the whole judge-validation pass in a single submission.

The synchronous path (`run_predictions()`) stays the default in both scripts and is unchanged —
this is additive, not a replacement. Shared plumbing lives in `classify.py`:

- `build_batch_request(custom_id, text, model=, system_prompt=, temperature=)` — builds one
  `Request` with the exact same system block (including its `cache_control` marker — see ADR
  history in `classify.py`), tool, and `tool_choice` as the synchronous `classify()` call, so the
  two paths only differ in how the request is dispatched, not what's being asked.
- `parse_batch_result(result)` — extracts and validates the classified labels from one batch result
  item the same way `classify()` does (reusing `_validate()`), plus a new `BatchItemError` for the
  batch-only outcomes (`errored`/`canceled`/`expired`) that a synchronous call can't produce.

**Per-item failure handling:** a batch item that isn't `"succeeded"`, or a `"succeeded"` item whose
labels fail validation, is skipped rather than aborting the whole run — its id is simply not written
to the predictions CSV, so it stays in the resume set (`done_ids`'s complement) and is picked up
automatically the next time either the sync or batch path runs. In `gold_eval.py`, if either the
workhorse or judge request for a given gold id fails, the **whole row** is dropped (not a
half-filled record with one side missing), for the same reason.

## Consequences

- **~50% cheaper for unattended bulk runs.** The natural place to reach for `--batch`: a full
  `eval.py` run over the synthetic corpus, or a `gold_eval.py --batch` run to (re)score the gold
  set — both cases where nobody is watching a progress bar in real time.
- **No progress output while in flight, and coarser resume granularity.** The synchronous path
  writes one row to the predictions CSV per completed call, so a crash mid-run loses at most one
  row. The batch path has no such checkpoint: if the process is interrupted after submitting a
  batch but before it ends, there is no batch-id checkpoint to resume against, so a rerun
  resubmits a fresh batch for whatever's still `todo` — re-paying for any batch that was in flight.
  Documented in `run_predictions_batch()`'s docstring in both files. Acceptable for a background/cron
  use case; use the synchronous path when resume-per-request granularity matters more than the
  discount.
- **Prompt caching carries over automatically.** `build_batch_request()` reuses `classify()`'s exact
  system-block construction, so if/when the system prompt grows past `claude-sonnet-4-6`'s
  ~2048-token minimum cacheable prefix (e.g. via the `optimize.py` loop lengthening it — see
  `classify.py`'s existing caching comment), batch requests over that prompt benefit the same way
  synchronous ones do. No separate caching logic needed for the batch path.
- **New shared test fixtures.** `tests/conftest.py` gained `FakeBatch` / `FakeBatches` /
  `FakeBatchResultItem` / `FakeBatchClient` (and the `batch_client` fixture) — fakes for
  `client.messages.batches.{create,retrieve,results}` that resolve instantly (no polling) and
  produce results keyed by whatever `custom_id`s the code under test actually submits, so
  `run_predictions_batch()` in both files is tested the same way the synchronous path already was:
  offline, with a fake client.
- **`optimize.py`'s scoring loop is unaffected.** Its ~354-call-per-iteration pattern is
  latency-sensitive within the loop (each iteration's revised prompt depends on the prior
  iteration's scored feedback), so batching doesn't fit there — see Alternatives Considered.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Replace the synchronous path entirely | Loses per-row resume granularity and real-time progress output that some runs (e.g. interactive dataset-building sessions, or a `gold_eval.py` run somebody is watching) still want; the task is additive, not a migration |
| Add batch mode to `optimize.py`'s scoring loop | Each iteration's revised prompt is generated *from* that iteration's scored feedback — the loop is inherently sequential across iterations, and batch results aren't available until the whole batch ends (up to an hour), which would turn every iteration into an hour-long wait. The within-iteration scoring calls (~354 per iteration) are the one place batching could apply without changing the loop's sequencing, but that's a larger, separate change against a hot, already-tested file — left for a future iteration if `optimize.py`'s live-run cost becomes the bottleneck. |
| Separate batches for workhorse vs. judge in `gold_eval.py` | Works, but pays two poll cycles and two "batch ends" waits instead of one; combining them into a single batch (differentiated by `model` per request and a `::workhorse`/`::judge` suffix on `custom_id`) gets the same discount in one submission |
| Silently retry a failed batch item synchronously | Adds a second code path (and a second cost model) for the failure case; simply leaving the id out of the predictions CSV already gets a free retry via the existing resume logic on the next run, sync or batch, with no extra code |
