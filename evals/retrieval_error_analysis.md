# BM25-vs-embeddings analysis -- would a better retriever fix the misses?

*Purpose: quantify how much of the gold-eval's **residual** error is even addressable by swapping BM25 for a semantic (embedding) retriever, before spending a Voyage AI dependency to find out. This is a read-only analysis over the committed run -- not a change to the retrieval layer.*

> **Method.** For every grounded (BM25 + top-k context) miss, look at the doc ids BM25 actually retrieved (the `citations` column of `evals/gold_rag_predictions.csv`) and check whether any of them carried the human-truth label in the corpus manifest. If yes, the right context was already in front of the model and it missed anyway -- a **vocabulary / label-boundary** error a better retriever cannot fix. If no, BM25's lexical match pulled topically-wrong context -- a **semantic / paraphrase** error where embeddings could plausibly help.

Snippets analyzed: **54**.  Grounded misses across both fields: **11** (2 retrieval-on-target, 9 retrieval-off-target).

## Headline

**9 of 11 residual misses (82%) are retrieval-off-target** -- BM25 surfaced no top-k doc carrying the true label. Only these could *possibly* move with a semantic retriever, so this is an **upper bound** on the embeddings-addressable slice: 9 of 54 snippets (17%).

**2 of 11 (18%) are retrieval-on-target** -- BM25 already retrieved a same-label doc and the model still picked another. Those are provably not retrieval's fault; a semantic retriever changes nothing there.

**The upper bound overstates the real prize.** Retrieval-off-target is *necessary but not sufficient* for embeddings to help: the corpus is only ~62 docs, so BM25 can miss a same-label doc simply because none is lexically near the snippet (a coverage gap, not a semantic-vs-lexical gap). And the off-target transitions below cluster in the exact overlapping-definition label pairs the synthetic-set `error_audit.md` flags (operations / procurement / technology / policy on category; air / land / multi on domain) -- label-boundary calls a better retriever wouldn't disambiguate. The genuinely retrieval-addressable count is some fraction of these, not all of them.

### Transitions among retrieval-off-target misses

| True -> Grounded (field) | Count |
|---|---|
| `operations` -> `policy` (category) | 2 |
| `air` -> `land` (operational_domain) | 2 |
| `operations` -> `procurement` (category) | 1 |
| `operations` -> `technology` (category) | 1 |
| `technology` -> `procurement` (category) | 1 |
| `air` -> `multi` (operational_domain) | 1 |
| `cyber` -> `multi` (operational_domain) | 1 |

## Per-field breakdown

| Field | Baseline misses | Grounded misses | Retrieval on-target (vocab) | Retrieval off-target (semantic) |
|---|---|---|---|---|
| category | 6 | 5 | 0 | 5 |
| operational_domain | 6 | 6 | 2 | 4 |

## Per-case detail (grounded misses)

`retrieval_hit = True` means BM25 already retrieved a doc with the true label -- so the error is not a retrieval failure.

| ID | Field | True -> Grounded (Baseline) | Retrieval hit? | Verdict |
|---|---|---|---|---|
| g010 | category | `operations` -> `procurement` | NO | semantic / paraphrase (embeddings could plausibly help) |
| g013 | category | `operations` -> `technology` | NO | semantic / paraphrase (embeddings could plausibly help) |
| g038 | category | `technology` -> `procurement` | NO | semantic / paraphrase (embeddings could plausibly help) |
| g045 | category | `operations` -> `policy` (was operations) | NO | semantic / paraphrase (embeddings could plausibly help) |
| g053 | category | `operations` -> `policy` | NO | semantic / paraphrase (embeddings could plausibly help) |
| g017 | operational_domain | `land` -> `sea` | yes | vocabulary / label-boundary (embeddings would NOT help) |
| g021 | operational_domain | `air` -> `land` | NO | semantic / paraphrase (embeddings could plausibly help) |
| g038 | operational_domain | `air` -> `land` (was air) | NO | semantic / paraphrase (embeddings could plausibly help) |
| g039 | operational_domain | `air` -> `land` (was air) | yes | vocabulary / label-boundary (embeddings would NOT help) |
| g055 | operational_domain | `air` -> `multi` (was air) | NO | semantic / paraphrase (embeddings could plausibly help) |
| g056 | operational_domain | `cyber` -> `multi` | NO | semantic / paraphrase (embeddings could plausibly help) |

## Read

On the surface the split looks like an argument *for* embeddings: 9 of 11 residual misses are retrieval-off-target. But that number is an upper bound on a confounded quantity, and the two confounds both point the same way. First, corpus coverage: with ~62 docs, BM25 often has no same-label doc to retrieve, so 'off-target' partly measures a small index, not a lexical-vs-semantic gap -- and adding embeddings over the same 62 docs can't retrieve a relevant doc that isn't there. Second, the off-target transitions are almost entirely the overlapping-definition label pairs already documented in `error_audit.md` (operations/procurement/technology/policy; air/land/multi) -- errors of label boundary, not of which passage was retrieved.

So the honest verdict is unchanged from v2's 'BM25 grounding doesn't justify embeddings', now with a measured ceiling: at most 9 of 54 snippets (17%) are even plausibly retrieval-addressable, and realistically fewer once label-boundary cases are set aside. That's worth **one targeted eval slice** (embeddings retrieval on just these off-target ids, if a first-party embeddings model ever lands) before spending a Voyage AI dependency -- not a retrieval-layer swap. The higher-leverage move for this residual error is label-scheme disambiguation (or the planned `region` field), not a semantic retriever.

*Generated from `evals/gold_predictions.csv`, `evals/gold_rag_predictions.csv`, and the corpus manifest. Re-run with `uv run python src/retrieval_error_analysis.py`.*