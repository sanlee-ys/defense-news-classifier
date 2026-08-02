# Feature Spec — v3.2.0: Scaled Region Eval (n=300, judge-graded)

**Version:** 1.0
**Status:** Accepted — **run 2026-08-02, shipped as `v3.2.0`**. The verdict and the numbers live in [ADR-022](../../decisions/022-scaled-region-eval-verdict.md); the report is `evals/scale_eval_v3.txt`. This document remains the design record.
**Author:** San Lee
**Last updated:** 2026-08-02
**Roadmap fit:** **MINOR** (`v3.2.0`). Additive measurement only — `src/api.py`, `src/classify.py` and `SYSTEM_PROMPT` are untouched, so the `{category, operational_domain, region}` contract holds.
**Related:** [ADR-014](../../decisions/014-region-field-design.md) (the region field, and the judge gate this eval stands on) · [ADR-007](../../decisions/007-evals-as-ci-gate.md) (thresholds come from measured runs) · [ADR-020](../../decisions/020-l4-multi-agent-pipeline.md) (the L4 critic fixed 6 of the 7 `global` misses at ~4× cost — the alternative this eval prices) · `src/scale_eval.py` (the v2.1.0 scale pass this mirrors)

---

## 1. Problem statement

The region axis ships with one number: **87.0% on n=54**, measured 2026-07-18. Its 95%
Wilson CI is **[75.6%, 93.6%] — 18 points wide**. Two things that matter cannot be decided
inside an interval that wide:

1. **Is a future region change a real regression?** A prompt edit that moves the number
   five points is indistinguishable from noise at n=54.
2. **Is the named error cluster systematic?** All **seven** region misses on the gold set
   were rows whose true label was `global`, which the model pulled to a specific region by
   inferring a theater from the US *actor* when the snippet stated no place. Seven rows is
   a story, not a measurement. HANDOFF job 2 (a prompt clause targeting that cluster) has
   no ruler to be measured against until this exists.

At n=300 the same 87.0% carries an **8-point** CI, [82.7%, 90.3%]. **Shrinking the ruler
is the deliverable.** The accuracy itself is whatever it turns out to be, and a lower
number at n=300 is a better-known number, not a worse classifier.

## 2. Why the judge is allowed to be the answer key

Hand-labeling does not scale, so the Opus judge grades the 300. ADR-014 made that
conditional rather than assumed: the judge had to validate against the human labels on
this specific axis first. It did — **100.0% region agreement** on the n=54 gold set
(`evals/gold_eval_v3.txt`), alongside 92.6% category and 98.1% domain.

**The judge configuration is therefore frozen.** Same `SYSTEM_PROMPT`, same
`gold_eval.JUDGE_MODEL`, same `classify()` call path as the run that cleared the gate.
Changing any of it would invalidate the validation, so the harness adds **no judge logic
of its own** — it calls `gold_eval.run_predictions` unchanged.

**What this is not:** a second human answer key. The reported accuracy is the workhorse
agreeing with the *judge*. On region the judge's measured disagreement with humans was
0/54, but 0/54 is itself a wide interval ([93.4%, 100%]), so the n=300 numbers are read
**alongside** the human-graded n=54 figures, never instead of them. The report says this
in its own header.

## 3. The sample — reused, not resampled (design fork, resolved)

The set is **`data/scale/scale_set.csv` unchanged**: the same 300 DVIDS snippets, the same
`s001…s300` ids, that v2.1.0 measured. Three alternatives were on the table.

| Option | Verdict |
|---|---|
| **Reuse the v2.1.0 set as-is** | **Chosen.** |
| Resample fresh from DVIDS | Rejected — needs `DVIDS_API_KEY`, `build_scale_set.py` refuses to overwrite, and it buys nothing the existing set lacks. |
| Resample *stratified for region balance* | Rejected — see below. |

Why reuse wins:

- **Comparability.** Every row lines up with the frozen v2.1.0 snapshot on `id`, so anyone
  who later wants a paired view of category/domain has one available for free. (That
  comparison would be **prompt-confounded** — the v2.1.0 workhorse column predates the v3
  prompt — so it is deliberately *not* reported here as a delta. Same trap PR #81 had to
  fix for ADR-012.)
- **No leakage.** The set was built excluding the corpus *and* `data/gold/gold.csv`, so the
  judge never grades its own validation data. A fresh sample would have to re-earn that.
- **Balancing would measure a wire that does not exist.** The DVIDS feed is US-actor-heavy;
  stacking the set toward `europe`/`africa` would produce a region accuracy that describes
  a corpus the classifier never sees. The honest move is to report the judge's region
  distribution as it falls and flag thin classes in the limitations block — which is
  exactly what v2.1.0 did for the `industry`/`operations` category skew.

**Accepted consequence:** thin region classes will have support too low for a quotable
per-label F1, and the region macro-F1 will be dragged down by them rather than by a
quality drop. The report's limitations block states this from the data, not from a
hardcoded caveat.

## 4. What gets built

`src/scale_region_eval.py` — a new module, **not** a migration of `src/scale_eval.py`.
That module's outputs (`evals/scale_predictions.csv`, `evals/scale_eval.txt`) are frozen
v2 records, `src/route_eval.py` imports it and is pinned to that snapshot, and
`src/baseline_ml.py` trains ADR-017's baseline off that CSV. Editing its `main()` to emit
three axes would regenerate a frozen record. New module, `_v3`-suffixed artifacts — the
same split ADR-014 used for `gold_predictions_v3.csv`.

