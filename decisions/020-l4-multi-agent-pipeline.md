# ADR-020: L4 built — triage → classify → critic with a one-bounce backward edge

**Status:** Accepted (build; verdict to be amended after San's live runs)
**Date:** 2026-07-25
**Deciders:** San Lee

**Related:** [spec](../docs/specs/l4-multi-agent.md) (Accepted, all forks resolved — this ADR
records the build against it) · [ADR-006](006-autonomy-ladder-portfolio-spine.md) (governance
primitives, here made concrete) · [ADR-013](013-decline-tiered-routing.md) (the constraint:
no premium-tier escalation anywhere) · [ADR-014](014-region-field-design.md) (the named error
cluster the critic targets)

---

## Context

L4 is the ladder's last level: multiple agents coordinating, with the honesty test being a
critic that can bounce a label **backward** for reclassification. The spec resolved the three
design forks (classify blind to triage; bounce cap 1; all-axes critic) and set the honest
hypothesis: the seven gold rows where `region=global` was pulled to a specific theater by
US-actor inference are rubric-checkable misses — critic-shaped by nature.

## Decision

**`src/l4_pipeline.py` implements the spec as written.** The build decisions worth recording
beyond the spec:

- **The critic's charter embeds the live region rubric via `extract_region_block(SYSTEM_PROMPT)`**
  — never retyped, so a prompt-side rubric change moves the critic automatically. A test pins
  the embedding.
- **The fail-closed gate is deterministic code, not prompt hope.** `challenge_violations`
  discards any challenge lacking a named axis, a substantive rubric-rule citation, and a
  stated evidence gap; a discarded challenge never moves a label and never spends the bounce.
  Same pattern family as rung 1's region-rubric freeze and rung 2's `validate_experiment`.
- **The bounce cap is structural.** `process_row` has exactly one re-classify site; the
  second critic review can only produce `fixed` or `contested`, never another bounce. The
  five terminal statuses (`accepted` / `fixed` / `contested` / `fail_closed`, plus sentinel
  salvage inside classify) are each covered by an offline test.
- **Classify's token usage is not surfaced** (its return contract is pinned by the contract
  tests), so the cost axis is **calls-per-row**, recorded per row in the predictions CSV —
  the number ADR-013 taught us to lead with anyway.
- **The scale do-no-harm baseline reuses ADR-019's fresh same-prompt arm**
  (`evals/exemplar_scale_baseline.csv`) — a fair anchor at zero re-spend. Region is not
  scored on scale (no answer key until v3.1.0), stated in the report.
- **Audit trail:** per-run append-only JSONL under `evals/l4/` (gitignored) recording every
  triage note, label, challenge (with cited rule + gap), bounce, and verdict — the append-only
  audit log from the governance primitives, and the replay viewer's third data source.

**Not decided here:** whether the pipeline pays. The verdict — named-cluster accounting,
three-axis McNemar on gold, do-no-harm on scale, challenge rate and measured calls-per-row —
is amended below after San drives the live runs. Expected challenge rate on gold is ~13%
(7/54); a rate far above that is itself a red flag the report must surface.

## Consequences

- **The autonomy ladder is fully built, L1 through L4.** What remains for the ladder story is
  L4's measured verdict and the portfolio cascade.
- ~750 workhorse calls of one-time spend when the runs happen (gold ~120 extra, scale ~630),
  zero premium-tier calls.
- The shipped classifier, its API, and the contract artifact are untouched — verified by an
  identity test on `SYSTEM_PROMPT` and by nothing in the pipeline importing mutation paths.
- Risk stated: the critic reviews 100% of rows, so its false-challenge behavior is the main
  way L4 could *lose* — every needless bounce is two extra calls and a chance to break a
  correct label. The `fail_closed` and `contested` counts in the report exist to make that
  cost visible rather than averaged away.

## Verdict

*To be amended after the live runs.*

## Downstream surfaces

Touched by this change (all in this PR):

- `src/l4_pipeline.py`, `tests/test_l4_pipeline.py` (new); `.gitignore` (audit logs);
  `CHANGELOG.md` `[Unreleased]`; `decisions/README.md` index row;
  `docs/specs/autonomy-ladder.md` L4 row flips to Built.

To sweep when the verdict lands, deliberately NOT in this PR:

- This ADR's Verdict + `evals/l4_eval.txt` and the two prediction CSVs (committed as the
  record); the README ladder narrative; the portfolio cascade (project page L4 section,
  ladder visual, replay wiring for the audit log) — result, not promise; SYS-019 markers if
  numbers are quoted on guarded surfaces.
