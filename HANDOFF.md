# HANDOFF — 2026-07-18 (refresh) — chair: FABLE

_You are a fresh session. Read `CLAUDE.md` (and the repo's process docs) before
acting. Escalate on anomaly, not task type. **Verify PR/file state with
`gh pr list` + `git log --oneline -5` before trusting anything below** — the
owner was mid-live-run when this was written._

## State

- The v3.0.0 build order ([ADR-014](decisions/014-region-field-design.md)) is
  **fully shipped on `main`**: design (#88) → schema + prompt rubric (#90) →
  gold region labels (#91, #92) → eval plumbing + ratified-convention prompt
  amendments (#94). Output contract is `{category, operational_domain, region}`.
- The **54-row gold set is settled and adversarially audited** on all three
  axes (full source-article verification): category and domain confirmed
  108/108 — the owner's hand labels and the published 94.4%/92.6% numbers
  stand untouched; region took two review corrections (g003 → `europe`,
  g024 → `americas`). Ratified labeling conventions live in
  `data/gold/README.md` (snippet-decidable/article-confirmable; Afghanistan +
  Central Asia → middle-east; Hawaii → indo-pacific; Mediterranean → europe).
- **The owner is running the v3 live pass** (~108 calls: workhorse + judge over
  the gold 54). Outputs land as NEW files — `evals/gold_predictions_v3.csv`,
  `evals/gold_eval_v3.txt` — and are committed only via a deliberate human PR.
  If they're on `main` when you read this, the pass is done; read
  `gold_eval_v3.txt` before doing anything else.
- Version files still say 2.2.0 — the bump to 3.0.0 rides the release sweep,
  not any feature PR. ADR-006 gained L3/L4 governance amendments mid-cycle
  (#93, separate session) — unrelated to the region work.

## Next jobs, in order (each its own branch → PR)

1. **Thresholds PR — only after the live numbers exist** (measure-first, house
   rule): region floors in `evals/thresholds.toml` from the measured run, and
   re-point `eval_gate`'s default + the offline gate at the v3 snapshot once
   it's committed. Never write an aspirational floor.
2. **Release sweep (Sonnet-tier mechanical):** CHANGELOG entry, README numbers
   from `gold_eval_v3.txt`, version 3.0.0 (MINOR/PATCH reset), roadmap row
   flipped to shipped. Then the owner pushes the `v3.0.0` tag (tags never work
   from containers — proxy 403; hand over exact commands).
3. **v3.1.0 scaled region eval — gated, not scheduled:** proceed only if
   judge-vs-human REGION agreement on the 54 validates (benchmark: the ~94%
   the judge shows on category/domain). Below that, the plan dies — surface
   it, don't patch around it.
4. **kb-agent's side of SYS-004** (separate repo, separate session): its
   `classify_snippet` contract must gain `region` before it re-pins.

## Escalate if

- Judge-vs-human region agreement comes in clearly below the ~94% benchmark —
  the v3.1.0 scaled plan dies; that's an owner decision, not a retry.
- Anything wants a region threshold before the live numbers exist.
- Anything wants to modify the dormant retired paths (`src/classify_rag.py`,
  `src/route.py`, `src/route_eval.py` and friends) — records, not scaffolding
  (ADR-012/013). They deliberately track the shipped schema but stay pinned to
  the frozen v2 prediction snapshot.
- Anything wants to edit gold labels: the set is adversarially audited — a
  change needs the same challenge + dual-skeptic bar, and the owner
  adjudicates every flip.

## Standing cautions

- **The v2 eval outputs are frozen records** (`evals/gold_predictions.csv`,
  `gold_eval.txt`, `gold_confusion*.{md,csv}`, `scale_eval.txt`,
  `route_eval.txt`): never delete, overwrite, or regenerate them. All v3
  outputs use `_v3` names. `eval_gate.py` defaults to the v2 snapshot; the CI
  live leg grades its fresh v3 run via `--preds` against the six measured v2
  floors (owner's call 2026-07-18: keep that leg live through the transition).
- **Batch `custom_id`s** must match `^[a-zA-Z0-9_-]{1,64}$` — `::` 400s; use
  `__` or bare ids (regression-tested).
- **Safety-layer refusals are an expected per-row outcome** on this content
  (s151 precedent). Record-and-continue with a sentinel; never let one row
  kill a batch retrieval (#85 pattern).
- **Measure-first has three precedents now** (ADR-012, ADR-013, and the
  region threshold discipline in #94): nothing ships past the eval, and
  thresholds come from measured numbers only.
- `evals/scale_eval` answer key **is the Opus judge** — never grade a
  judge-model variant against it; human gold only for quality verdicts. The
  same rule extends to region: the judge must validate against the human 54
  before it grades anything at scale.

## Owner-only actions pending

- Finish the live pass; review `gold_eval_v3.txt` (region accuracy + the
  judge-region gate number) and `eval_confusion.py`'s per-cell breakdown.
- Commit the v3 snapshot via PR when satisfied.
- The eventual `v3.0.0` tag push, after the release sweep.