### Reused unchanged

| Piece | From |
|---|---|
| The 300 snippets | `data/scale/scale_set.csv` |
| Workhorse + judge prediction loop, sync and `--batch` | `gold_eval.run_predictions` / `run_predictions_batch` (already three-axis) |
| Judge + workhorse model ids | `gold_eval.JUDGE_MODEL` / `WORKHORSE_MODEL` |
| Accuracy + Wilson CI + per-label metrics | `scale_eval.accuracy_row` / `per_label` / `limitations_block` |
| Wilson interval, macro-F1, confusion matrix | `eval.py` |
| Snapshot→prompt pinning | `provenance.py` |
| Atomic report write | `run_isolation.atomic_write_text` |

`accuracy_row`, `per_label` and `limitations_block` were **renamed from private to public**
in `scale_eval.py` (pure rename, no behavior change, no artifact regenerated) because two
evals now compute through them. `limitations_block` gained an optional `axes` argument so
the three-axis caller can pass its own list; the default is the two axes v2.1.0 reported.

### New

- **Resume-honesty guard** — `assert_resume_is_honest`. Appending to a partial run after a
  prompt or model change would silently blend two classifiers into one snapshot that no
  fingerprint could honestly describe. `gold_eval` has this check against its own sidecar;
  this is the same rule for the scale snapshot.
- **The `global`-cluster section** — the counts that make this eval worth running:
  answer-key `global` rows, how many the workhorse pulled to a specific region, which
  regions they were pulled to, the converse over-call, and the pull's share of all region
  disagreements. This is the evidence a HANDOFF-job-2 prompt clause would be measured
  against, and the at-scale price comparison for ADR-020's declined critic.
- **Region confusion matrix** — `evals/scale_confusion_v3_region.csv`, judge on the rows.
- **A `--run` / `--report` split** — the exemplar-eval (ADR-019) shape. `--report` builds
  the whole report from the committed CSV with no client, no key and no call, so
  re-rendering after an edit is free. Only `--run` spends.

### Explicitly NOT built (anti-creep)

- **No threshold.** Nothing is added to `evals/thresholds.toml` and `src/eval_gate.py` is
  untouched. Floors in this repo come from measured runs only (ADR-007); the measurement
  does not exist until the commands in §6 are executed. Whether the n=300 region number
  ever earns a CI floor is an owner decision **after** the run, not a guess before it.
- **No version bump, no CHANGELOG entry, no README/metrics-artifact change.** Those move
  when the measurement exists. Release mechanics for that step live in the separate
  v3.2.0 release runbook, not here.
- **No prompt change.** HANDOFF job 2 (the `global`-boundary clause) is a *fix*; this is a
  *measurement*. Measuring first is the whole method — the clause gets its own branch,
  measured against the ruler this builds.
- **No ADR yet.** The repo's pattern is spec first, ADR at verdict time (ADR-017 landed
  with its run, not with `docs/specs/ml-baseline-bakeoff.md`). The ADR recording what the
  n=300 region number means is post-run work.

## 5. Artifacts

| Path | Written by |
|---|---|
| `evals/scale_predictions_v3.csv` | `--run` (appended per row; resume-safe) |
| `evals/scale_predictions_v3.provenance.json` | `--run`, **only** on a pass that made API calls |
| `evals/scale_eval_v3.txt` | `--report` (atomic whole-file write) |
| `evals/scale_confusion_v3_region.csv` | `--report` |

Nothing under `evals/` that already exists is read-modified or overwritten.

## 6. Run protocol (owner-driven)

Live runs are owner-driven by repo contract — anything that spends tokens is handed over
as an exact command, never launched from a session. Run from the repo root.

**Recommended (batch — roughly half the per-token cost, non-interactive):**

```bash
uv run --env-file .env python src/scale_region_eval.py --run --batch
uv run python src/scale_region_eval.py --report
```

**Alternative (synchronous — live per-row progress, resumable per call):**

```bash
uv run --env-file .env python src/scale_region_eval.py --run
uv run python src/scale_region_eval.py --report
```

Both `--run` forms make **600 calls** (300 snippets × workhorse + judge) and are
resume-safe: a crash costs at most one snippet, and re-running skips ids already in the
CSV. `--report` is free and repeatable.

**If the run is interrupted and the prompt or a model has changed since**, the resume
guard refuses rather than blending. The remedy it prints is to delete
`evals/scale_predictions_v3.csv` **and** its provenance sidecar and start clean.

**Per-row refusals are expected** on this content (the s151 precedent). The batch path
skips an unparseable row and leaves it todo for the next pass; it never kills the batch.

## 7. After the run (not this spec's scope, listed so nothing is dropped)

1. Read `evals/scale_eval_v3.txt` — region accuracy + CI, the `global`-cluster counts, and
   which per-label rows have enough support to quote.
2. Decide whether the n=300 region number earns a `thresholds.toml` floor. Owner's call;
   the honest default is to wait for a second run so the floor has run-to-run noise under
   it, exactly as the v2 floors were sized.
3. Write the ADR recording the verdict, then the version bump / CHANGELOG / metrics-artifact
   sweep per the v3.2.0 release runbook.
4. HANDOFF job 2 (the `global`-boundary prompt clause) becomes measurable at this point,
   and should be measured against this ruler rather than the n=54 one.
