# ADR-022: The scaled region eval — the ruler shrinks, and the `global` cluster is systematic

**Status:** Accepted
**Date:** 2026-08-02
**Deciders:** San Lee

**Related:** [ADR-014](../014-region-field-design.md) (the region field, and the judge gate this
eval stands on) · [ADR-007](../007-evals-as-ci-gate.md) (floors come from measured runs) ·
[ADR-020](020-l4-multi-agent-pipeline.md) (the L4 critic fixed 6 of the 7 `global` misses at
~4× cost — the alternative this eval prices) · [ADR-017](017-classical-baseline-bakeoff.md)
(the disclosed two-axis limit this partly lifts) ·
[spec](../../docs/specs/scaled-region-eval.md) · [release runbook](../../docs/v3.2.0-release-runbook.md)

---

## Context

The region axis shipped in `v3.0.0` with exactly one number: **87.0% on n=54**, whose 95%
Wilson interval is **[75.6%, 93.6%] — 18 points wide**. Two questions could not be answered
inside an interval that wide.

1. **Is a future region change a real regression?** A prompt edit that moves the number five
   points is indistinguishable from noise at n=54. HANDOFF job 2 — a prompt clause aimed at
   the `global` cluster — had no ruler to be measured against.
2. **Is the named error cluster systematic?** All **seven** region misses on the gold set were
   rows whose true label was `global` and which the model pulled to a specific region,
   inferring a theater from the US *actor* where the snippet stated no place. Seven rows is a
   story, not a measurement.

ADR-014 made the judge conditional rather than assumed: it had to validate against human
labels *on this axis* before it could grade at scale. It did — **100.0% region agreement** on
the gold 54. The harness landed run-ready in #154 (spec: `docs/specs/scaled-region-eval.md`),
and the paid pass was owner-run on 2026-08-02.

## Decision

**Record the measurement, and read it as a ruler rather than a headline.** Full report:
[`evals/scale_eval_v3.txt`](../../evals/scale_eval_v3.txt); per-row predictions in
`evals/scale_predictions_v3.csv` with its provenance sidecar; region confusion matrix in
`evals/scale_confusion_v3_region.csv`. This ADR is the durable verdict; the release it rides
is `v3.2.0` (MINOR — additive measurement, `SYSTEM_PROMPT` / `src/api.py` / the
`{category, operational_domain, region}` contract all untouched).

### What was measured

