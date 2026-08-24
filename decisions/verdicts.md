# Experiment verdicts

**What this file is.** A dated log of every experiment this project ran and what the numbers
said. One row per experiment. It is an index, not an archive: each entry links to the full
record, which keeps its original text under [`archive/`](archive/).

**Why it is not a set of ADRs.** An ADR records a decision that governs the code from now on.
A verdict records a result. The two look alike on the page and behave nothing alike: a
decision is meant to be stable and few, a result is meant to accumulate. This repository
wrote ten verdicts as ADRs before the difference became visible, and the cost was a decision
log where most entries decided nothing. New experiments add a row here. They do not take an
ADR number.

**The house style is unchanged: the negative result ships.** Six of the ten entries below
declined the thing they measured. That is the point of measuring, and each one is a
[`docs/how-it-works.md`](../docs/how-it-works.md) claim the project earned rather than
assumed.

## The log

| Date | Experiment | Result | Call | Full record |
|---|---|---|---|---|
| 2026-07-19 | Pin the RAG path to `claude-sonnet-4-6` after the Sonnet-5 migration | Domain regression on the grounded path only; category grounding still cleared its floors at +1.9% | Split the model constant, transitional. **Superseded** when grounding was retired | [ADR-010](archive/010-rag-path-model-pin.md) |
| 2026-07-22 | Which boundary should tiered routing escalate? | The real-text gold set showed workhorse-versus-human disagreement on `technology`/`operations`, not `industry`/`procurement` | Re-aimed at `technology`/`operations`. **Closed by ADR-013**: a prompt fix cleared the target before routing could | [ADR-011](archive/011-reaim-tiered-routing-technology-operations.md) |
| 2026-07-23 | Does BM25 retrieval grounding still pay under the improved prompt? | No. The lift it once had did not survive the prompt improvement | **Retired.** Ungated, removed from CI, code kept dormant as the record | [ADR-012](archive/012-retire-bm25-grounding.md) |
| 2026-07-24 | Does tiered model routing beat the single-model classifier? | No measurable gain at roughly 2x the cost | **Declined.** Shipped as `v2.2.0`, the release whose deliverable is the verdict | [ADR-013](archive/013-decline-tiered-routing.md) |
| 2026-07-25 | Does a classical TF-IDF + logistic-regression baseline match the LLM? | category 72.2% vs 92.6% (McNemar p=0.013); domain 66.7% vs 92.6% (p=0.0005), n=54 human answer key | **LLM spend justified by measurement.** Baseline not swapped in anywhere | [ADR-017](archive/017-classical-baseline-bakeoff.md) |
| 2026-07-25 | Does kNN-exemplar few-shot beat the zero-shot prompt? | Null. scale category 90.0% to 91.0% (p=0.70); gold category 92.6% to 88.9% (p=0.69) | **Declined.** Harness kept dormant with its tests | [ADR-019](archive/019-knn-exemplar-fewshot.md) |
| 2026-07-25 | Does an L4 triage/classify/critic pipeline improve labels? | Hypothesis confirmed, pipeline harmful as configured: gold domain 92.6% to 81.5%, scale domain 91.3% to 86.7% (**p=0.016**) | **Declined as configured.** The honesty test passed; the pipeline did not | [ADR-020](archive/020-l4-multi-agent-pipeline.md) |
| 2026-08-02 | What is the real region accuracy at n=300 rather than n=54? | region **88.3%** 95% CI [84.2, 91.5], macro-F1 0.904; category 91.7%, domain 89.3%. The CI narrows from 18 points to 7 | **Recorded as a ruler, not a headline.** Shipped `v3.2.0`. No `thresholds.toml` floor: one run has no run-to-run noise under it | [ADR-022](archive/022-scaled-region-eval-verdict.md) |
| 2026-08-02 | Does a `global`-boundary prompt clause fix the named-cluster pulls? | region 88.5% to 92.2%, 12 of 17 named pulls fixed against 7 correct rows dragged, net +11, at **McNemar p=0.0522** against a pre-registered p<0.05 | **Reverted as marginal.** Claimed no version | [ADR-023](archive/023-global-boundary-clause-verdict.md) |
| 2026-08-03 | The same clause, re-run at adequate power | All four pre-registered rules pass at effective n=595, **p=0.0002** | **Adopted unchanged.** Shipped `v3.2.1`, a PATCH | [ADR-024](archive/024-global-boundary-clause-adopted.md) |
| 2026-08-23 | Do the 42 domain-axis disagreements (92.9%, the lowest axis) contain a clause-targetable error cluster? | 23 of 42 are majority model errors under a 3-analyst majority rule, split across 7 mechanisms; the largest carries **6** rows against a pre-set bar of 15 (the n=595 power floor). 10+ rows are judge errors, and the key contradicts itself: s370/s371 are one snippet keyed both `land` and `multi` | **No clause to write.** The domain bottleneck is the RULER: any future domain work starts by re-adjudicating the key and closing the rubric's zero-domain gap, not by prompting against key noise | `evals/domain_error_audit.md` |
| 2026-08-23 | Do the Ralph loop's two category clauses (run 2's accepted candidate, B +0.106 on synthetic) survive a powered real-text A/B? | category 94.1% to 94.8%, 10 fixed against 6 broken over 579 ties, **McNemar p=0.4545** against a pre-registered p<0.05; guardrails clean; harness clean at n=595 | **Declined.** The B gain did not transfer off the synthetic set at any size this design can see (>=3% at 0.90 power). A ~+1% effect is not ruled out; chasing it needs n~3-4k and a NEW registration, per rule 0. The loop branch stays unmerged as the record | [spec](../docs/specs/loop-candidate-category-eval.md) + `evals/loop_candidate_scale_eval.txt` |

## Two entries that are one story

ADR-023 and ADR-024 measure the same prompt clause twice. It failed at n=300 and passed at
n=595. Read together they make the project's sharpest point about measurement: **across the
two rounds the ruler changed and the bar never did.** The clause was not re-argued into
acceptance. It was re-measured at a sample size that could resolve it.

They are kept as two records because the first one is the evidence that the bar held. A
single merged entry would read as though the clause was adopted on the first try.

## How to add an entry

Add a row. Put the full record wherever it belongs: an `evals/` report is usually enough, and
a spec under `docs/specs/` if the experiment was pre-registered. Do not open an ADR unless
the result changes how the code is built from now on. If it does, the ADR records that
change and cites this row for the evidence.
