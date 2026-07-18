# ADR-013: Decline tiered model routing — measured, it buys nothing at ~2x the cost

**Status:** Accepted
**Date:** 2026-07-18
**Deciders:** San Lee

**Closes out:** [ADR-011](011-reaim-tiered-routing-technology-operations.md) (which re-aimed
the v2.2.0 routing target at `technology`-vs-`operations` and set the gate this ADR now
answers).

---

## Context

The roadmap's v2.2.0 was **tiered model routing**: escalate only low-confidence cases to the
Opus tier, measure the cost/quality trade. [ADR-011](011-reaim-tiered-routing-technology-operations.md)
aimed it at the `technology`→`operations` boundary — the one clustered miss on the real gold
set — and set an explicit gate: first see whether the
[PR #79](https://github.com/sanlee-ys/defense-news-classifier/pull/79) prompt fix already
cleared that cluster, because *routing is the fallback for the residual the prompt cannot fix,
not the first tool*.

By the time the experiment was built, the gate already read as "cleared": #79 took
`technology` recall to 1.000 vs human on the gold set, and the v2.1.0 scaled eval corroborated
the overall numbers at n=300. So the experiment shipped
([PR #84](https://github.com/sanlee-ys/defense-news-classifier/pull/84)) with its hypothesis
stated up front: routing likely no longer pays. `src/route.py` manufactures the confidence
signal the forced-tool classifier lacks (a required `runner_up_category` field; escalate
exactly when the top-two categories are {technology, operations}), and `src/route_eval.py`
measures the verdict with three honesty guards: quality graded **only on the n=54 human gold
set** (the scale set's answer key is the Opus judge — the escalation target itself — so it
reports rate and cost, never "accuracy"); escalations **replayed from the stored judge
predictions** (same model, same call shape — zero new Opus spend); and the runner-up schema's
perturbation of the workhorse's own labels measured rather than assumed away.

The measured verdict (`evals/route_eval.txt`, one workhorse batch pass over gold n=54 +
scale n=299):

| System | Category vs human (n=54) | Domain vs human (n=54) |
|---|---|---|
| workhorse only | 94.4% [84.9, 98.1] | 92.6% [82.5, 97.1] |
| routed | 94.4% — **+0 rows** | 92.6% — **+0 rows** |
| all-Opus | 94.4% | 94.4% |

- **Escalated rows: fixed 0, broke 1, unchanged 8.** The trigger found the right
  neighborhood — the 9 gold escalations include g007/g036/g040, the original ADR-011
  cluster — but there is nothing left there to fix, and the one label escalation *did*
  change was an import of the judge's own known tech→ops error (g007): Opus overrode a
  correct workhorse answer.
- **No headroom even at the ceiling:** all-Opus scores the same 94.4% category as the
  workhorse. On this axis a router can only shuffle which rows are wrong.
- **Cost: ~1.97x per article.** The trigger fires on 19.4% of real articles (58/299), and
  only 2 of those 58 escalations changed the label at all. At a 5:1 Opus:Sonnet list-price
  ratio, that is double the cost for zero measured quality.
- **Schema perturbation is small but real:** adding the runner-up field moved 2/54 category
  calls (0/54 domain) — and, notably, flipped one snippet (s151, a chem-bio *defense*
  program story) from a clean `technology/multi` classification into a safety-layer
  **refusal**. The measurement shape itself changed model behavior; the harness records and
  excludes it rather than hiding it.

## Decision

**Decline tiered model routing for the shipped classifier, and ship v2.2.0 as the measured
negative result.** Concretely:

- **The shipped path stays single-model.** `classify()` on the Sonnet workhorse remains the
  product; `classify_routed()` is not adopted by the API, the evals, or any caller.
- **Ship the experiment as the release.** The v2.2.0 tag carries the routing harness, the
  measurement, and this ADR — the deliverable is the verdict, exactly as scoped when the
  experiment was approved ("build the routing experiment, ship the verdict").
- **Keep the code dormant, not deleted.** `src/route.py`, `src/route_eval.py`, their tests,
  and the `evals/route_*` artifacts stay as the reproducible record, mirroring the ADR-012
  BM25 retirement. Nothing imports them in the shipped path.
- **Close ADR-011.** Its gate was answered: the prompt fix cleared the target before routing
  could, which is the outcome its own framing preferred ("the cheapest fix wins").

## Consequences

- **The guiding principle now has two data points.** "Model tier is a cost/quality knob
  decided by the eval, not by default" has now declined the escalation twice with data:
  BM25 grounding (ADR-012) and tiered routing (this ADR). The 94%+ single-model,
  single-call classifier *is* the measured optimum of everything tried against it.
- **The confidence-signal groundwork survives.** The runner-up-field technique (manufacturing
  a routing signal under forced tool use) is built, tested, and measured — including its
  perturbation cost. Any future routing idea starts from this harness and must beat these
  numbers, not from zero.
- **A residual worth naming for v3.0.0:** all-Opus *does* beat the workhorse on the domain
  axis (+1 row, 94.4% vs 92.6% — inside n=54 noise, but the only axis with any measured
  headroom). If routing is ever revisited, the target is domain, not category — and the
  trigger would need rethinking, since the runner-up field as built reports only categories.
- **The safety-layer interaction is on record.** s151 shows a schema change alone can flip a
  benign defense snippet into a refusal on a safeguarded model. Bulk harnesses against
  Sonnet-tier-plus models must treat refusals as an expected per-row outcome
  ([PR #85](https://github.com/sanlee-ys/defense-news-classifier/pull/85) made both runner-up
  passes record-and-continue), not an exception.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Adopt routing anyway ("Opus can't hurt") | It measurably can: the only label change on gold was Opus overriding a correct workhorse answer with the judge's known error. 1.97x cost, +0 rows, and a new wrong answer is strictly worse than the baseline. |
| Route on the domain axis instead (the one with headroom) | The +1-row all-Opus domain edge is a single flip inside n=54 noise, and the built trigger doesn't observe domain uncertainty. A defensible future experiment, but it needs its own signal design and a measured case — parked, not smuggled in. |
| Loosen the trigger (escalate more) or tighten it (escalate less) and re-measure | The all-Opus row bounds every possible category router at +0 on this gold set — no trigger tuning can beat a ceiling the escalation target itself doesn't clear. |
| Escalate to a different premium model than the judge | Breaks the zero-new-spend replay design and the judge-validation chain for no stated hypothesis of why another model would beat Opus here. |
| Delete the routing code | Same call as ADR-012: in a portfolio repo the *built-it-measured-it-declined-it* trail is the artifact. Dormant-but-inspectable beats a clean tree. |