300 DVIDS snippets (`data/scale/scale_set.csv`, the same ids v2.1.0 used — reused, not
resampled, per the spec's §3 fork), workhorse `claude-sonnet-5`, answer key the
`claude-opus-4-8` judge, same prompt and call path that cleared the ADR-014 gate.

| Workhorse vs judge | Accuracy | 95% CI (Wilson) | Macro-F1 |
|---|---|---|---|
| **Region** | **88.3%** (265/300) | [84.2%, 91.5%] | 0.904 |
| Category | 91.7% (275/300) | [88.0%, 94.3%] | 0.763 |
| Domain | 89.3% (268/300) | [85.3%, 92.3%] | 0.868 |

**The deliverable is the interval, not the point estimate.** Region's CI narrows from 18
points at n=54 to **7 points** at n=300. The accuracy landing at 88.3% against the gold set's
87.0% is corroboration — a better-known number, which is the whole ask.

### The `global` cluster is confirmed systematic

| | |
|---|---|
| Answer-key `global` rows | 70 |
| …of which pulled to a specific region | **17** |
| Converse (over-called `global`) | 10 |
| All region disagreements | 35 |
| The pull's share of them | **49%** (17/35) |
| Pulled to | americas 16, indo-pacific 1 |

Seven rows could not separate a behavior from a run of luck. Seventeen out of seventy, 49% of
every region disagreement, and 16 of 17 landing on `americas`, can: the model infers a theater
from the US actor when the snippet anchors nothing, exactly as the n=54 cluster suggested and
exactly what the rubric's no-guessing rule forbids.

**This ADR arms HANDOFF job 2; it does not implement it.** No prompt change is made here.
Measuring first is the method, and the clause now has a ruler with a 7-point interval to be
measured against instead of an 18-point one. Note the cost that has accrued to that job since
it was written: #137/#142 pinned the published snapshot to the prompt that produced it, so
touching `SYSTEM_PROMPT` hard-reds both `gen_metrics_artifact.py` and `src/eval_gate.py` until
a paid gold re-run rewrites the sidecar.

### The answer-key caveat, preserved verbatim

These numbers are **workhorse-vs-judge agreement**, not a second human answer key. The judge's
measured disagreement with humans on region was 0/54 — and **0/54 is itself a wide interval**
([93.4%, 100%]). So the n=300 figures are read **alongside** the human-graded n=54 figures in
`evals/gold_eval_v3.txt`, never instead of them. The report states this in its own header, and
any surface quoting the n=300 number inherits the obligation to say so.

Two further honesty items the report derives from the data rather than hardcoding: the DVIDS
wire is US-actor-heavy, so `americas` is 148/300 (49%) and `africa` has n=3 — which drags the
region macro-F1 (0.904) down through thin classes rather than through a quality drop. Read
overall accuracy plus the well-populated per-label rows.

### Fork 1 — where the n=300 numbers get published: **bake-off precedent**

They cannot be `data-metric`/`metric:`-marked anywhere, because `evals/metrics.json` publishes
the live *gold* block only and no artifact key exists for a scale figure; architecture's
`UNMARKED_ALLOWED` ratchet is shrink-only. Three options were on the table (runbook "Design
forks"): (a) frozen dated figures in this repo, bare prose elsewhere; (b) extend `metrics.json`
with scale keys; (c) raise the ratchet.

**Taken: (a).** The numbers live in this repo — the committed eval artifacts plus a frozen,
dated figure treatment in `README.md` carrying no managed metric markers. Architecture and
portfolio *point at* the classifier rather than quoting it. This is precisely the ADR-017
bake-off precedent: a **frozen dated measurement must not drift with a live artifact**, and a
marker is a promise that a number tracks the artifact. (b) would be a deliberate SYS-019
amendment turning a dated run into a published live key — the bake-off deliberately declined
that. (c) is against the ratchet's own shrink-only rule.

### Fork 2 — a `thresholds.toml` floor: **no**

**No floor is added; `evals/thresholds.toml` and `src/eval_gate.py` are untouched.** ADR-007's
rule is that floors come from measured runs, and this measurement now exists — but a floor
also needs run-to-run noise under it, which one run cannot supply (that is how the v2 floors
were sized). The v2.1.0 scale numbers have carried no thresholds for the same reason: a scale
pass is a **dated measurement, not a live gate**, and the offline gate grades a free committed
snapshot while re-measuring this one costs 600 calls. Revisitable after a second run.

## Consequences

- **The region axis has a usable ruler.** A 7-point interval makes a real region regression
  distinguishable from noise for the first time; HANDOFF job 2 becomes measurable.
- **The `global` cluster is evidence, not anecdote** — and it is now also the at-scale price
  comparison for ADR-020's declined critic (which fixed 6/7 of the cluster at ~4× calls).
- **No published number moves.** The gold block in `evals/metrics.json` is computed from
  `evals/gold_predictions_v3.csv` (n=54), which this run does not touch; the only byte that
  changes in the artifact is `version`. All eight gated floors stay byte-identical.
- **No live gate gets stricter**, and no prompt, model, or contract changes. The shipped
  classifier is byte-for-byte the one that produced the v3.0.0 gold numbers.
- **A dated figure is now a maintenance obligation**: the README treatment carries its date and
  its n, and must not be re-quoted as if it tracked the live artifact.

## Downstream surfaces

- **Eval artifacts (new, frozen records):** `evals/scale_eval_v3.txt`,
  `evals/scale_predictions_v3.csv`, `evals/scale_predictions_v3.provenance.json`,
  `evals/scale_confusion_v3_region.csv`. Never regenerated or overwritten, per the repo's
  frozen-record rule.
- **Version chain (one commit, or CI is red):** `pyproject.toml` → `3.2.0`, regenerated
  `evals/metrics.json`, the pinned literal + measured-at docstring in
  `tests/test_metrics_artifact.py`, and `src/api.py`'s FastAPI `version=`.
- **Release paperwork:** `CHANGELOG.md` (`[3.2.0]` heading + link refs), `CLAUDE.md` (the
  "Not yet shipped" bullet retires), `HANDOFF.md` (job 1 → shipped; owner-only pending list),
  `decisions/README.md` (this index row).
- **Prose that named the eval as future work:** `README.md` (the "Current state" heading and
  paragraph, the `(v3.1.0)` gate line, the "no region labels until v3.1.0" baseline caveat,
  and the new frozen region-CI table beside the v2.1.0 scaled-eval section), `src/ml_loop.py`,
  `src/baseline_ml.py`, `docs/specs/l4-multi-agent.md`, `docs/specs/ml-baseline-bakeoff.md`.
- **Other repos (per the release runbook's dependency chain):** `architecture`
  (`program/README.md` — the guarded `<!-- version:classifier -->` marker and the roadmap
  bullet, which points here rather than quoting the new figures per fork 1; the portal
  regenerates itself on that push), and `kb-agent`
  (`kb/projects/defense-news-classifier.md`, then `ingest.py --accept` + `index.py`).
- **Decisions:** ADR-014 (its judge gate is what licensed this run; unamended — correct on its
  date), ADR-007 (fork 2 applies its rule rather than changing it), ADR-020 (this is the
  at-scale sizing of the cluster its critic fixed), ADR-017 (its disclosed "no region labels"
  limit is now dated rather than open-ended).
- **Not touched, deliberately:** `evals/thresholds.toml`, `src/eval_gate.py`,
  `classify.SYSTEM_PROMPT`, `src/api.py`'s behavior, every frozen v2 record
  (`evals/scale_eval.txt`, `evals/baseline_eval.txt`, `evals/l4_eval.txt`,
  `evals/gold_eval_v3.txt`), and portfolio / learning-notes — whose gates stay green and whose
  optional prose is deferred, fork 1 keeping the new figures out of them regardless.
