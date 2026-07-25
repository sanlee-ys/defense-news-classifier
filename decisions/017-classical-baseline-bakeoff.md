# ADR-017: Classical ML baseline bake-off — the LLM spend is justified by measurement

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** San Lee

**Related:** [ADR-004](004-no-ml-framework-for-eval.md) (amended scope: sklearn may model,
it may not measure) · [ADR-012](012-retire-bm25-grounding.md) / [ADR-013](013-decline-tiered-routing.md)
(the prior measure-before-escalate verdicts) · [spec](../docs/specs/ml-baseline-bakeoff.md) ·
[autonomy-ladder](../docs/specs/autonomy-ladder.md) (this harness is rung 2's substrate)

---

## Context

Every prior measurement in this repo priced a spend *layered on top of* an LLM — grounding
(retired, ADR-012) and routing (declined, ADR-013). The LLM itself had never been baselined:
nobody had asked what TF-IDF + logistic regression scores on this task for zero dollars.
The spec called the question publishable in either direction; this ADR records which
direction it fell.

Setup (full detail in the spec and `src/baseline_ml.py`): train on the 300 judge-graded
DVIDS snippets (`judge_*` labels only — training on `pred_*` would distill the workhorse),
test once on the 54-row human gold set, deliberately standard configuration (word 1–2 grams,
English stop words, min_df=2, one `LogisticRegression(class_weight="balanced")` per axis).
Metrics come from the same hand-rolled `eval.py` functions that grade the LLM.

## Decision

**The bake-off ran; the LLM wins decisively on both axes, and the result is recorded as the
first measured justification of the foundational LLM spend.** The baseline is not swapped
in anywhere; the shipped classifier is unchanged.

The verdict (`evals/baseline_eval.txt`, n=54, human answer key, same stored v3 LLM
predictions on both sides of the pairing):

| Axis | Baseline | LLM (v3 run) | McNemar (exact, paired) |
|---|---|---|---|
| category | 72.2% [59.1, 82.4] (39/54) | 92.6% [82.5, 97.1] (50/54) | 14 vs 3 discordant, **p=0.013** |
| operational_domain | 66.7% [53.4, 77.8] (36/54) | 92.6% [82.5, 97.1] (50/54) | 15 vs 1 discordant, **p=0.0005** |

Unlike the grounding and routing deltas, these clear significance even at n=54. The gap is
not noise; it is the finding.

Where the baseline fails is as informative as that it fails:

- **`policy` collapses** (recall 1/6) — short snippets about legislation share surface
  vocabulary with operations coverage; lexical features can't separate intent from topic.
- **`industry` is structurally unlearnable** here: the DVIDS-skewed train set contains
  **one** industry row. The 5-class baseline is really a 4-class baseline; disclosed, not
  hidden.
- **`land` recall 3/11 on domain** — the axis the LLM also finds hardest, but the baseline
  falls to lexical traps (Army units doing air/multi things) the LLM reads through.

The cost/latency half of the comparison went the expected way: $0.00 and ~0.1 ms/article
locally vs one workhorse API call per article. If ~70% accuracy were acceptable, the
baseline would win on economics — for this project's bar it is not, and now that trade is a
number instead of an assumption.

Secondary numbers, clearly separated because they measure agreement with the *judge*, not
with humans: 5-fold CV inside the 300 train rows scores 83.7% (category) / 73.3% (domain),
and `class_weight="balanced"` beat unweighted on both axes (83.7 vs 75.7, 73.3 vs 68.3),
settling the spec's §9 question in favor of the shipped default.

## Consequences

- The portfolio's conspicuous hole is closed: "why an LLM at all?" now has a measured
  answer — **+20 points on category, +26 on domain, p<0.02 on both.**
- Known handicaps, stated rather than hidden: train labels are judge-generated (the
  baseline inherits the judge's ~5–6% human-disagreement ceiling — the direction that
  handicaps the baseline, not flatters it); region is uncovered until v3.1.0 supplies
  labels; the single-row `industry` class caps what any train-side fix can do.
- scikit-learn enters the **dev/eval dependency group only**. Runtime deps are unchanged;
  nothing in the shipped path imports it. ADR-004's amendment already scoped its ban to
  metric computation, and the metrics here remain hand-rolled.
- The harness (`src/baseline_ml.py`) is autonomy-ladder **rung 2's substrate**: the
  agent-driven ML loop will wrap exactly this train/predict/score cycle with error-driven
  feature engineering. Building the manual version first was the spec's point.
- The spec said "next free ADR is 016"; 016 was taken by the PR-review lane in the
  interim, so the verdict lands here as 017.
