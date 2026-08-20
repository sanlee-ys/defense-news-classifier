# ADR-019: kNN-exemplar few-shot — the last untried retrieval shape, measured

**Status:** Accepted — verdict recorded 2026-07-25: **null result, exemplars declined**
**Date:** 2026-07-25
**Deciders:** San Lee

**Related:** [ADR-012](012-retire-bm25-grounding.md) (neighbor-docs grounding, retired) ·
[ADR-018](018-agent-driven-ml-loop.md) (whose live-run amendment recorded lexical keyword
features failing to transfer) · [ADR-017](017-classical-baseline-bakeoff.md) (supplies the
judge-labeled pool loader and the McNemar helper)

---

## Context

Retrieval augmentation has been measured twice here and lost twice, in different shapes:
unlabeled BM25 neighbor *documents* as context (ADR-012: 0 domain calls fixed, 4 broken)
and lexically-mined keyword *features* (ADR-018 amendment: +6.0 on the judge-labeled
validation split, −8.6 on human gold). One shape remains untried: retrieve the k most
similar **labeled examples** and inject them as few-shot exemplars. Mechanically distinct
in the way that matters — exemplars carry labels, so they teach *boundary placement*
rather than adding topical context — but they ride the same BM25 similarity signal that
misled twice.

**The stated prior is therefore negative.** This experiment exists because the shape is
genuinely untried and the repo's thesis is to measure rather than assume — in either
direction. A third negative result completes the retrieval-augmentation series; a win
would be the first augmentation to survive a fair baseline in this repo.

## Decision

**Build the measurement harness (`src/exemplar_eval.py`), run it once, and record the
verdict here — whichever way it falls.** Design constraints:

- **Exemplar pool: the 300 judge-labeled scale rows**, loaded via `baseline_ml.load_train`
  (judge labels only — its never-`pred_*` guarantee is already test-pinned). k=3,
  mirroring the retired RAG layer's k deliberately, so the comparison across the series
  reads clean.
- **Category and domain only.** The pool has no region labels, and the only region-labeled
  data (the gold set) cannot serve as both exemplar pool and eval set without a leak.
  Region is instead a **guardrail** on the gold arm: exemplars must not degrade it.
- **Primary measurement: paired exact McNemar on the scale set (n=300) vs judge labels**,
  exemplar retrieval leave-one-out. The baseline arm is **re-run fresh** under the current
  prompt and model — the stored `scale_predictions.csv` workhorse column predates the v3
  prompt, and comparing a new-prompt arm against an old-prompt baseline is the exact
  unfair-baseline bug PR #81 had to fix before ADR-012 could be trusted.
- **Secondary, directional: the gold 54**, exemplar arm only, against the stored
  `gold_predictions_v3.csv` baseline (same prompt/model — a fair anchor at zero cost).
- **Mechanism: exemplar block appended to `SYSTEM_PROMPT`**, call made through
  `classify()` via rung 1's `_classify_retry`, so the two arms differ by exactly the
  appended block and inherit strict-enum validation and per-axis sentinel salvage. The
  block states that region labels are intentionally absent, so the region rubric above it
  stays authoritative.
- **Cost, estimated up front:** ~654 workhorse calls (300 + 300 + 54); exemplar-arm
  prompts carry ~3×400-char snippets extra. Run resume is per-row (append + skip-scored),
  so an interrupted run loses at most one call.
- San drives the live runs; the harness and report are offline-testable without a key.

## Consequences

- The retrieval-augmentation question gets a complete, three-shape measured answer
  (context docs / mined features / labeled exemplars) instead of a two-shape one with a
  shrug at the end.
- ~654 workhorse calls of one-time spend, accepted by San 2026-07-25 ("we have time").
- The gold arm gives the writeup a human-labels read, but at n=54 it is directional only
  (per §8 of the bake-off spec's honest-reporting rules); the scale-set McNemar is the
  citable number and it measures agreement with the *judge*, stated as such.
- If the verdict is negative, the harness stays dormant with its tests as the
  reproducible record — the ADR-013 pattern.

## Verdict (2026-07-25)

San ran all three arms the same day (`evals/exemplar_eval.txt` + the three arm CSVs are
the committed record). **A clean null: labeled exemplars neither help nor hurt, and they
are declined.**

| Measurement | Baseline | Exemplar | Paired (fixed/broke, McNemar p) |
|---|---|---|---|
| scale category (n=300, vs judge) | 90.0% | 91.0% | 15 / 12, p=0.70 |
| scale domain (n=300, vs judge) | 91.3% | 91.0% | 10 / 11, p=1.00 |
| gold category (n=54, directional) | 92.6% | 88.9% | 2 / 4, p=0.69 |
| gold domain (n=54, directional) | 92.6% | 90.7% | 0 / 1, p=1.00 |
| gold region (guardrail) | 87.0% | 87.0% | — pass, zero movement |

Reading it honestly: every delta is inside its interval; the discordant pairs are
near-symmetric (15/12, 10/11) — exemplars *churn* individual calls without moving the
totals. The gold direction is mildly negative but at n=54 that is noise, not a finding.
The region guardrail passed exactly (47/47 both arms), so the withheld-labels disclaimer
did its job.

This completes the three-shape retrieval-augmentation series with three distinct
outcomes, which is the real product of the series:

1. **Neighbor documents** (ADR-012) — actively harmful (0 fixed / 4 broken on domain).
2. **Lexically-mined features** (ADR-018 amendment) — harmful *off-distribution*
   (B +6.0, C −8.6).
3. **Labeled exemplars** (this ADR) — **inert**: no measurable effect at roughly double
   the prompt size and the retrieval machinery's complexity.

The 92%+ single-model, single-call classifier remains the measured optimum of everything
tried against it — now including the last retrieval shape. The harness stays dormant with
its tests as the reproducible record (the ADR-013 pattern). Exemplar retrieval should not
be revisited unless the eval ruler changes materially (e.g. a much larger human-labeled
set) — a null at n=300 paired is a stronger "no" than ADR-012's n=54 ever was.

## Downstream surfaces

Touched by this change (all in this PR):

- `src/exemplar_eval.py`, `tests/test_exemplar_eval.py` — harness + guards (new).
- `CHANGELOG.md` `[Unreleased]`, `decisions/README.md` index row.

Swept with the verdict (same day, verdict PR): this ADR's Verdict section;
`evals/exemplar_eval.txt` + the three arm CSVs committed as the record;
`README.md` three-shape series paragraph; `docs/specs/autonomy-ladder.md` §6 L2 addendum;
`CHANGELOG.md` + `decisions/README.md` rows updated.

Still deliberately open:

- The eventual portfolio L2 writeup — the "every retrieval shape tried and measured"
  framing; SYS-019 markers if any number is quoted on a guarded surface.
