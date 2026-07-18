# ADR-014: Region field design — six labels with a `global` catch-all, gold-first scope

**Status:** Accepted
**Date:** 2026-07-17
**Deciders:** San Lee

**Scopes:** the roadmap's planned v3.0.0 breaking change — output becomes
`{category, operational_domain, region}`.

---

## Context

The versioning roadmap has carried the `region` field as the v3.0.0 MAJOR bump since v2:
adding a third output axis breaks the `{category, operational_domain}` contract, so it forces
a fresh gold-labeling pass and resets MINOR/PATCH. Three design questions gate the build, and
all three were put to the owner and answered on 2026-07-17 (they had been surfaced in a prior
session and interrupted; this ADR records the answers so no later session re-litigates them).

The data fact that shapes everything: the real-text corpus is DVIDS, a **US military wire**.
A large share of its stories are CONUS-based with no foreign theater in view — base training,
unit ceremonies, enterprise-wide programs. How those no-anchor stories are labeled determines
the whole region distribution, the same way the operations skew already dominates the
category axis (documented at v2.1.0: the scaled set's category macro-F1 is uninformative for
the same reason).

## Decision

Three decisions, one per design question:

### 1. Label set: six labels, `global` as the single catch-all

`REGIONS = ["indo-pacific", "europe", "middle-east", "africa", "americas", "global"]`

`global` absorbs **both** no-anchor stories and genuinely multi-region stories. This mirrors
how `multi` works on the domain axis: one honest bucket for "no single answer" rather than
two labels (`none` vs `global`) whose boundary the rubric would have to defend on every
CONUS story — exactly where the corpus mass is.

**Boundary rules (rubric v1 — expected to be refined by the gold review, not after it):**

- **Region is the geographic theater of the story's subject activity**, not the actor's
  nationality and not the dateline. A US carrier operating in the South China Sea is
  `indo-pacific`; a Ukraine aid package debated in Washington is `europe`.
- **A concrete location makes an anchor.** Training at a CONUS base, a shipyard delivery in
  Virginia, an exercise in the Mojave — those are `americas`. "No-anchor" means the story
  has no meaningful geography at all (a budget line, a doctrine change, an enterprise-wide
  IT program), not "the geography is the US".
- **Two or more theaters with none dominant → `global`.** Same test as `multi` on the
  domain axis: pick the single region only when the story is *primarily about* it.
- **`americas` is the whole hemisphere**, CONUS included — no separate domestic label. The
  domestic/foreign cut is recoverable downstream (`americas` + no-anchor `global`), not a
  label of its own.

These rules deliberately do **not** touch the existing category/domain enums or their
definitions. If gold review shows region can't be labeled without changing them, that is
beyond v3.0.0's stated break — stop and re-scope (the standing escalation trigger).

### 2. Gold workflow: session pre-labels, owner reviews all 54

The session pre-labels the 54 gold snippets offline (no API); the owner then reviews and
corrects **every** row, not a sample. Chosen over blind owner labeling because the
corrections are the point: each one is a boundary case the rubric above failed to decide,
and they get folded back into the rubric before the classifier prompt is written. The
anchoring risk is accepted — on a 54-row set the review burden of blind labeling buys
little, and the judge-vs-human validation (below) is the independent check.

### 3. Scope: v3.0.0 ships gold-graded region only

v3.0.0 ships two numbers, both on the n=54 gold set: **human-graded region accuracy** and
**judge-vs-human region agreement** on the same rows. The scaled n=300 region eval waits
for v3.1.0 and runs **only if** the judge validates on the region axis — same
earn-the-right sequencing as v2 → v2.1.0, where judge validation on the gold set preceded
scaling. If judge-vs-human region agreement comes in clearly below the ~94% the judge
shows on category/domain, the scaled-region plan dies there and v3.1.0 gets re-scoped.

## Breaking-change / migration notes

- **Output contract:** `classify()` returns `{category, operational_domain, region}`;
  `region` is a **required** key, `CLASSIFY_TOOL` gains a strict-enum `region` property
  (ADR-008 pattern) backed by a `REGIONS` constant beside `CATEGORIES`/`DOMAINS`.
- **Version:** MAJOR bump to `3.0.0`; MINOR and PATCH reset.
- **Gold set:** `data/` gold labels gain a `region` column via the workflow above. Existing
  category/domain gold labels are untouched.
- **Prior results stand, unregraded.** v1/v2 eval artifacts (including the retired RAG and
  routing records, ADR-012/013) remain valid for the axes they measured; nothing is re-run
  against the new schema. New eval output files get new names rather than overwriting
  records.
- **Thresholds after measurement, never before** (house rule): no region accuracy gate
  enters CI until the gold numbers exist.
- **Build order** (one concern per PR): schema + prompt rubric with worked examples →
  gold relabel flow → eval plumbing (`gold_eval`, `eval_confusion`) → owner runs the live
  pass.

## Consequences

- **The region distribution will be `americas`/`global`-heavy.** That is the corpus talking
  (a US wire), not a labeling artifact — the README will have to document region macro
  metrics as skew-limited, exactly as it already does for category on the scaled set.
- **One catch-all trades recall granularity for rubric defensibility.** Analysis that needs
  "truly worldwide" vs "no geography" can't get it from the label alone; accepted, because
  the alternative put the fuzziest boundary on the most common row type.
- **The rubric is falsifiable early.** Pre-label + full review means every rubric failure
  surfaces as a correction before any API spend, and the corrected 54 become both the gold
  answer key and the prompt's worked examples.
- **Judge validation is load-bearing for v3.1.0.** The scaled eval's answer key would again
  be the Opus judge, so the judge must first prove itself against human region labels on
  the 54 — the standing "never grade the judge against itself" rule extends unchanged to
  the new axis.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Seven labels: separate `none` and `global` | Puts the hardest boundary (no-geography vs worldwide) on the dominant CONUS row type; every ambiguous call would land exactly there. The distinction is recoverable downstream and not worth a rubric war. |
| Coarser regions (e.g. domestic/foreign, or merged theaters) | Cheaper to label but analytically thin — theater-level regions are what defense-news analysis actually keys on, and five theaters + catch-all is already near the floor. |
| Owner labels the 54 blind | No anchoring risk, but slower and it defers boundary-case discovery to grading time. The full-review workflow surfaces the same disagreements as corrections, with the rubric still editable. |
| Ship the scaled n=300 region eval inside v3.0.0 | Spends the judge on an axis it hasn't been validated on — the same circularity the scale-eval answer-key rule exists to prevent. Sequencing it behind gold validation is the measured-first house rule applied verbatim. |
