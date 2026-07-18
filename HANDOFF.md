# HANDOFF — 2026-07-18 — chair: FABLE

_You are a fresh session. Read `CLAUDE.md` (and the repo's process docs) before
acting. Escalate on anomaly, not task type._

## State

- `main` @ `8975b83` — **v2.2.0 released and tagged** (tag `v2.2.0` is on the remote).
  The v2.2.0 milestone shipped as a measured negative result: tiered routing was built
  (#84), hardened after a live safety-layer refusal (#85), measured (0 rows moved,
  ~1.97x cost), and declined ([ADR-013](decisions/013-decline-tiered-routing.md), #86).
  CHANGELOG, README, roadmap, and version (2.2.0) are all swept and consistent.
- Working branch convention this cycle: `claude/classifier-app-alternatives-2an4ww`,
  PR → squash-merge to `main` once CI is green (offline-gate + test + CodeQL), branch
  auto-deletes on merge.
- No open PRs, no uncommitted work, all 293 tests green at release.
- The container has **no API key** — all paid/live steps run on the owner's machine
  (Windows / PyCharm / PowerShell: no `&&`, use separate lines; `.env` is local-only).

## Your job this session

**Line up v3.0.0 — the `region` field** (the roadmap's planned breaking change:
output becomes `{category, operational_domain, region}`). The owner said "line up
3.0.0"; the taxonomy questions below were posed but **not yet answered** — getting
those answers is step 1, not optional.

1. Ask the owner these three design questions (they were surfaced and interrupted;
   re-ask, don't assume):
   - **Label set** — proposed: `indo-pacific`, `europe`, `middle-east`, `africa`,
     `americas`, + `global` as the single catch-all for no-anchor and multi-region
     stories (mirrors `multi` on the domain axis). Alternatives: separate
     `none`/`global` (7 labels), or coarser regions. Key data fact: DVIDS is a US
     wire, so CONUS no-anchor stories dominate — how they're labeled shapes the
     whole distribution.
   - **Gold labeling workflow** — recommended: session pre-labels the 54 gold
     snippets offline, owner reviews/corrects each (fast, corrections reveal the
     rubric's boundary cases); alternative: owner labels blind (no anchoring).
   - **Scope** — recommended: v3.0.0 ships gold-graded region only (n=54 human
     accuracy + judge-vs-human region validation on the same 54); the scaled n=300
     region eval waits for v3.1.0 and only if the judge validates on region.
     Mirrors the v2 → v2.1.0 earn-the-right sequencing.
2. Record the answers in **ADR-014** (region field design: label set, boundary
   rules, migration/breaking-change notes) before touching code.
3. Then build in small steps (one concern per PR): schema (`CLASSIFY_TOOL` strict
   enum + `REGIONS` constant) + prompt rubric with worked examples → gold relabel
   flow → eval plumbing (`gold_eval`, `eval_confusion`, thresholds **after**
   measurement, never before) → owner runs the live pass.

## Queued for other tiers

- **Sonnet:** after the v3.0.0 design lands, the mechanical sweeps (tests for the
  new schema path, README numbers once measured, CHANGELOG entry) are prescribed
  work.
- **Owner-decision gate, any tier:** scaled region eval (v3.1.0) is contingent on
  judge-vs-human region agreement on the 54 — do not schedule it before that number
  exists.

## Escalate if

- The region labels force a change to the *existing* category/domain enums or their
  definitions — that's beyond v3.0.0's stated break; stop and ask.
- Judge-vs-human region agreement on the gold 54 comes in clearly below the ~94%
  the judge shows on category/domain — the scaled-region plan dies; surface it.
- Anything wants to modify the dormant retired paths (`src/classify_rag.py`,
  `src/route.py` and friends) — they are records, not scaffolding (ADR-012/013).

## Standing cautions

- **Batch `custom_id`s** must match `^[a-zA-Z0-9_-]{1,64}$` — `::` separators 400
  (fixed once, regression-tested; keep new batch code to `__` or bare ids).
- **Safety-layer refusals are an expected per-row outcome** in bulk runs on this
  content (s151 precedent: a chem-bio *defense* story refused after a mere schema
  change). Record-and-continue with a sentinel; never let one row kill a batch
  retrieval (#85 pattern in `route_eval.py`).
- **Tag pushes are blocked from the container** (proxy 403) — branch pushes and PRs
  work; tags are always the owner's step, hand over exact commands.
- **Measure-first is the house rule with two precedents** (ADR-012, ADR-013): no
  feature enters the shipped path without beating the eval; thresholds are set from
  measured numbers, never aspirationally.
- `evals/scale_eval` answer key **is the Opus judge** — never grade a judge-model
  variant against it (circularity); human gold only for quality verdicts.

## Owner-only actions pending

- Answer the three v3.0.0 design questions (above).
- Hand-label / correct the n=54 gold `region` column when the workflow is agreed.
- All live API runs (classifier + judge passes) and the eventual `v3.0.0` tag push.
