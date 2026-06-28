# ADR-005: Optimize the classifier prompt with an autonomous, error-driven agent, guarded by a 3-way split

**Status:** Proposed  
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
