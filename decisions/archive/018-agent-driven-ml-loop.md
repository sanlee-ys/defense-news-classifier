# ADR-018: Rung 2 — the agent-driven ML loop, on the bake-off substrate

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** San Lee

**Related:** [ADR-005](005-agentic-prompt-optimization-loop.md) (rung 1's loop architecture,
reused wholesale) · [ADR-017](017-classical-baseline-bakeoff.md) (the substrate) ·
[autonomy-ladder](../../docs/specs/autonomy-ladder.md) (this completes L3's build)

---

## Context

The autonomy ladder's L3 is delivered as two rungs. Rung 1 (ADR-005) put an agent in charge
of the classifier's *prompt*. Rung 2 puts the same loop architecture in charge of a
*classical ML model* — the TF-IDF + logistic-regression baseline ADR-017 built and measured
one PR earlier. The fusion is the point: the inner loop is mechanical (sklearn fits to
convergence, no judgment), the outer loop is agentic (read the errors, decide the next
experiment), so "do ML" and "do loop engineering" stop being separate goals.

The defensible core, unchanged from the 2026-06-27 design: the agent must earn its place
via judgment — qualitative error analysis driving the next experiment — or it is just a
worse `GridSearchCV`.

## Decision

**Build rung 2 as `src/ml_loop.py`, reusing rung 1's honesty architecture verbatim rather
than re-deriving it.** Concretely:

- **The 3-way split, same roles.** A (~210 of the 300 judge-graded rows) is all the agent
  sees; B (~90) drives the done-signal and best-iteration selection; C (the 54-row human
  gold set) is scored every iteration but read by no decision. `check_done_signal` and
  `select_best_iteration` are **imported from `optimize.py` unchanged** — the Goodhart
  guard is shared code, not a shared intention.
- **The experiment space is bounded and validated.** The agent controls the vectorizer
  (analyzer, n-grams, min_df, max_features, sublinear_tf, stop words), regularization
  (C, class_weight), and — the error-driven part — up to 20 named **keyword feature
  groups** (binary substring indicators) it derives from reading misclassified examples.
  `validate_experiment` is the rung-2 counterpart of rung 1's region-rubric freeze:
  deterministic, free, run before any fitting; an invalid proposal costs a retry, and a
  proposer that can't produce a valid experiment raises `ProposalError` and stops the run.
- **Feedback comes from out-of-fold predictions on A** (5-fold CV inside A), not from the
  fitted model's predictions on its own training rows — a model scoring its own training
  set memorizes it and would hand the agent an empty failure list. This is the one place
  rung 2's design had to differ from rung 1 (where scoring a prompt never "trains" on the
  scored rows). A test pins that OOF failures exist, so a regression to fit-on-self
  feedback fails CI.
- **Only the proposer spends tokens.** Scoring is local sklearn; the token budget gates
  proposer calls (exact usage from `response.usage`, failed retries billed). The proposer
  model is the SYS-002 default workhorse.
