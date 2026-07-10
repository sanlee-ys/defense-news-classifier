# Prompt-optimization run logs

This directory holds the JSONL run logs written by `src/optimize.py` (the
rung-1 prompt-optimization loop -- Level 3 of the [autonomy
ladder](../../docs/specs/autonomy-ladder.md), spec'd in
[docs/specs/prompt-optimization-loop.md](../../docs/specs/prompt-optimization-loop.md),
decision recorded in [ADR-005](../../decisions/005-agentic-prompt-optimization-loop.md)).

## `sample_dryrun_run.jsonl` is a mock, not a result

**This file was produced by `uv run python src/optimize.py --dry-run` --
zero API calls, a deterministic offline backend simulating "prompt edits
improve accuracy." It proves the loop mechanics end-to-end (split, score,
feedback, propose, re-score, done-signal, run log) and gives a downstream
replay/viewer a real artifact to build against. It is not a measurement of
the classifier and must never be read, cited, or plotted as one.** The
`agent_rationale` field on every mock iteration says so explicitly
(prefixed `[dry-run]`).

The real run lands when San runs the live command from the project
[README](../../README.md#rung-1-the-prompt-optimization-loop) himself:

```bash
uv run --env-file .env python src/optimize.py --max-iterations 8 --token-budget 200000
```

That produces a new `run_<UTC-timestamp>.jsonl` here alongside the sample.

## File naming

`run_<UTC-timestamp>.jsonl`, e.g. `run_20260710T232300Z.jsonl` -- one file
per optimization run, timestamp taken at the moment the run starts
(`new_run_log_path()` in `src/optimize.py`).

## Format: append-only JSONL

One JSON object per line, written incrementally as the run progresses
(`append_run_log()` -- never a rewrite of the whole file). This is what
makes a run resume-safe in the N4 sense used elsewhere in this repo: a
crash mid-run loses at most the one iteration in progress, never an
already-completed one. Unlike `evals/predictions.csv`'s per-*row* resume,
this is per-*iteration* -- coarser, and accepted as such, because each
iteration scores under a different prompt, so there is nothing to resume
*within* an interrupted iteration (see ADR-005 "Resolved during
implementation").

Read a log back with `optimize.read_run_log(path)`, which returns every
record in file order. Filter to just the per-iteration records with
`optimize.iteration_records(records)`. **A run reconstructs entirely from
this file** -- nothing about a completed run lives anywhere else.

## Record types (in the order they appear)

### 1. `run_metadata` (always the first line)

```json
{
  "type": "run_metadata",
  "model": "claude-sonnet-4-6",
  "token_budget": 200000,
  "iteration_cap": 8,
  "split_hashes": {"A": "...", "B": "...", "C": "..."},
  "start_prompt": "<the classifier's starting system prompt>",
  "seed": 42,
  "timestamp": "2026-07-10T23:23:00+00:00"
}
```

`split_hashes` is a stable hash of each set's sorted id list (see
`_hash_ids`), so a reader can confirm two runs used the same split, or that
A/B/C were disjoint, without re-shipping the id lists themselves.

### 2. `iteration` (one per iteration, 0 = the baseline)

```json
{
  "type": "iteration",
  "iteration": 0,
  "prompt": "<full prompt text scored this iteration>",
  "prompt_diff": null,
  "scores": {
    "A": {"macro_f1": 0.533, "accuracy": 0.5333, "domain_macro_f1": 1.0,
          "domain_accuracy": 1.0, "per_class_f1": {"...": 0.5}},
    "B": {"...": "same shape"},
    "C": {"...": "same shape"}
  },
  "failures_read": [],
  "confusion_stats": {},
  "agent_rationale": null,
  "edit_summary": null,
  "tokens_spent": 0,
  "done_signal": null
}
```

Matches spec section 8 field-for-field, with one field's semantics worth
being explicit about:

- **`tokens_spent` is cumulative** through this iteration, not a per-iteration
  delta -- it is what `check_done_signal`'s token-budget check compares
  directly against `token_budget`, and it lets a reader see total spend at a
  glance without summing.
- **`prompt_diff` / `agent_rationale` / `edit_summary` are `null` at
  iteration 0** (spec: "no edit" baseline) and a string on every iteration
  after that.
- **`failures_read` / `confusion_stats` are sourced from set A only**, and
  are what *produced* this iteration's prompt (i.e. they're the feedback the
  proposer read on the *previous* iteration's A-score, not anything about
  this iteration's own A-score). B and C are never present anywhere in
  these two fields -- see the Goodhart-guard test suite in
  `tests/test_optimize.py` for the regression guard on that claim.
- **`done_signal` is non-null only on the final record.** Its value is one
  of `"threshold"`, `"plateau"`, `"budget_iterations"`, `"budget_tokens"` --
  see `check_done_signal()`'s docstring for the fixed precedence order.

### 3. `run_summary` (always the last line, once the run completes)

```json
{
  "type": "run_summary",
  "best_iteration": 6,
  "final_iteration": 6,
  "done_signal": "threshold",
  "delta_macro_f1": {"A": 0.396, "B": 0.512, "C": 0.424},
  "overfitting_gap_a_vs_c": -0.028,
  "total_tokens_spent": 0
}
```

Everything in this record is a **precomputed convenience**, not new
information -- it is a pure function of the `iteration` records above it
(`best_iteration` = `select_best_iteration(records)`; the deltas are
first-vs-last A/B/C scores). A crash before this line is written costs
nothing but the convenience: the same numbers are recoverable by reading
the iteration records directly. This is why it is a trailer rather than
folded into the leading `run_metadata` record -- metadata is written before
iteration 0 even runs, before `best_iteration` can possibly be known.

- **`best_iteration` is selected on B, never C** (consuming the held-out set
  for a decision would defeat its purpose) and is **not** "whichever
  iteration ran last" (a plateau-stop's last few iterations are, by
  definition, not the best -- that's *why* the loop stopped).
- **`overfitting_gap_a_vs_c`** = the A-delta minus the C-delta across the
  whole run (spec section 9's headline overfitting number): a large
  positive gap means the prompt improved on the synthetic set it was tuned
  against far more than it improved on real gold text -- memorization, not
  generalization. Read alongside the per-iteration A-vs-B and B-vs-C gaps
  already visible in each iteration's `scores` block.
- **C is directional only** (n≈54, a noisy sample -- see the spec's
  "Known Limitations" section). The done-signal never rides C for exactly
  this reason; treat single-run C movements as a hint, not a verdict.

## Why JSONL instead of one pretty-printed JSON object

Resolved in ADR-005 ("Resolved during implementation"): append-per-iteration
is what gives N4 resume-safety. A single big JSON object would need to be
rewritten whole on every iteration, so a crash mid-write could corrupt the
*entire* log, not just cost the in-progress iteration. JSONL trades
pretty-printing for that safety property, which is the one that matters for
an unattended, potentially-long-running, real-money loop.
