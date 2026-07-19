# ADR-003: Use synthetic data only — no real news articles

**Status:** Accepted; **amended 2026-07-19** — scope narrowed, **not superseded** (see [Amendment](#amendment-2026-07-19))  
**Date:** 2026-06-19  
**Deciders:** San Lee

---

## Context

A labeled dataset is required to train-test the classifier. Options:

1. **Scrape real news** — Reuters, Defense News, Breaking Defense, etc. Requires a scraper, licensing review, and human annotation for ground-truth labels.
2. **Use an existing labeled dataset** — none found that match this specific label schema (category + operational domain).
3. **Generate synthetic articles via LLM** — same API, same tool-use pattern, fully controlled label distribution.

## Decision

Generate all data synthetically using the same model (`claude-sonnet-4-6`). One API call per category × domain combination (30 calls), producing 10 articles each (300 total), uniformly distributed.

## Consequences

**Practical advantages:**
- No scraping pipeline, no licensing issues, no annotation cost.
- Perfectly balanced dataset — 10 articles per label pair, no class imbalance to manage.
- Label distribution is controlled and reproducible.

**Known limitation — circular eval:**  
The same model generates the data and classifies it. The eval measures in-distribution consistency: does the classifier agree with the generator's labeling? It does not measure generalization to real-world news written by humans. This limitation is documented prominently in the README and PRD.

**Synthetic text bias:**  
Generated snippets are stylistically more uniform than real news articles (similar sentence structure, vocabulary, level of specificity). A classifier trained purely on this data would likely overfit to that style.

These are known, accepted trade-offs for a v1 portfolio project. A v2 eval against human-labeled real news would address both.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Scrape real news | Adds scraper complexity and licensing uncertainty; human annotation required for ground truth |
| Existing dataset | None found matching the two-field schema |
| Mix of real + synthetic | Adds complexity without a clear quality benefit at v1 scope |

---

## Amendment (2026-07-19)

**This ADR is narrowed, not superseded, and the distinction matters.**

The title reads "no real news articles," which has been false since v2: the project now
carries a 54-snippet hand-labeled gold set and a 300-snippet judge-graded scaled set, both
real public DVIDS text. A reader skimming the status could reasonably mark this Superseded
and conclude the synthetic corpus is retired.

**It is not retired, and marking it so would be a live hazard.**
`data/synthetic_articles.csv` is the **A/B split of the prompt-optimization loop**
([ADR-005](005-agentic-prompt-optimization-loop.md) names it as the source for both A and B),
and it is read by `src/optimize.py`, `src/eval.py`, `src/generate.py`, and fixtured in
`tests/test_eval.py`, `tests/test_optimize.py`, and `tests/test_stability.py`. Deleting it in
a cleanup sweep would take the Level-3 autonomy-ladder rung
([ADR-006](006-autonomy-ladder-portfolio-spine.md)) with it.

So, precisely:

- **Expired:** the *cost* rationale for rejecting real news ("scraper complexity, licensing
  uncertainty, annotation cost"). Real public-domain text was sourced and hand-labeled
  without a scraper, and the annotation cost was paid. That argument no longer decides
  anything.
- **Expired:** "no class imbalance to manage." True of the synthetic set, not of the real
  ones — the DVIDS wire is operations-heavy, which is why the scaled run documents its
  category macro-F1 as uninformative.
- **Live:** the synthetic corpus itself, as the loop's A/B substrate. Its *stylistic
  uniformity*, once listed as a limitation, is now a mild feature in that role: A and B are
  drawn from the same distribution, so an A-vs-B gap reads as memorization rather than
  distribution shift.
- **Live:** the circular-eval caveat, for any number computed on the synthetic set alone.
  It is why the real gold set exists and why the loop's honest number is split C.

**What this ADR no longer governs.** Data sourcing for real text — public-domain only, DVIDS
plus hand-pulled filings — is a live constraint with no home. It is asserted in
`data/gold/README.md` and honored in practice, but never decided anywhere. That deserves its
own ADR rather than being read into this one. **Written 2026-07-19 as
[ADR-015](015-public-domain-data-sourcing.md).**
