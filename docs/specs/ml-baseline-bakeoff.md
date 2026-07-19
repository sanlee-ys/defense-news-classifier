# Feature Spec — Classical ML Baseline Bake-Off

**Version:** 0.1 (Draft)
**Status:** Proposed — not started
**Author:** San Lee
**Last updated:** 2026-07-19
**Roadmap fit:** new **MINOR** (additive measurement harness; the `{category, operational_domain, region}` output contract is untouched, and nothing is swapped into the shipped classifier).
**Related:** [ADR-004](../../decisions/004-no-ml-framework-for-eval.md) (no ML framework — this spec proposes a bounded exception) · [ADR-012](../../decisions/012-retire-bm25-grounding.md) and [ADR-013](../../decisions/013-decline-tiered-routing.md) (the two prior measure-before-escalate verdicts) · [autonomy-ladder](autonomy-ladder.md) (this is the substrate for rung 2)

---

## 1. Problem Statement

This repo's thesis is **measure before you spend**. It has earned that three times: BM25 grounding measured and retired ([ADR-012](../../decisions/012-retire-bm25-grounding.md)), tiered routing measured and declined ([ADR-013](../../decisions/013-decline-tiered-routing.md)), and judge-tier escalation measured and declined in the sibling faithfulness-judge repo.

Every one of those measures a spend *layered on top of* an LLM. **The LLM itself has never been baselined.** Nobody has asked what TF-IDF plus logistic regression scores on this task for zero dollars and single-digit milliseconds.

That is the conspicuous hole. A reader who takes the thesis seriously asks the question in the first thirty seconds, and the repo has no answer. It became more conspicuous, not less, when the profile README was cut to four projects that all argue measurement rigor (2026-07-19).

**This is publishable in either direction**, which is rare and is the main reason to build it:

- Baseline lands far below the LLM → the foundational spend is finally justified with a number instead of an assumption.
- Baseline lands close to the LLM → that is the strongest negative result in the portfolio. "I built the LLM version, then measured the free alternative, and it was within a few points" is a more senior thing to publish than another accuracy score.

There is no outcome where the measurement is wasted.

---

## 2. Goals

| # | Goal |
|---|------|
| G1 | Train a classical baseline (TF-IDF → logistic regression) for **category** and **operational_domain** and score it on the same human gold set the LLM is scored against. |
| G2 | Report the comparison honestly, with the sample-size caveat attached to every figure. |
| G3 | Report the **cost and latency** axis alongside accuracy — this is where the baseline is expected to win by orders of magnitude, and it is half the decision. |
| G4 | Land an ADR recording the verdict, whichever way it falls. |
| G5 | *(Upside)* If the baseline is close, that becomes the headline finding for the repo and the portfolio page. |

---

## 3. Non-Goals

- **Beating the LLM, or any accuracy target as a release gate.** The deliverable is a rigorous comparison. Gating "done" on the result pressures the exact metric-gaming this repo exists to avoid.
- **Swapping the baseline into the shipped classifier.** Measurement experiment, not a production change. The shipped path stays single-model, single-call.
- **Region.** See §4 — the training labels do not cover it. Region is category+domain's problem to solve later, not this spec's.
- **Fine-tuning a transformer.** That is the v2 idea (DistilBERT/ModernBERT on Colab) and needs more labeled real data. Out of scope, stays parked.
- **New hand-labeling.** Everything needed already exists in-repo.
- **The agent-driven ML loop (autonomy ladder rung 2).** This baseline is its substrate. Build the manual version first so rung 2 knows what it is wrapping.

---

## 4. Data — read this before writing any code

**Decided 2026-07-19 (San).** Train on the judge-graded scaled set, test on the human gold set.

| Split | File(s) | n | Labels |
|---|---|---|---|
| **Train** | `data/scale/scale_set.csv` (text) joined on `id` with `evals/scale_predictions.csv` (labels) | 300 | `judge_category`, `judge_operational_domain` |
| **Test** | `data/gold/gold.csv` | 54 | `category`, `domain`, `region` — human, hand-labeled |

Three things that will bite whoever builds this:

1. **`scale_set.csv` has no labels in it.** Columns are `id,dvids_id,source_url,text`. The labels live in `evals/scale_predictions.csv` (`id,pred_category,pred_operational_domain,judge_category,judge_operational_domain`). **Train against `judge_*`, never `pred_*`** — `pred_*` is the workhorse LLM's own output, and training on it would make the baseline a distillation of the model it is supposed to be an alternative to. That is the single most likely way to silently invalidate this experiment.

2. **There is no region label in the training data.** The v2.1.0 scaled eval covered category and domain only; the scaled region eval is v3.1.0 and unscheduled. So the baseline covers **two axes, not three**, and the writeup must say so rather than quietly omitting region.

