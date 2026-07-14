# ADR-010: Pin the RAG-grounded path to claude-sonnet-4-6 after the Sonnet-5 workhorse migration

**Status:** Accepted
**Date:** 2026-07-11
**Deciders:** San Lee

---

## Context

The workhorse classifier migrated from `claude-sonnet-4-6` to `claude-sonnet-5`
(`classify.MODEL`; see the Sonnet-5 migration commit). That migration was scoped to the
ungrounded workhorse and its gold eval, and the ungrounded baseline gate passed comfortably —
domain accuracy actually *rose* to 94.4% under Sonnet 5.

But `classify_rag.py`'s grounded path imported the workhorse constant directly
(`from classify import MODEL`), so the migration transitively dragged the BM25-grounded RAG path
onto Sonnet 5 too. Re-running the RAG eval against Sonnet 5 surfaced a real, reproduced (3×)
regression, isolated to the **domain** field:

| Metric (grounded vs. ungrounded, same model) | Sonnet 4.6 | Sonnet 5 |
|---|---|---|
| Domain accuracy — ungrounded baseline | 88.9% | 94.4% |
| Domain accuracy — grounded | 88.9% | 85.2% |
| **Domain accuracy delta (grounding lift)** | **+0.0%** | **−9.3%** |
| Category accuracy delta (grounding lift) | +1.9% | +1.3% |

The RAG gate's `domain_delta_min` floor is −3%. Under Sonnet 5, grounding regressed the domain
field by −9.3%, breaching it. Category grounding was unaffected and still passes.

The finding is **not** that Sonnet 5 is worse. It is that Sonnet 5's *ungrounded* domain accuracy
got good enough (94.4%) that BM25 lexical grounding flipped from signal to noise **for that field
specifically** — the retrieved neighbors now pull a confident, correct ungrounded call sideways
more often than they help (6 right→wrong vs. 1 wrong→right on domain under Sonnet 5). That is a
design question about the RAG *feature* against a stronger baseline, not a defect in the workhorse
migration. It should not block the workhorse from shipping on Sonnet 5.

A dedicated verdict process (a separate model given only the measured numbers) reached the same
conclusion: migrate the workhorse to Sonnet 5, but decouple the RAG path rather than drag it along
or loosen the floor to force green.

## Decision

**Split the single shared model constant into two, and pin the RAG path to `claude-sonnet-4-6`
as a deliberate, transitional split** — not a permanent quiet fork.

- `classify.MODEL = "claude-sonnet-5"` — the **workhorse** constant, unchanged by this ADR.
- `classify_rag.RAG_MODEL = "claude-sonnet-4-6"` — a **new, RAG-owned** constant.
  `classify_rag.py` no longer imports `MODEL` from `classify.py`; `classify_grounded()` defaults
  to `RAG_MODEL`.

