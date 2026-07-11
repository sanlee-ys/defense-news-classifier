# ADR-005: Optimize the classifier prompt with an autonomous, error-driven agent, guarded by a 3-way split

**Status:** Accepted  
**Date:** 2026-06-27  
**Deciders:** San Lee

---

## Context

The classifier prompt is tuned by hand: a human reads the misclassifications, edits the prompt, re-runs the eval, repeats. That manual loop has a clear feedback signal (the eval) and a clear goal (higher macro-F1), which makes it a candidate to automate.

Two motivations:

1. **Demonstrate "loop engineering"** — design an environment where an agent iterates to a goal autonomously, with a real feedback signal and an explicit stop condition. This is a portfolio aim in its own right (see [docs/specs/prompt-optimization-loop.md](../docs/specs/prompt-optimization-loop.md)).
2. **Possibly improve the prompt** — a secondary, reported result, not a goal we can guarantee.

The central risk is **Goodhart's law**: any optimizer pointed at a metric will learn to game it. An agent that edits the prompt to fix the exact examples it is scored on will overfit, and a naive setup would hide that by reporting only the score it optimized. The decision has to make overfitting *measurable*, not invisible.

## Decision

Build an **autonomous, error-driven agent loop** that reads eval failures, revises the classifier prompt, re-scores, and stops on an explicit signal. Two design choices define it:

**1. Error-driven, not mechanical.** Each iteration the agent reads raw misclassified examples plus confusion-matrix stats and edits the prompt to address *why* it failed. The qualitative judgment is the point; a blind parameter sweep is not loop engineering and a prompt has no hyperparameters to sweep.

**2. A 3-way split as the overfitting guard.**

| Set | Source | Role | Agent sees it? |
|-----|--------|------|----------------|
| **A** optimize | `data/synthetic_articles.csv` (~210) | agent reads these failures | yes |
| **B** validation | `data/synthetic_articles.csv` (~90) | drives the done-signal | no |
| **C** test | `data/gold/gold.csv` (real, n≈54) | honest generalization number, reported only | no |

The done-signal is threshold OR plateau on **B** (N=3) OR token/iteration budget. Optimizing and stopping on the same set would bias plateau detection, so **B** is held back from the agent specifically to keep the stop honest. **C** is never used for any decision; the **A-vs-C gap is reported as the overfitting measurement.**

Primary metric: `category` macro-F1 (`macro_average` from `src/eval.py`). Optimizer model: `claude-sonnet-4-6` (repo default). Improvement is reported, never a release gate.

## Consequences

- **Enables the loop-engineering demo** and reuses the existing eval (`compute_metrics`, `macro_average`, `confusion_matrix`) as the feedback signal — no new metric code.
- **Overfitting becomes a measured, reported quantity** rather than a hidden failure. The honest story is the deliverable.
- **Requires parameterizing `classify()`** to accept a custom prompt without changing its public default or the pinned wire contract. This is the build linchpin.
- **Shrinks the optimization set.** Holding back B leaves ~210 of 300 synthetic rows to optimize on. Accepted: honest stop-detection is worth more than 90 extra rows.
- **C is noisy at n≈54.** The done-signal rides B for that reason; scaling C with the validated judge (v2.1.0) would later strengthen the held-out number.
- **Establishes the run-log schema and replay pattern** that the future agent-driven ML loop (rung 2) reuses.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Keep hand-tuning the prompt (status quo) | Not autonomous; demonstrates no loop-engineering skill and does not scale |
| Mechanical sweep / `GridSearchCV`-style search | A prompt has no hyperparameter grid; no qualitative judgment, so it is not loop engineering — it would be a worse version of a sweep |
| Single 2-way train/test split | Optimizing and detecting plateau on the same set biases stop-detection; the A-vs-B memorization signal disappears |
| Optimize directly on the real gold set (C) | Overfits n≈54 and destroys the one honest held-out number we have |
| A prompt-optimization framework (DSPy, etc.) | Heavyweight dependency against the repo's minimal-deps rule (ADR-004); a hand-built loop is more legible as the artifact |
| Gate "done" on measurable improvement | Couples release to an outcome we cannot control (label-ambiguity ceiling) and pressures gaming the eval — the exact failure this design exists to expose |

## Resolved during implementation