3. **The train labels are judge-generated, not human.** This is the disclosed cost of the data decision (the alternative was training on synthetic text, which introduces a synthetic-to-real transfer confound instead). Consequence to state plainly in the ADR and README: **the baseline is learning to imitate the Opus judge**, so it inherits that judge's ~5–6% disagreement-with-human ceiling. It is then tested against *human* labels, which is the honest direction for that asymmetry to run — the baseline is handicapped relative to the LLM, not flattered.

The train and test sets are disjoint by construction (`scale_set.csv` was built disjoint from both the corpus and the gold set — see the v2.1.0 notes in the README).

---

## 5. Approach

Deliberately boring. The point is a *standard* baseline, not a clever one — a hand-tuned baseline invites "you rigged it," and a handicapped baseline invites "you rigged it the other way."

- **Features:** `TfidfVectorizer`, word n-grams (1,2), English stop words, `min_df=2`. Fit on train only.
- **Models:** two independent `LogisticRegression` classifiers, one per axis (category 5-class, domain 6-class), `class_weight="balanced"` to attack the known `industry` and `space` imbalance.
- **No tuning against the test set.** If any hyperparameter search happens, it is cross-validation *within* the 300-row train split. The 54 gold rows are touched exactly once, at the end. Write the code so this is structurally hard to violate.
- **Scoring:** reuse the existing eval surface (`src/eval_confusion.py` and friends) so the baseline's numbers and the LLM's numbers come out of the same code path. A separate scoring path would be its own artifact.
- **Cost/latency:** record wall-clock inference time for 54 rows and the dollar cost (zero) next to the LLM's per-call cost and latency. This is G3 and it is not an afterthought — it is the half of the comparison the baseline is expected to win.

### The dependency decision (surface this, do not just do it)

TF-IDF + logistic regression means **scikit-learn**. [ADR-004](../../decisions/004-no-ml-framework-for-eval.md) was amended 2026-07-19 to scope its ban to *metric computation*, so this is **not an exception to it** — a baseline model the eval measures is outside that ADR's scope by its own terms. An earlier draft of this spec framed it as a bounded exception; that was a misreading of ADR-004, whose stated reasons were always about metrics.

- **Zero-dep alternative:** hand-roll TF-IDF and logistic regression. Real cost: a hand-rolled baseline is not the *standard* baseline, so a skeptical reader discounts a loss ("your implementation was bad") and discounts a win equally. It also spends a day on machinery that is not the point.
- **Do:** add `scikit-learn` to the **dev/eval dependency group**, not the runtime dependencies.
- **Do not:** let sklearn's arrival become a reason to replace the hand-written metrics with `classification_report`. ADR-004's amendment forbids that explicitly, and the reason is that the hand-rolled metrics are portfolio signal.
- The shipped classifier's runtime deps are unchanged. Nothing in `src/classify.py` or `src/api.py` imports sklearn.

---

## 6. Deliverables

1. `src/baseline_ml.py` — train, predict, persist the fitted vectorizer + models.
2. `evals/baseline_eval.txt` — the report: accuracy per axis, per-label precision/recall/F1, confusion matrices, and the cost/latency comparison.
3. `evals/baseline_predictions.csv` — per-row predictions on the 54 gold rows, for auditability.
4. Tests in `tests/`, offline, no API key. At minimum: the train/test join is correct, `judge_*` is the label source and `pred_*` is never read, and the gold set is not used in fitting.
5. **An ADR** recording the verdict and the sklearn exception. Next free number is **015** (014 is the region field).
6. README section leading with the comparison, with the n=54 caveat attached.

---

## 7. Definition of Done

1. Baseline trains from committed data with one offline command, no API key.
2. It scores on the 54 gold rows through the existing eval path.
3. `evals/baseline_eval.txt` reports both axes, per-label breakdowns, and cost/latency.
4. Tests pass offline; the no-test-set-leakage test exists and is meaningful.
5. ADR-015 records the verdict and the bounded ADR-004 exception.
6. README states the comparison honestly, including that region is uncovered and that train labels are judge-generated.

---

## 8. Honest-reporting rules (non-negotiable)

This repo has shipped a soft-number-dressed-as-solid before, in the sibling faithfulness-judge repo's headline. The rules that came out of it apply here:

- **Every accuracy figure carries its n.** At n=54 a difference of a few points is inside the interval. Report the interval or report the raw counts.
- **A delta is not a finding.** If the baseline is within a few points of the LLM, run the significance test on the paired predictions (McNemar on the discordant rows) before writing any sentence that implies one is better.
- **Report the direction that hurts.** If the baseline wins on an axis, that is the headline, not a footnote.
- **Name what is uncovered.** Region, judge-generated training labels, single small test set.

---

## 9. Open questions for the build session

- Should the baseline also be scored against the **300 judge labels** via cross-validation, as a second number with a tighter interval? It measures a different thing (agreement with the judge, not with humans) but the n is 5× larger. Probably yes, reported separately and clearly labeled — but it is a call.
- Is `class_weight="balanced"` the right default given the DVIDS operations skew, or does it distort the majority class enough to matter at this n? Worth one experiment, reported either way.