**Scope of the pin: the whole RAG path, not just the domain field.** The regression is
domain-specific, so a more surgical fix (keep Sonnet-5 grounding for category, route only the
domain field's grounding to 4.6) is possible. It was rejected here for simplicity: a single
per-call model is far simpler than a per-field model split inside one forced-tool call (which would
mean two calls or a bespoke merge), and category grounding on 4.6 still passes its floors
(+1.9% delta), so nothing is lost by keeping both fields on one model. This ADR is meant to unblock
a clean merge, not to solve RAG-vs-model-scaling generally.

**The RAG eval's baseline moves with it.** The grounding deltas only mean anything when both arms
run on the *same* model. The RAG comparison previously borrowed the workhorse's baseline
predictions (`evals/gold_predictions.csv`), which is now Sonnet 5 — so comparing a 4.6 grounded run
against a Sonnet-5 ungrounded baseline would conflate the model change with the grounding change
(and spuriously fail the delta gate at −5.5%). The RAG eval therefore carries its **own**
`claude-sonnet-4-6` ungrounded baseline, `evals/gold_rag_baseline_predictions.csv` (the
pre-migration `gold_predictions.csv`, frozen). Both `gold_eval_rag.py` and `eval_gate.py` read this
file for the RAG baseline instead of `gold_eval.PREDS_PATH`.

## Consequences

- **The offline eval gate is green again, honestly.** With both RAG arms on 4.6, the committed
  numbers clear every floor: category accuracy 90.7% (floor 85%), category delta +1.9%, **domain
  delta +0.0%** (floor −3%). No floor was loosened.
- **The workhorse ships on Sonnet 5 unblocked.** The baseline gate keeps grading
  `gold_predictions.csv` (Sonnet 5) — domain accuracy 94.4% — untouched by the RAG pin.
- **The RAG baseline is a frozen fixture, not regenerated each live run.** The live evals job
  (`.github/workflows/evals.yml`) deletes only `gold_predictions.csv` and
  `gold_rag_predictions.csv`, never `gold_rag_baseline_predictions.csv`, so a live run compares a
  fresh 4.6 grounded pass against this frozen 4.6 ungrounded snapshot. Acceptable for a transitional
  state where both arms are one model; it becomes stale only if 4.6's ungrounded behavior drifts,
  which the follow-up below will retire anyway.
- **Two model tiers are now in play in one project.** Slightly more to reason about, and the two
  constants must not silently re-couple. A regression test
  (`test_rag_path_is_pinned_to_its_own_model_not_the_workhorse`) asserts the grounded call goes to
  4.6 and `RAG_MODEL != classify.MODEL`, so a future re-coupling fails a fast unit test instead of
  the RAG delta gate.
- **This is transitional debt, recorded as such.** The pin buys time to decide the RAG feature's
  real future against the Sonnet-5 baseline; it is not the end state.

## Re-measurement (2026-07-14): the pin's premise holds under the extended-rubric prompt

The original −9.3 regression was measured with the pre-rubric prompt. After the
extended-rubric prompt change (PR #73) flipped grounding from break-even to clearly positive
on the 4.6 pin, the Sonnet-5 experiment was re-run rather than assumed in either direction
(`scripts/adr010_remeasure.py`; it writes its report under `evals/runs/`, which is
gitignored run-log territory, so the full numbers are inlined here): three independent
grounded Sonnet-5 passes over the gold set against the same-model ungrounded snapshot
(domain 90.7%).

| Pass | Grounded domain | Delta | Domain flips (fix/break) |
|---|---|---|---|
| 1 | 87.0% | −3.7 | 3 / 5 |
| 2 | 87.0% | −3.7 | 2 / 4 |
| 3 | 85.2% | −5.6 | 2 / 5 |

Category stayed flat within noise (90.7 / 88.9 / 90.7 vs 90.7 ungrounded). The rubric
shrank the domain regression (−9.3 → roughly −4) but did not cure it: every pass still
breaches the −3.0 `domain_delta_min` floor and breaks more domain calls than it fixes.
**The pin stands.** The follow-up options below remain the live paths to retiring it.

## Follow-up (the next decision to make — NOT decided here)

The leading candidate, verbatim from the verdict:

> **drop BM25 grounding for the domain field on Sonnet 5 specifically, keep it for category where
> it still passes**

— or, alternatively, **re-tune retrieval (k, score thresholds, corpus filtering) against the new
Sonnet-5 baseline** so grounding stops hurting the now-stronger domain field. Deciding between
those (or dropping domain grounding outright) is its own ADR. When it lands, `RAG_MODEL` and
`evals/gold_rag_baseline_predictions.csv` move together — or disappear, if the domain field stops
being grounded and the whole RAG path returns to the workhorse model.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Drag the RAG path onto Sonnet 5 with the workhorse and loosen `domain_delta_min` to pass | Silently lowers a quality floor to hide a real, measured −9.3% regression — exactly what the gate exists to catch. The floor is a promise; moving it to fit a worse number breaks the promise. |
| Keep the RAG path on Sonnet 5 and just accept the failing gate until the feature is fixed | Blocks the workhorse Sonnet-5 migration (a clean, passing change) behind an unrelated RAG design question. Decoupling lets the good change merge now. |
| Surgical per-field pin: category grounding on Sonnet 5, domain grounding on 4.6 | More faithful to "the regression is domain-only," but forces either two model calls per grounded item or a bespoke per-field merge, against a forced-tool call that returns both fields at once. Category on 4.6 already passes, so the extra complexity buys nothing for this transitional step. Revisit if the follow-up keeps category grounding on Sonnet 5. |
| Reuse the workhorse's Sonnet-5 `gold_predictions.csv` as the RAG baseline and pin only the grounded run to 4.6 | Conflates model + grounding in every delta (4.6 grounded − Sonnet-5 ungrounded = −5.5% domain), so the deltas no longer measure grounding at all, and the gate still fails. A same-model baseline is required for the comparison to be meaningful. |
| Regenerate the 4.6 ungrounded baseline on every live RAG run instead of freezing it | Purer (never stale), but adds a full ungrounded 4.6 pass to the live job for a path that is explicitly transitional and about to be re-decided. The frozen fixture is the right cost/complexity for a stop-gap; the follow-up ADR will make the baseline question moot. |