The spec's [open questions](../docs/specs/prompt-optimization-loop.md#13-open-questions)
(section 13) are resolved here, conservatively, rather than by editing the spec itself — the
spec stays the historical contract; this ADR is where implementation-time decisions get recorded.

- **Run-log persistence** (§13 "confirm location + naming"): one append-only JSONL file per run
  at `evals/optimize/run_<UTC-timestamp>.jsonl` — a leading `run_metadata` line, one line per
  iteration, a trailing `run_summary` line. Append-only (not one rewritten JSON object) is what
  gives N4 its crash-safety: a crash costs at most the one in-progress iteration's *record*,
  never the whole log. Schema documented in
  [`evals/optimize/README.md`](../evals/optimize/README.md). A single pretty-printed JSON object
  would read nicer but loses that property — rejected for the same reason a single 2-way split
  was rejected above: the safety property matters more than the convenience for an unattended,
  real-money loop. To be precise about what N4 does *not* buy here: the data survives, but the
  *process* does not resume — unlike `eval.py`'s per-row checkpoint, re-running after a crash
  starts a fresh run from iteration 0 and (live) re-spends the tokens already paid. Continuing a
  partial run from its log (`--resume <run-log>`) is deliberate future work, not silently claimed.
- **Winner selection** (not explicitly asked in §13, but consequential and spec-silent): the
  reported "best" prompt is `argmax` of B macro-F1 across all iterations (recorded as
  `best_iteration` in the run log's trailer), never C (would consume the held-out set for a
  decision) and never "whichever iteration ran last" (a plateau-stop's last few iterations are,
  by definition, not the best — that is why the loop stopped). Ties keep the earliest iteration.
- **`classify()` prompt-parameterization** (§13 F1 "confirm the cleanest refactor"): already
  shipped ahead of this build — `classify()` gained an optional `system_prompt` parameter in
  #43 (`feat: let classify() accept a custom system prompt`), with the public default and the
  pinned wire contract (`tests/test_contract.py`) both untouched. No further change needed here.
- **A/B split ratio and seeding** (§13 "confirm ratio, confirm seeded"): 0.7 (~210/90, matching
  the spec's proposed split), seeded and recorded — `--seed` defaults to a fixed value for
  reproducibility, and every run's `split_hashes` (a stable hash of each set's sorted id list)
  are logged so a reader can confirm two runs used the same split, or that A/B/C were disjoint.
- **Primary metric** (§13 "confirm category macro-F1 vs. a combined score"): confirmed as spec'd
  — `category` macro-F1 alone drives the done-signal; `operational_domain` is tracked and
  reported (both split's `scores` block carries `domain_macro_f1`/`domain_accuracy`) but never
  gates anything, since the loop's proposer prompt only asks it to fix category-level confusion.
- **Confusion-signal computation** (an implementation-level deviation from N1's letter, not its
  spirit): `build_feedback`'s confusion stats are computed with a direct groupby over mismatched
  rows rather than `src/eval.py`'s `confusion_matrix()`. That function reindexes both axes to the
  *true*-label set, so a predicted label that never occurs as a ground-truth label in a given
  split — a real risk once a small split's errors concentrate onto one systematically
  overpredicted label, not just a theoretical one — would be silently dropped from the feedback
  the agent sees. `compute_metrics`/`macro_average` (the actual scoring math N1 is protecting)
  are still reused verbatim everywhere else; only this one aggregation, which was never metric
  math to begin with, is hand-rolled.
- **Frontend replay** (§13 "confirm step-through-on-click for v1"): deferred out of this repo
  entirely, per the spec's own cascade (§12) and the autonomy-ladder's one-concern-per-session
  rule — this build ships the backend loop, the run-log schema, a committed dry-run sample log,
  and this ADR; the recorded-replay player on the portfolio project page is a downstream,
  portfolio-repo session once this lands.

**Open for San, not resolved here:** the default `--target-f1` (0.90, a placeholder — see
`src/optimize.py`'s `DEFAULT_TARGET_F1` comment) is not derived from any measurement and should
be revisited once a live baseline B-score is in hand; and whether this ADR flipping to Accepted
pre-merge (rather than on merge to `main`) matches San's usual convention is itself a small
process question worth a one-line confirmation.
