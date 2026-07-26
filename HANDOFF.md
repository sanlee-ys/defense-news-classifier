# HANDOFF — 2026-07-25 — chair: FABLE

_You are a fresh session. Read `CLAUDE.md` (and the repo's process docs) before
acting. Escalate on anomaly, not task type. **Verify PR/file state with
`gh pr list` + `git log --oneline -5` before trusting anything below** — this
file is a point-in-time snapshot and goes stale the moment work lands._

## State

- **`v3.1.0` is shipped and released** (2026-07-25, PR #136; tag on the remote,
  GitHub release "The autonomy ladder, built to the top"). It tagged the
  accumulated `[Unreleased]` block: ADR-017 through ADR-020, plus the optimizer
  region fix and the published contract artifact. MINOR, because all of it is
  eval and experiment machinery — `src/api.py` and `SYSTEM_PROMPT` are untouched
  since `v3.0.0`, so the `{category, operational_domain, region}` contract holds.
- **The autonomy ladder is fully built, L1–L4** ([spec](docs/specs/autonomy-ladder.md)).
  Everything above L1 has now been measured, and three of the four measurements
  are negative:

  | Level | State | Verdict |
  |---|---|---|
  | L1 single call | shipped | the production path, still the measured optimum |
  | L2 augmented | built, retired | three retrieval shapes, three failures (below) |
  | L3 rung 1 (prompt loop) | shipped `v2.1.0` | works; the honesty architecture it established is now shared code |
  | L3 rung 2 (ML loop) | built + run | **negative transfer, caught live** ([ADR-018](decisions/018-agent-driven-ml-loop.md)) |
  | L4 multi-agent | built + measured | **hypothesis confirmed, pipeline declined** ([ADR-020](decisions/020-l4-multi-agent-pipeline.md)) |

- **Rung 2 is the repo's Goodhart centerpiece, demonstrated rather than designed
  for.** First live run, six iterations, stopped on plateau: the best-by-B
  iteration scored B 0.699 (+6.0 over baseline) while held-out C fell to 0.545
  (−8.6). Nothing cheated — the agent never sees C. The mechanism is distribution
  shift: A and B are both judge-labeled DVIDS wire text, so keywords mined from
  A's errors generalize there and mislead on C's human-labeled mix. Every guard
  behaved, and C vetoed the loop's own best iteration.
- **L4's split verdict matters in both halves.** The backward edge works: of the
  7 named `global`-cluster rows, the critic challenged and the bounce fixed **6**.
  But the all-axes critic over-challenged at **57.4%** against an expected ~13%
  (the spec's own red-flag rule fired), and did net harm elsewhere — scale domain
  91.3 → 86.7, **p=0.016**, the first statistically significant harm any
  experiment here has produced, at ~4× calls per row. Restraint that lives only
  in a prompt did not hold.
- **The LLM spend is finally priced** ([ADR-017](decisions/017-classical-baseline-bakeoff.md)).
  TF-IDF + logistic regression on the 300 judge-graded snippets, scored once
  against human gold: category 72.2% vs the LLM's 92.6% (p=0.013), domain 66.7%
  vs 92.6% (p=0.0005). The foundational spend is justified with a number instead
  of an assumption.
- **The retrieval question is closed in three shapes.** Neighbor documents
  harmful ([ADR-012](decisions/012-retire-bm25-grounding.md)), mined keyword
  features harmful off-distribution ([ADR-018](decisions/018-agent-driven-ml-loop.md)),
  labeled exemplars inert ([ADR-019](decisions/019-knn-exemplar-fewshot.md):
  91.0% vs 90.0%, p=0.70). **Do not propose retrieval augmentation again** absent
  a materially bigger human-labeled ruler.
- **The shipped classifier is unchanged through all of it** — single model,
  single call, same prompt. It remains the measured optimum of everything tried
  against it, which is the repo's actual headline.
- **The 54-row gold set is settled and adversarially audited** on all three axes.
  Category and domain confirmed 108/108; region took two review corrections
  (g003 → `europe`, g024 → `americas`). Ratified conventions live in
  `data/gold/README.md`.
- **The SYS-004 seam is closed on both sides.** An earlier snapshot listed
  kb-agent's half as outstanding; it landed in kb-agent PR #52 (2026-07-19), and
  this repo publishes the generated `contracts/classify-response.schema.json`
  with CI failing on a stale artifact.
- **Roadmap renumber:** the scaled region eval held the `v3.1.0` slot and now
  sits at **`v3.2.0`** (see the CLAUDE.md versioning table). Surfaces that named
  the old slot were swept to version-free phrasing, so the reference cannot rot
  at the next move. ADRs were deliberately left as written — correct on their
  date.
- **Every downstream surface ADR-017 named is now swept.** The last one was the
  SYS-007 AI-skill map (architecture PR #72, 2026-07-26), which gained a sixth
  cluster, **Baselines & build-vs-buy** — framed as "fit the classical model you
  are not going to ship, to price the one you are," and marked *measured once,
  not yet a practice*. The same PR credited the finished ladder to the Agents &
  orchestration cluster and the held-out veto to the Evals keystone. Note for
  whoever bumps a version next: that PR also had to fix a stale `v3.0.0` version
  claim in `architecture/program/README.md`, which is a **guarded marker** and had
  been failing that repo's CI since our tag. A version bump here reddens the
  architecture repo until its prose catches up.
- **The bake-off is published** (portfolio PR #132, 2026-07-26). The project page
  now carries a "Why an LLM at all" section with the 72.2%/66.7% vs 92.6%
  comparison, both p-values, the failure shape, and the two disclosed handicaps.
  This was job 1 in the previous revision of this file and is done; the numbers
  there deliberately carry no `data-metric` markers, because a frozen paired
  comparison must not drift with the live artifact.
- **In flight, not yours unless it stalls:** PR #137 (`pin-predictions-to-prompt`)
  fingerprints the gold predictions snapshot against the prompt that produced it,
  closing a gap where a prompt edit plus a version bump could re-stamp stale
  numbers with a new version while CI stayed green. It touches
  `evals/metrics.json` and `tests/test_metrics_artifact.py`, both of which the
  v3.1.0 sweep also moved — expect a rebase, not a conflict of substance.

## Next jobs, in order (each its own branch → PR)

1. **`v3.2.0` scaled region eval — unblocked, unscheduled.** n=300 DVIDS snippets
   graded on region by the validated Opus judge (100.0% judge-vs-human on the
   gold 54 cleared the gate), same Wilson-CI reporting as v2.1.0. This needs a
   decision to start, not a measurement. Owner's call.
2. **The named `global` cluster still wants a prompt clause.** All 7 misses are
   gold-`global` rows the model pulls to a specific region by inferring a theater
   from the US *actor*. L4 established the cluster is genuinely fixable by
   evidence checking (it fixed 6 of 7) — but at 4× cost through a pipeline that
   was declined. A prompt clause is the cheap alternative to test, measure-first
   like PR #79.
3. **Option, explicitly NOT a commitment: a structurally narrowed critic.** L4's
   failure was a charter that lived only in the prompt. A critic code-gated to
   fire *only* where triage reports `none stated`, on region alone, is a
   different experiment with a different cost profile — and it is a **new
   experiment needing its own spec and ADR**, not a patch to ADR-020. Do not
   start it as cleanup.

## Escalate if

- Anything wants a threshold that isn't derived from a measured run.
- Anything wants to modify the dormant retired paths (`src/classify_rag.py`,
  `src/route.py`, `src/route_eval.py`, and now `src/l4_pipeline.py` and
  `src/exemplar_eval.py`) — records, not scaffolding (ADR-012/013/019/020). They
  track the shipped schema but stay pinned to their frozen prediction snapshots.
- Anything wants to edit gold labels: the set is adversarially audited — a
  change needs the same challenge + dual-skeptic bar, and the owner adjudicates
  every flip.
- Anything wants to touch the region rubric inside `SYSTEM_PROMPT`. The freeze
  is mechanically enforced now; a change there is a deliberate owner decision,
  not a refactor. The L4 critic extracts its rubric from the live prompt rather
  than restating it, and a test pins that — do not "simplify" it to a copy.
- Anything proposes retrieval augmentation, a premium-tier escalation, or a
  second model as an actor. All three have been measured and declined; a fourth
  attempt needs a new argument, not a new implementation.

## Standing cautions

- **The v2 eval outputs are frozen records** (`evals/gold_predictions.csv`,
  `gold_eval.txt`, `gold_confusion*.{md,csv}`, `scale_eval.txt`,
  `route_eval.txt`): never delete, overwrite, or regenerate them. v3 outputs use
  `_v3` names. The same rule now covers `baseline_eval.txt`, `exemplar_eval.txt`,
  `l4_eval.txt` and their prediction CSVs.
- **Published numbers are generated, not typed.** `evals/metrics.json` is the
  artifact outward surfaces assert against; `gen_metrics_artifact.py` reads the
  version from `pyproject.toml`, so a version bump turns CI red until you
  regenerate the artifact *and* update the pinned literal in
  `tests/test_metrics_artifact.py`. That is the guard working, not a bug.
- **Run logs are gitignored by policy** (`evals/optimize/`, `evals/ml_loop/`,
  `evals/l4/`). The verdict in the ADR is the durable record; if a run needs to
  be published, embed it deliberately rather than un-ignoring the directory.
- **Batch `custom_id`s** must match `^[a-zA-Z0-9_-]{1,64}$` — `::` 400s; use
  `__` or bare ids (regression-tested).
- **Safety-layer refusals are an expected per-row outcome** on this content
  (s151 precedent). Record-and-continue with a sentinel; never let one row kill
  a batch retrieval (#85 pattern).
- **Measure-first is now five-for-five** (ADR-012, ADR-013, ADR-018, ADR-019,
  ADR-020): nothing ships past the eval, and thresholds come from measured
  numbers only. Four of those five declined an escalation with data.
- `evals/scale_eval`'s answer key **is the Opus judge** — never grade a
  judge-model variant against it; human gold only for quality verdicts.
- **Tags never work from containers** (proxy 403). Tag pushes are owner-only;
  hand over exact commands rather than attempting them.
- **Live runs are owner-driven.** Anything that spends tokens against the API —
  gold passes, scale passes, the L3 loops, the L4 pipeline — gets handed to San
  as an exact command, not launched from a session.

## Owner-only actions pending

- Scheduling the `v3.2.0` scaled region eval, which is unblocked but deliberately
  unscheduled (job 1).
- Deciding whether the narrowed-critic experiment (job 3) is worth a spec at all.
  The honest default is no. The ladder is complete, measured, and now fully
  published — there is no documentation debt left to trade against, so this
  would be new build work on a rung that already returned its answer.
