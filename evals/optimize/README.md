# Prompt-optimization run logs

This directory holds the JSONL run logs written by `src/optimize.py` (the
rung-1 prompt-optimization loop -- Level 3 of the [autonomy
ladder](../../docs/specs/autonomy-ladder.md), spec'd in
[docs/specs/prompt-optimization-loop.md](../../docs/specs/prompt-optimization-loop.md),
decision recorded in [ADR-005](../../decisions/005-agentic-prompt-optimization-loop.md)).

## Real runs have landed -- and they all overfit

Three live runs completed (2026-07-11 and 2026-07-12). **All three moved
category macro-F1 up on the tuned split A and *down* on held-out gold C:**

| Run | Stop | ΔA | ΔC | Gap (A−C) | Tokens |
|---|---|---|---|---|---|
| `run_20260711T143640Z` | `threshold` | +0.153 | **−0.066** | +0.219 | 2,641,918 |
| `run_20260711T185723Z` | `budget_tokens` | +0.082 | **−0.023** | +0.105 | 2,376,187 |
| `run_20260712T003435Z` | `threshold` | +0.179 | **−0.025** | +0.204 | 1,524,937 |

That consistency is the finding, not a single run's number: three
independent runs, two different stop signals, and the held-out set moved
backwards every time. The loop reliably improves the prompt *against the
set it can see* while giving back a little ground on real gold text --
which is exactly the failure mode the 3-way split exists to expose, caught
by the split rather than by hindsight. Treat any single C movement as
directional (n≈54, see the spec's "Known Limitations"); treat 3-for-3 in
the same direction as a pattern worth designing against.

`run_20260712T003435Z` is the one replayed on the portfolio's
[loop-replay viewer](https://sanlee.me/lab/loop-replay.html) -- picked
because it stopped on `threshold` and spent the least to get there.

Two logs here are **incomplete** (`run_20260711T025015Z`,
`run_20260711T132027Z`): they have iteration records but no trailing
`run_summary`, so a run was interrupted. They are readable but should not
be summarized; `read_run_log` will return their iterations and a `None`
summary.

To produce another, run the live command from the project
[README](../../README.md#rung-1-the-prompt-optimization-loop):

```bash
uv run --env-file .env python src/optimize.py --max-iterations 8
```

(The default token budget, 2M, is deliberately above a full default run's
~1.7M estimated spend: the iteration cap is meant to be the binding stop,
the token budget the runaway backstop -- see `DEFAULT_TOKEN_BUDGET`'s
comment in `src/optimize.py`.)

## Mocks in this directory, and one that is named like a result

**`sample_dryrun_run.jsonl` was produced by `uv run python src/optimize.py
--dry-run` -- zero API calls, a deterministic offline backend simulating
"prompt edits improve accuracy." It proves the loop mechanics end-to-end
(split, score, feedback, propose, re-score, done-signal, run log) and gives
a downstream replay/viewer a real artifact to build against. It is not a
measurement of the classifier and must never be read, cited, or plotted as
one.** The `agent_rationale` field on every mock iteration says so
explicitly (prefixed `[dry-run]`).

**`run_20260711T014612Z.jsonl` is also a dry run**, despite the
`run_<timestamp>` name -- a second `--dry-run` invocation that wrote to the
normal run path. Its `total_tokens_spent` is `0` and its rationales carry
the `[dry-run]` prefix, but the filename alone does not say so. It is kept
rather than renamed so this note has something to point at: **the filename
is not the provenance check -- `total_tokens_spent: 0` and a `[dry-run]`
rationale prefix are.** A mock that scores +0.396 on A can look like the
best run in the directory to anyone sorting by headline delta.

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
  "token_budget": 2000000,
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
  "done_signal": null,
  "unclassified": {"A": 0, "B": 0, "C": 0},
  "region_guardrail": {"macro_f1": 0.87, "accuracy": 0.8704,
                       "per_class_f1": {"europe": 0.9, "global": 0.81}}
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
- **`unclassified` counts ROWS, not axes.** A row lands here if `classify()`
  could not return a valid label on *at least one* of the three axes. The
  `__unclassified__` sentinel itself is applied **per axis** (`_salvage_labels()`
  in `src/optimize.py`): a row whose `region` was out of enum but whose
  `category` and `operational_domain` were fine keeps both good labels and is
  scored a miss on region only. Blanket-sentinelling all three would inject a
  phantom category miss into the very metric the done-signal reads.
- **`region_guardrail` is the region axis on split C -- a guardrail, never a
  target** (added 2026-07-19; `null` on runs and log records that predate it).
  The loop optimizes `category`, but the proposer rewrites the *whole*
  classifier prompt, which since `v3.0.0` carries a ~130-line region rubric
  ([ADR-014](../../decisions/014-region-field-design.md)) it was never asked to
  touch. This is the number that makes silent damage to that rubric visible:
  watch it flat across a run, and treat any sustained drop as a regression in
  the revised prompt, whatever category did.
  - **C only.** `data/synthetic_articles.csv` has no `region` column, so
    region is not scoreable on splits A or B. Gold is the only region-labeled
    data the loop has.
  - **Never wired into any decision.** Not in `scores`, not in the B-F1
    history, not read by `check_done_signal()` or `select_best_iteration()`.
    Pointing the optimizer at it would make C an optimization target and
    destroy the one honest held-out number the 3-way split exists to protect.
  - **`null` means "not measured"**, never "measured and zero".
  - **In a `--dry-run` log it is always `1.0` and means nothing** -- the mock
    backend copies the true region straight through, like it does for domain.
    It is not evidence the region rubric survived anything.

### 3. `run_summary` (always the last line, once the run completes)

```json
{
  "type": "run_summary",
  "best_iteration": 6,
  "final_iteration": 6,
  "done_signal": "threshold",
  "delta_macro_f1": {"A": 0.396, "B": 0.512, "C": 0.424},
  "overfitting_gap_a_vs_c": -0.028,
  "region_guardrail_macro_f1": {"baseline": 0.870, "best": 0.868},
  "region_guardrail_delta": -0.002,
  "total_tokens_spent": 0
}
```

Everything in this record is a **precomputed convenience**, not new
information -- it is a pure function of the `iteration` records above it
(`best_iteration` = `select_best_iteration(records)`; the deltas are
baseline-vs-**best** A/B/C scores -- measured on the winning iteration, not
the final one, because on a plateau or budget stop the final prompt is by
construction not the one being shipped, and the headline overfitting number
should describe the winner). A crash before this line is written costs
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
- **`region_guardrail_delta`** = the region macro-F1 movement from the
  baseline to the **best** iteration (same span as `delta_macro_f1`, so it
  describes the prompt that actually won, not a discarded final one). It is
  the one-glance answer to "did optimizing category cost us the region axis?"
  A clearly negative value means the winning prompt damaged a rubric the loop
  was never asked to touch -- read the winning iteration's `prompt_diff`
  before trusting its category gain. `null` when region was not measured. The
  same n≈54 noise caveat as C applies: a small wobble is noise, a collapse is
  not.

## Why JSONL instead of one pretty-printed JSON object

Resolved in ADR-005 ("Resolved during implementation"): append-per-iteration
is what gives N4 resume-safety. A single big JSON object would need to be
rewritten whole on every iteration, so a crash mid-write could corrupt the
*entire* log, not just cost the in-progress iteration. JSONL trades
pretty-printing for that safety property, which is the one that matters for
an unattended, potentially-long-running, real-money loop.
