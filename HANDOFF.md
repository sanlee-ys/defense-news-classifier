# HANDOFF — 2026-07-19 — chair: SONNET

_You are a fresh session. Read `CLAUDE.md` (and the repo's process docs) before
acting. Escalate on anomaly, not task type. **Verify PR/file state with
`gh pr list` + `git log --oneline -5` before trusting anything below** — this
file is a point-in-time snapshot and goes stale the moment work lands._

## State

- **`v3.0.0` is shipped and released.** Tag exists locally and on the remote;
  the GitHub release ("The region field") published 2026-07-18. Output contract
  is `{category, operational_domain, region}` ([ADR-014](decisions/014-region-field-design.md)).
  First live run: category 92.6%, domain 92.6%, region 87.0%.
- **The region gate cleared.** Judge-vs-human region agreement on the gold 54
  came in at **100.0%**, above the ~94% benchmark, so the answer-key chain holds
  for a scaled region eval. That gate was the only thing blocking v3.1.0.
- **The 54-row gold set is settled and adversarially audited** on all three axes.
  Category and domain confirmed 108/108; region took two review corrections
  (g003 → `europe`, g024 → `americas`). Ratified conventions live in
  `data/gold/README.md`.
- **Autonomy ladder:** L1 shipped; L2 shipped then retired ([ADR-012](decisions/012-retire-bm25-grounding.md));
  **L3 partly shipped** — rung 1 (prompt-optimization loop) rode the `v2.1.0`
  tag, rung 2 (agent-driven ML loop) is spec'd but unbuilt; **L4 unspec'd**,
  with only the build-vs-adopt call settled (hand-roll).
- **`[Unreleased]` carries real work.** The optimizer could silently destroy the
  `region` axis — `src/optimize.py` predated v3.0.0 and knew nothing about region.
  Fixed in `src/optimize.py` + `src/classify.py` with an *enforced* rubric freeze
  (`region_rubric_violations()`) plus a reported-never-optimized `region_guardrail`
  score. This is on `main` and awaits a version decision.

## Next jobs, in order (each its own branch → PR)

1. **Decide the version for the `[Unreleased]` optimizer fix.** It is a *fix*
   with no contract change, so `v3.0.1` by the repo's own semver rule — but it
   also adds a guardrail score and a hard failure mode (`ProposalError`), which
   is arguably capability. Owner's call; do not guess.
2. **v3.1.0 scaled region eval — unblocked, unscheduled.** n=300 DVIDS snippets
   graded on region by the validated Opus judge, same Wilson-CI reporting as
   v2.1.0. The gate that governed this has cleared; it now needs a decision to
   start, not a measurement.
3. **L3 rung 2 — the ML baseline bake-off** (`docs/specs/ml-baseline-bakeoff.md`,
   spec'd, unbuilt). Train on 300 judge-graded, test on 54 human gold. This is
   what L3 needs to be complete.
4. **kb-agent's side of SYS-004** (separate repo, separate session): its
   `classify_snippet` contract must gain `region`. Still outstanding — this is
   cross-repo debt, not classifier work.

## Escalate if

- Anything wants a threshold that isn't derived from a measured run.
- Anything wants to modify the dormant retired paths (`src/classify_rag.py`,
  `src/route.py`, `src/route_eval.py` and friends) — records, not scaffolding
  (ADR-012/013). They track the shipped schema but stay pinned to the frozen v2
  prediction snapshot.
- Anything wants to edit gold labels: the set is adversarially audited — a
  change needs the same challenge + dual-skeptic bar, and the owner adjudicates
  every flip.
- Anything wants to touch the region rubric inside `SYSTEM_PROMPT`. The freeze
  is mechanically enforced now; a change there is a deliberate owner decision,
  not a refactor.

## Standing cautions

- **The v2 eval outputs are frozen records** (`evals/gold_predictions.csv`,
  `gold_eval.txt`, `gold_confusion*.{md,csv}`, `scale_eval.txt`,
  `route_eval.txt`): never delete, overwrite, or regenerate them. v3 outputs use
  `_v3` names.
- **Batch `custom_id`s** must match `^[a-zA-Z0-9_-]{1,64}$` — `::` 400s; use
  `__` or bare ids (regression-tested).
- **Safety-layer refusals are an expected per-row outcome** on this content
  (s151 precedent). Record-and-continue with a sentinel; never let one row kill
  a batch retrieval (#85 pattern).
- **Measure-first has three precedents** (ADR-012, ADR-013, and the region
  threshold discipline in #94): nothing ships past the eval, and thresholds come
  from measured numbers only. The principle has now declined an escalation twice
  with data.
- `evals/scale_eval`'s answer key **is the Opus judge** — never grade a
  judge-model variant against it; human gold only for quality verdicts.
- **Tags never work from containers** (proxy 403). Tag pushes are owner-only;
  hand over exact commands rather than attempting them.

## Owner-only actions pending

- The version call on the `[Unreleased]` optimizer fix (job 1 above).
- Scheduling v3.1.0, which is unblocked but deliberately unscheduled.
