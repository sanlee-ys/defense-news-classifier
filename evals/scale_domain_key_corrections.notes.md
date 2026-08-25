# Adjudication notes for the domain-key corrections (ADR-028)

The overlay (`scale_domain_key_corrections.csv`) carries the 15 corrected rows with
per-row reasons. This file records the rows that were examined and deliberately NOT
corrected, so the next auditor knows they were ruled on rather than missed. Every row
here was flagged by `domain_error_audit.md`; the owner ruled per row (ADR-028 protocol).

## Examined, no change (5)

- **s496** (key `land`): an ADA battery performing parachute jumps. The activity is
  airborne-infantry training with its own character, not air-and-missile-defense
  activity, so the amd-is-air reading does not attach; the jump training itself is a
  ground-force skill. Contrast s468, where the activity is generic and the AMD identity
  is the whole story.
- **s438** (key `multi`): a change-of-directorship at Joint Interagency Task Force
  West. A leadership ceremony has no activity medium; under rule 1 the label follows
  the subject organization's enduring character, which is genuinely interagency and
  multi-domain. The key's label survives under the ratified rule, though not under the
  reasoning ("Joint" in a name) the audit suspected it used.
- **s187** (key `multi`): Marines conducting fixed-site security training aboard a
  landship at an Army port. The activity straddles sea and land and neither ratified
  rule decides it; underdetermined, key left as-is.
- **s301** (key `multi`): shipboard VBSS training with two helicopter squadrons. Naval
  aviation inside a maritime operation is arguably organic `sea`; also arguably a
  genuine air-sea span. No ratified rule decides it; key left as-is.
- **s308** (key `multi`): STEM-outreach programme by Air Mobility Command. Now
  rule-backed: an education programme has no medium (rule 1) and the command name is
  not a domain (rule 2). The earlier conflict with s351 is resolved by correcting s351.

## Open under questions ADR-028 does not decide (4)

- **s248, s126** (missile-by-employment): the key calls one Army surface-launched
  weapon `air` and the other `land`. Needs its own ruling before either row can be
  corrected or a clause graded.
- **s235, s230** (air fires inside a ground action): s235 sits in tension with the
  rubric's own worked example; s230 names no aircraft at all. Needs its own ruling.