- **Primary metric: mean of the two axes' macro-F1 on B**, logged under the `macro_f1`
  key so rung 1's selection code reads rung-2 records unchanged. Two axes only — the
  training data has no region labels until v3.1.0 (ADR-017's disclosed limit, inherited).
- **Same run-log format**: append-only JSONL (metadata / iteration / summary) under
  `evals/ml_loop/` (gitignored), so the recorded-replay viewer's format carries over.
- **`DryRunBackend`** provides a free, deterministic, end-to-end offline path (tests, CI,
  demos); the live backend is never constructed by tests.

**Not decided here:** whether rung 2's first live run improves on the baseline. The loop is
built and CI-covered; the live run is San's to drive, and its verdict — including "the
agent could not beat a fixed configuration," which would be a publishable negative result
in this repo's voice — is recorded when it exists. No version bump until then; the
capability sits in `[Unreleased]` per the project's precedent (rung 1 waited for v2.1.0).

## Amendment — live-run verdict (2026-07-25)

San ran the first live loop the day the code merged (Sonnet proposer, 8-iteration cap,
100k token budget; log `run_20260725T153551Z.jsonl`, gitignored per policy — the numbers
below are the record). Six iterations, stopped on **plateau**. The verdict:

**The agent improved the metric it could see and degraded the one that matters — and the
harness caught it.**

| | B (validation, judge-labeled) | C (held-out human gold) |
|---|---|---|
| baseline (iter 0) | 0.639 | 0.631 |
| best-by-B (iter 2) | **0.699** (+6.0) | **0.545** (−8.6) |

The mechanism is distribution shift, not classic peeking: the agent never sees B, but A
and B are both judge-labeled DVIDS wire text, so the keyword features it mined from A's
errors (platform names, service designators) genuinely generalize *within* that
distribution and B rewards them. C is the human-labeled gold set — different labeler,
different text mix (it includes the SEC-filing snippets) — and the same DVIDS-shaped
keywords mislead there. This is exactly the B-vs-C gap the ADR-005 split design predicted
("fit the judge's labeling style" vs "agreement with humans"), now observed live. Every
guard behaved: plateau fired after three non-improving B iterations, best-iteration
selection read B alone, and C exposed the trade precisely because nothing was allowed to
optimize it.

Two secondary observations for the writeup:

- **Prompt adherence:** iteration 1 dumped ten keyword groups at once despite the
  one-coherent-change-per-iteration instruction. It passed validation (the bounds
  deliberately don't encode experimental discipline), but it makes that iteration's B gain
  unattributable — the same species of proposer drift rung 1 documented.
- **The overfit tail is visible in the trace:** iterations 3–5 show A flat, B declining,
  the agent mining ever-narrower signals (`command_change_ops`) that were already noise.

Standing verdict: rung 2's live result is a **measured negative-transfer finding**, the
Goodhart centerpiece demonstrated end-to-end rather than merely designed for. It is
arguably the stronger portfolio artifact than a win: the loop's value was proven by the
held-out set vetoing the loop's own best iteration. The shipped classifier is, as ever,
unchanged. This verdict unblocks the portfolio surfaces listed under Downstream surfaces.

## Consequences

- **L3 of the autonomy ladder is now fully built** (both rungs); the remaining L3 work is
  a recorded live run + writeup, then L4 earns its own spec/session.
- The bake-off harness gains a consumer, which is why its train/predict pieces were built
  as importable functions rather than a script.
- The dry run's canned moves do not beat the baseline (B mean macro-F1 0.639 stays best at
  iteration 0, plateau fires after 3 tries) — deliberately acceptable: the canned path
  exercises the machinery, and beating the baseline is the live agent's job, not the
  fixture's.
- Risk carried, stated: with n≈90 on B, per-iteration deltas of a point or two are inside
  noise; the plateau rule reads "no strict improvement," so noise-level wiggle does not
  reset patience. The live writeup must read B-vs-C the way rung 1's spec prescribes —
  directionally, not on small moves.

## Downstream surfaces

Touched by this change (all in this PR):

- `src/ml_loop.py`, `tests/test_ml_loop.py` — the loop and its guards (new).
- `docs/specs/autonomy-ladder.md` — L3 row and §6 flip from "rung 2 spec'd, unbuilt" to
  built; §6's L4 line updated to "both rungs built".
- `.gitignore` — `evals/ml_loop/run_*.jsonl` (same policy as rung 1's logs).
- `CHANGELOG.md` `[Unreleased]`, `decisions/README.md` index row.

To sweep later, deliberately NOT in this PR:

- **First live run** — San drives (`uv run --env-file .env python src/ml_loop.py`); its
  log feeds the replay viewer and the portfolio writeup.
- Portfolio surfaces (project page L3 section, the ladder visual's rung-2 marker) — update
  when the live run exists, so the page shows a result, not a promise; SYS-019 markers if
  numbers are quoted.
- `docs/specs/prompt-optimization-loop.md` §rung-2 forward references, if any prove stale
  on the next docs pass.
