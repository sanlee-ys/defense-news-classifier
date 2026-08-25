# ADR-028: `multi` is the domain-neutral catch-all, and the domain key gets a corrections overlay

**Status:** Accepted
**Date:** 2026-08-23
**Deciders:** San Lee

**Related:** `evals/domain_error_audit.md` (the evidence this decision rests on; PR #194) ·
[ADR-014](014-region-field-design.md) (the region `global` catch-all this mirrors) ·
[ADR-024](archive/024-global-boundary-clause-adopted.md) (the "an institution is not a
theater" principle this extends to the domain axis) · the 2026-08-23
`decisions/verdicts.md` row "no clause-targetable cluster"

---

## Context

The 42 `operational_domain` disagreements between the shipped classifier and the frozen
Opus judge key at n=595 were audited by a three-analyst majority protocol
(`evals/domain_error_audit.md`). The audit found no clause-targetable model-error
cluster -- and found that the RULER is the axis's bottleneck: ten-plus rows are majority
judge errors, the key contradicts itself (s370/s371 are one snippet keyed both `land`
and `multi`; s478/s479 conflict with s468; s308 conflicts with s351), and the rubric has
a structural gap. `multi` is defined only as "joint / spans more than one domain", so a
story that spans ZERO domains -- a policy statement, force-structure numbers, a medical
or education programme, an academic talk -- has no legal label, and the key resolves
those rows by no rule at all.

Any future domain-axis measurement against this key at these margins scores key noise,
not the model. The key files themselves are frozen records
(`evals/scale_predictions_v3.csv`, `evals/scale_ext_predictions.csv`) and are never
edited or regenerated.

## Decision

Two rules are ratified, and one mechanism carries them into practice.

**Rule 1 -- `multi` is the domain-neutral catch-all.** `multi` covers both "spans more
than one domain" and "no physical medium at all", exactly as region's `global` covers
both multi-region and no-anchor stories (ADR-014). One principle now holds on both axes.

**Rule 2 -- an institution is not a domain.** A service, command, laboratory, or
program-office name identifies the actor, not a medium: a story whose only domain
evidence is its owning institution has no domain anchor, and under rule 1 it is `multi`.
This is the same principle ADR-024 adopted for region ("a US institution is not an
American theater"), applied to the domain axis. The alternative -- anchoring a
domainless story to its host organization's service -- was considered and rejected: it
is the key's own inconsistent half-behavior, and it would make the two axes reason
differently about the same evidence.

Two existing rubric readings are reaffirmed as they interact with these rules: an
air-and-missile-defense story is `air` even when a ground service owns the unit and the
activity is generic (the rubric already says so; the key applied it inconsistently), and
"joint"/"combined" inside an organization or base NAME is naming, not evidence of two
domains -- the activity's medium decides.

**The mechanism -- a corrections overlay, never an edit.** Key corrections live in
`evals/scale_domain_key_corrections.csv` (`id`, old label, new label, rule, reason).
The frozen key files stay byte-identical. `src/domain_key.py` applies the overlay for
FUTURE experiments, refusing on drift (an overlay row whose old label no longer matches
the key means the key changed under it). Published records and past verdicts are not
re-scored; the overlay is opt-in for new work.

**Adjudication protocol (the gold-set precedent, kept):** corrections are drafted with
evidence, and the owner rules on every flip. No correction enters the overlay without
that ruling. The audit's flagged rows produced 15 proposed flips, 5 explicit
no-change rulings, and 4 rows left open under questions this ADR does not decide.

## What this does not decide

- **The missile-employment boundary** (s248/s126: the key calls one Army
  surface-launched weapon `air` and the other `land`) and **the air-fires-inside-a-
  ground-action tension** (s235 vs the rubric's own worked example). Each needs its own
  ruling; their rows stay uncorrected and are named in the overlay's companion notes.
- **Any change to `SYSTEM_PROMPT`.** Teaching the model rule 1 is a prompt change, and
  prompt changes here are measured, pre-registered experiments (ADR-024 shape). Fixing
  the ruler comes first precisely so that a later measurement means something.
- **Any re-scoring of published numbers.** The 92.9% domain-vs-judge figure and every
  shipped verdict stand as records of measurements against the key as it was.

## Alternatives considered

- **Re-run the judge with an amended rubric.** Rejected for the corrections themselves:
  a model re-grading its own disputed calls is weaker evidence than an owner ruling, and
  it would produce a second full key rather than a small reviewed delta.
- **Edit the frozen key files in place.** Rejected outright: frozen records are never
  regenerated, and five repos' worth of provenance discipline exists to keep it that way.
- **Anchor domainless stories to the owning institution.** Rejected; see rule 2.

## Consequences

- The domain axis becomes measurable again: a future domain experiment grades against
  `domain_key.corrected_key(...)` and scores the model, not key self-disagreement.
- The corrected key changes the baseline domain accuracy for future work (most flips
  move rows the shipped model already predicted `multi` on, so the measured
  model-vs-key gap narrows). That is the correction working, not a free lunch -- the
  published historical numbers do not move.
- The s370/s371 duplicate pair becomes consistent, restoring the property that one
  snippet has one label.

## Downstream surfaces

- `evals/scale_domain_key_corrections.csv` -- the overlay this ADR authorizes.
- `src/domain_key.py` and `tests/test_domain_key.py` -- the only sanctioned way to read
  the corrected key.
- `evals/domain_error_audit.md` -- the evidence record; unchanged by this ADR.
- Future domain-axis experiment harnesses -- must consume the overlay via
  `domain_key.py`, never the raw key, for the domain axis.
