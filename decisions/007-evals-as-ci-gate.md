# ADR-007: Wire the v2 gold-set evals into CI as a two-gate quality gate, split by API cost and fork-PR secret safety

**Status:** Accepted
**Date:** 2026-07-10
**Deciders:** San Lee

---

## Context

The v2 gold-set evals (`src/gold_eval.py`, `src/gold_eval_rag.py`) already measure the
classifier and its retrieval-grounded variant against a human-labeled answer key
(`data/gold/gold.csv`, n=54) and report real numbers — category accuracy 88.9%, RAG lift
+1.9%, committed in `evals/gold_eval.txt` / `evals/gold_rag_eval.txt`. Nothing currently
stops those numbers from silently regressing: a prompt edit, a model swap, or a retrieval
change can merge without ever being checked against the measured bar.
`.github/workflows/tests.yml` gates lint/format/types/unit-test coverage on every push, but
it has no idea these capability numbers exist. This closes a gap under the cross-repo
SYS-007 "evals-as-CI" initiative (see the `architecture` repo): a measured number that
isn't enforced in CI is a report nobody re-checks, not a quality bar. Cross-repo roadmap
bookkeeping is out of scope for this repo-local, one-concern PR.

The two eval scripts are today print-only: they build a human-readable report string and
write it to a `.txt` file, exiting 0 regardless of the numbers. Wiring them into CI needs a
machine-readable pass/fail signal that does not exist yet. They also already have two
distinct phases baked in: a **prediction** phase that calls the Anthropic API and is
skipped entirely when `evals/gold_predictions.csv` / `evals/gold_rag_predictions.csv`
already exist (their existing resume/checkpoint behavior), and a pure **scoring** phase
that grades whatever predictions are on disk. Cost has to be a first-class constraint on
any CI design here: this is a public repo, `ANTHROPIC_API_KEY` is a real secret, and every
model call costs money. `gh secret list -R sanlee-ys/defense-news-classifier` currently
returns nothing — the secret does not exist on the repo yet.

## Decision

Split the gate in two, mapped directly onto the scripts' existing prediction/scoring split.

1. **Offline scoring-regression gate** (`offline-gate` job, `.github/workflows/evals.yml`)
   — runs on every `push` and `pull_request`, no secret, no network call. It grades the
   prediction CSVs already committed in `evals/` against floors in the new
   `evals/thresholds.toml`, using a new pure module, `src/eval_gate.py`, that never calls
   the Anthropic API. Its honest job is to prove the shipped numbers still clear the
   declared bar and that the scoring code itself still computes them correctly — it is
   **not** a live capability check, and it is free and deterministic.
2. **Live capability gate** (`live-capability-eval` job, same workflow) — runs **only** on
   `workflow_dispatch` and a weekly `schedule` cron, never on `pull_request`. It deletes the
   cached prediction CSVs, re-runs `gold_eval.py` and `gold_eval_rag.py` against the real
   models to regenerate fresh predictions, then runs the exact same `eval_gate.py` against
   the exact same floors. This is the "did the model/prompt/retrieval actually get worse"
   check. It is read-only: it measures and gates, it never commits refreshed numbers back
   to the repo — updating the checked-in snapshot stays a deliberate, reviewed human PR.

`eval_gate.py` is the single machine-readable entry point both jobs share: it uses a new
`metrics(merged) -> dict` extracted from each eval script (the same values `build_report()`
already formats for humans, now also exposed as data), reads floors from
`evals/thresholds.toml` via the stdlib `tomllib` (zero new dependencies, Python 3.11+),
prints a metric/value/floor/PASS|FAIL table, and calls `sys.exit(1)` on any breach.

**Trigger choice is the cost and secret-safety answer together.** Restricting the paid job
to `workflow_dispatch` + schedule — never `pull_request` — means a fork PR has no event
that can invoke it at all, which is the airtight answer to the public-repo
fork-secret-exposure problem. The alternative, `pull_request_target`, is explicitly
rejected (see Alternatives): it runs untrusted fork code in the base repo's context WITH
secrets, the one combination GitHub itself warns is unsafe. `live-capability-eval` declares
`permissions: contents: read` and a guard step that hard-fails with a clear message if
`secrets.ANTHROPIC_API_KEY` is absent, so a misconfigured run fails loudly instead of
silently passing or silently doing nothing.

