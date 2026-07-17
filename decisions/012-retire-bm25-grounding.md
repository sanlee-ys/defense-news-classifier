# ADR-012: Retire BM25 retrieval grounding — it no longer pays under the improved prompt

**Status:** Accepted
**Date:** 2026-07-17
**Deciders:** San Lee

**Supersedes:** [ADR-010](010-rag-path-model-pin.md) (the RAG path's `claude-sonnet-4-6` pin
becomes moot once grounding is retired).

---

## Context

v2.0.0 added BM25 retrieval grounding: each classification is conditioned on the top-3
label-tagged corpus neighbours. [ADR-010](010-rag-path-model-pin.md) pinned the grounded
path to `claude-sonnet-4-6` after grounding regressed the Sonnet-5 domain field, and left
open the question of whether grounding still earns its place.

The tech-vs-ops prompt change ([PR #79](https://github.com/sanlee-ys/defense-news-classifier/pull/79))
lifted the **ungrounded** classifier materially (category 90.7% → 94.4%, domain 90.7% →
92.6% on the gold set). That forced an honest re-measure of grounding — and surfaced that
the RAG comparison had been scoring **new-prompt grounded against an old-prompt frozen
baseline**, inflating the apparent lift. `scripts/refresh_rag_baseline.py`
([PR #81](https://github.com/sanlee-ys/defense-news-classifier/pull/81)) rebuilt the
same-model ungrounded baseline under the current prompt so both arms match.

With a fair baseline, grounding no longer helps. Confirmed with a 3-pass run
(`scripts/confirm_rag_grounding.py`, mirroring ADR-010's 3× methodology), 4.6 pin, k=3, n=54:

| Pass | Category Δ | Domain Δ | Domain fix / break |
|---|---|---|---|
| 1 | +1.9% | **−1.9%** | 0 / 1 |
| 2 | +0.0% | **−3.7%** | 0 / 2 |
| 3 | +0.0% | **−1.9%** | 0 / 1 |

The decisive number: across all three passes — **162 grounded classifications — grounding
fixed a domain call zero times and broke four.** Every domain delta is negative (mean
≈ −2.5%). Category is a wash (mean ≈ +0.6%, fixes ≈ breaks). This is ADR-010's mechanism
recurring, now via the prompt rather than the model: once the ungrounded classifier is good
enough, lexical BM25 neighbours pull confident, correct calls sideways more often than they
help — worst on domain, where a snippet's warfighting domain is rarely disambiguated by
lexically-similar neighbours.

The measured verdict from v2.0.0 ("BM25 grounding doesn't justify upgrading to embeddings")
has hardened into a stronger one: **BM25 grounding doesn't justify itself.** Neutral at best,
a domain regression at worst, and — because the mean domain delta straddles the −3% gate
floor — a source of flaky CI if kept in the gated path.

## Decision

**Retire BM25 retrieval grounding from the shipped and gated path, and record it as a
measured negative result.** Concretely:

- **Ungate it.** Remove the `[rag]` table from `evals/thresholds.toml`, the `check_rag`
  path from `src/eval_gate.py` (and its tests), and the RAG jobs from
  `.github/workflows/evals.yml`. The offline/live gates now grade only the ungrounded
  baseline (the shipped classifier).
- **Stop claiming a grounding lift.** The README's grounding sections are rewritten to state
  the retirement and the negative result, in the project's standing "ship the negative
  result" voice.
- **Supersede ADR-010.** With grounding retired, the 4.6 pin and the frozen RAG baseline it
  introduced are moot; ADR-010 is marked Superseded by this ADR.
- **Keep the code dormant, not deleted.** `src/classify_rag.py`, `src/retrieve.py`,
  `src/gold_eval_rag.py`, the `data/corpus/`, and the `scripts/*rag*` measurement tooling
  stay in the repo as the archived record of the experiment — they are no longer imported by
  the shipped classifier, gated in CI, or claimed in the README. This is a portfolio repo;
  the *built-it-measured-it-retired-it* trail is worth more than a clean deletion.

The shipped classifier is unaffected: it was always the ungrounded `classify()` call, and the
live API (`src/api.py`) never used grounding, so the service and its consumers (e.g.
kb-agent's `classify_snippet`) are untouched.

## Consequences

- **The gate grades what ships.** Only the ungrounded baseline is gated, so CI can no longer
  go red (or flaky) on a grounding delta for a path that isn't shipped.
- **Honest story, no dangling claim.** The README stops crediting grounding with a lift it
  doesn't provide under the current prompt. The negative result is stated plainly.
- **The RAG artifact remains inspectable.** A reader can still run `gold_eval_rag.py` /
  `confirm_rag_grounding.py` to reproduce the verdict against the dormant code and corpus.
- **Semantic/embedding retrieval stays parked.** The v2 parking-lot condition ("only if a
  larger eval overturns the BM25 verdict") is *not* met — this result reinforces the verdict,
  it doesn't overturn it. If ever revisited, it starts from "grounding must beat a 94%+
  ungrounded baseline," a high bar.
- **n=54 caveat stands.** The verdict rests on the same small gold set; v2.1.0 (scale the
  eval) could revisit it. But the direction is unambiguous (0 domain fixes in 162 tries), so
  retirement is the right call on current evidence, not a coin-flip deferred.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Keep grounding, loosen `domain_delta_min` to stop the gate failing | Exactly what ADR-010 forbade: lowering a quality floor to hide a real, measured regression. The floor is a promise. |
| Drop domain grounding, keep category grounding (ADR-010's suggested follow-up) | Category grounding is neutral under the new prompt (+1.9/0/0, fixes ≈ breaks), so category-only grounding buys ~nothing while keeping the retrieval stack, the corpus, and a second model pin in the shipped path. Not worth the complexity. |
| Re-tune retrieval (k, corpus filtering, score thresholds) to recover a positive delta | Possible, but speculative spend against a 94%+ baseline where lexical neighbours have little left to add. If retrieval is revisited it should be embeddings vs. this baseline, decided by measurement — not BM25 tuning to rescue a retired path. |
| Hard-delete the grounding code and corpus | Cleaner tree, but discards the artifact. In a portfolio repo the measured-and-retired experiment is a feature, not clutter; dormant-but-inspectable is the better record. |
