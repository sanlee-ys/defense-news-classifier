# ADR-003: Use synthetic data only — no real news articles

**Status:** Accepted  
**Date:** 2026-06-19  
**Deciders:** sanlee

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