**Thresholds live in one shared `evals/thresholds.toml`** used by both gates, with floors
set roughly 5–7 points below the currently committed numbers (baseline `category_accuracy`
0.83 vs 0.889 committed, `category_macro_f1` 0.85 vs 0.906; RAG `category_accuracy` 0.85 vs
0.907 grounded, plus `category_delta_min` / `domain_delta_min` = -0.03 so grounding is
checked against regressing the ungrounded baseline, not just against an absolute floor).
The margin is sized for the live gate's run-to-run noise (model calls are non-deterministic)
so the weekly job doesn't flap red on noise; the committed snapshot clears every floor
comfortably today. This mirrors `tests.yml`'s existing `--cov-fail-under=66` philosophy: a
few points below current, ratcheted upward later. At n=54 the eval is a small,
already-documented sample (see `docs/how-it-works.md`'s threats-to-validity), so floors are
intentionally coarse rather than tight; `v2.1.0`'s planned eval-scaling (validated Opus
judge, 300+ snippets) is the path to tightening them.

## Consequences

- The shipped v2 capability numbers are now checked on every PR, not just reported: a
  regression that clears the loose floor still needs a human to notice, but a *large*
  regression (bad prompt edit, wrong model string, broken retrieval) fails the
  `offline-gate` check outright, for free. That check only *blocks the merge* once
  `offline-gate` is marked a required status check in branch protection — a one-time repo
  setting `evals.yml` cannot declare on its own behalf; see README.md's "Enforce the gate"
  go-live step.
- **`eval_gate.py` is exercised on every push/PR** even though it never calls the API, so
  the gate's own logic (threshold parsing, breach detection, exit code) stays continuously
  tested in the same place it will actually run when the live job fires.
- **Loose shared floors make the per-PR offline gate a weak drift detector.** It only trips
  on a large regression or a scoring-code break, not a one- or two-point real drift.
  Mitigated today by `eval_gate.py`'s own breach unit tests
  (`tests/test_eval_gate.py`) and by the gate code being continuously exercised; a tighter,
  separate offline floor set is a later, deliberate ratchet (see Alternatives).
- **The live gate is non-deterministic and costs real money** (~108 calls for
  `gold_eval.py`, ~54 for `gold_eval_rag.py`, per run). A weekly cadence bounds spend to a
  known, predictable amount; changing that cadence is a conscious edit to the cron line and
  this ADR, not an accident.
- **`live-capability-eval` will hard-fail via its guard step on first run** until San adds
  `ANTHROPIC_API_KEY` to the repo (see README.md's go-live steps). This is by design: fail
  loudly, not silently skip.
- Refactoring `build_report()` in both scripts to read from the new `metrics()` functions
  changes no printed output and no committed `.txt` snapshot; `tests/test_gold_eval.py` and
  `tests/test_gold_eval_rag.py` are unchanged and still pass, proving it.
- `Jenkinsfile` gets a parity-only `Eval gate (offline)` stage mirroring `offline-gate`,
  flagged in a comment as carrying no status check and no secret — consistent with the rest
  of the file, which already mirrors Actions without being a live gate.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| `pull_request_target` for the live gate | Runs untrusted fork PR code in the base repo's trust context WITH secrets — the exact combination GitHub's own docs call out as unsafe on a public repo. Rejected outright, not engineered around. |
| Run the live gate on every PR (no gating) | Costs real money per PR (~162 calls) and is non-deterministic, so PRs could flap red on model noise rather than an actual regression; also hands `ANTHROPIC_API_KEY` to every `pull_request`-triggered run, including same-repo PRs that don't need it. |
| Path-filtered live gate on PRs (only prompt/model/retrieval paths) | Narrows the cost problem but not the fork-secret-exposure problem — a fork PR can still touch `src/classify.py` and trigger a paid run against an untrusted diff. Rejected for the same reason as running on every PR, just less often. |
| Label-gated live run on San's own PRs (e.g. a `run-capability-eval` label) | Tighter pre-merge feedback than dispatch/schedule, and same-repo PRs are not the fork-secret risk. A real option, not chosen as the default because it re-adds per-labeled-push cost and flakiness risk to the PR loop that the dispatch/schedule design avoids entirely. Left as a documented option if tighter feedback is wanted later. |
| One tight offline floor set instead of one shared loose file | Would make the per-PR gate a real drift detector instead of a large-regression backstop. Rejected as the default because the *live* gate's non-determinism sets the effective floor for any threshold both gates share; a genuinely tighter offline-only floor is a real future ratchet, not implemented here to keep this PR to one concern. |
| Add the gate as a step inside `tests.yml` instead of a new workflow | Keeps one fewer workflow file, but couples the classifier's lint/type/coverage gate (must always run, no secret) to the eval gate (conceptually separate, and the future home of the paid job) and touches a collision-hotspot file (`.github/workflows/*` is called out in `CLAUDE.md`) for no structural reason. A separate `evals.yml` keeps `tests.yml` untouched and gives the eval gate its own status check. |
| Have the live gate commit refreshed prediction CSVs back to `main` | Would keep the snapshot current automatically, but means CI can silently rewrite the checked-in "ground truth" numbers the README leads with, with no human review of what changed or why. Refreshing the snapshot stays a deliberate, reviewed PR. |
