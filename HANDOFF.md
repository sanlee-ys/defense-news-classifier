# HANDOFF — 2026-08-02 — chair: FABLE

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
- **`v3.1.0` is still the released tag; everything below it landed after and is
  unreleased.** Sixteen PRs have merged since the tag (#137–#154, less #139 —
  closed, superseded by #142 — and #147, still open), three of them refreshes to
  this file. The rest are runtime
  hardening, two provenance pins, three new offline layers, two CI lanes, and the
  `v3.2.0` harness. None of it moved a published number: all eight gated floors
  are byte-identical (category 0.926, category-F1 0.911, domain 0.926, domain-F1
  0.933, judge-cat 0.926, judge-dom 0.981, region 0.870, judge-region 1.000).
- **~~⚠ The `[Unreleased]` CHANGELOG block does not cover that work~~ — CLOSED in the
  `v3.2.0` release.** The `[3.2.0]` entry now records the ADR-021 taxonomy, the
  paired-compare layer and both CI lanes alongside the three that were already
  there; the judgement call was made as part of writing the release. The gap as it
  stood: `[Unreleased]` recorded exactly three things: the
  browser baseline export (#148) under Added, and the two provenance pins (#137,
  #142) under Fixed. ADR-021 (#151, #152), the paired-compare layer (#149), the
  Docker CI lane (#146), and the two review-trigger changes (#144, #150) had merged
  **without a CHANGELOG entry**, so step 7 of
  [the v3.2.0 runbook](docs/v3.2.0-release-runbook.md) ("`[Unreleased]` already
  holds shipped work that rides the v3.2.0 tag") was false as written. The CI lanes
  were included rather than dropped, on this repo's own v2.1.0 precedent — the
  `Jenkinsfile` and the evals-CI gate both earned entries there.
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
  against it, which is the repo's actual headline. Stated precisely as of today:
  `SYSTEM_PROMPT` still hashes to `a59689e8…` (the fingerprint recorded in
  `evals/gold_predictions_v3.provenance.json`, mechanically enforced — see the
  provenance pins below), `src/api.py` is untouched since `v3.0.0`, and the
  `{category, operational_domain, region}` contract holds. The one post-tag change
  to `src/classify.py` is ADR-021's truncation guard, which makes a cut-off
  response raise instead of scoring — a new refusal path, not a new answer.
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
  architecture repo until its prose catches up. **That ripple is now inventoried
  end to end** — every downstream surface across four repos, in dependency order,
  with the out-of-order costs named — in
  [docs/v3.2.0-release-runbook.md](docs/v3.2.0-release-runbook.md) (#153). Do not
  restate its steps here; it is the single source for release mechanics, and a
  second copy is exactly the drift this file keeps having to fix.
- **The bake-off is published** (portfolio PR #132, 2026-07-26). The project page
  now carries a "Why an LLM at all" section with the 72.2%/66.7% vs 92.6%
  comparison, both p-values, the failure shape, and the two disclosed handicaps.
  This was job 1 in the previous revision of this file and is done; the numbers
  there deliberately carry no `data-metric` markers, because a frozen paired
  comparison must not drift with the live artifact.

### Landed since the `v3.1.0` tag

- **A stale prompt can no longer be published *or* graded** (#137, #142 — the two
  provenance pins; both merged, both in `[Unreleased]`). A live run now records
  `prompt_sha256` plus both model ids to a sidecar
  (`evals/gold_predictions_v3.provenance.json`), and **both** consumers refuse on
  divergence: `scripts/gen_metrics_artifact.py` will not publish, and
  `src/eval_gate.py` will not print its floors. The second one is the subtler
  half — the gate's claim is "the *shipped* numbers still clear the bar", and
  before #142 a prompt edit plus a skipped gold re-run left it printing eight
  green floors for a classifier that was not the one shipped. Practical
  consequence for you: **editing `SYSTEM_PROMPT` now hard-reds CI** until either a
  paid gold re-run or a named, reasoned waiver. That is the guard working.
- **One API error taxonomy, and a truncated response is never scored**
  ([ADR-021](decisions/021-api-error-taxonomy-and-incomplete-responses.md), #151;
  extended by #152). Five modules had grown the same wrong `except
  (InternalServerError, RateLimitError)` tuple — **too narrow** (`OverloadedError`
  / 529 is a *sibling* of `InternalServerError`, not a subclass, so the most common
  transient failure on a long unattended run aborted it) and **too wide** (a spend
  cap arriving as a 429 was slept on and retried, which cannot succeed).
  `src/api_retry.py` is now the single taxonomy: the non-retryable pattern
  (quota/billing/credit/auth) is tested first and wins over exception type, then
  deterministic types fail fast, then transient ones retry; an unrecognized error
  fails fast, because retrying an unknown failure triples spend on a bug. Backoff
  is byte-for-byte the old policy. Separately, `classify()` now asserts the call
  *finished* — with forced tool use and `max_tokens=256`, a truncated `ToolUseBlock`
  can still **validate**, because the axes that survived are individually legal
  labels, and that partial answer was being scored right-or-wrong against gold.
  #152 then wired the three live-call modules #151 had missed
  (`l4_pipeline`'s triage/critic calls, `ml_loop`'s raw `messages.create`,
  `gold_eval_haiku`'s whole batch path). **Not verified live** — the whole taxonomy
  is exercised offline against constructed SDK errors, never a real 529.
- **A paired-comparison layer, with harness health reported separately** (#149,
  `src/paired_compare.py`). Every A/B here — ADR-012, ADR-013, ADR-017, ADR-019 —
  re-derived the same plumbing by hand, and the part that kept getting
  re-litigated was the bookkeeping, because a comparison that quietly drops rows
  reports a lift that never happened. Now: a deterministic group key that fails
  loud rather than merging two inputs into one "pair"; metrics computed only over
  pairs where **both** arms scored (a missing observation is never imputed and
  never zero, or an arm that crashes on the hard rows looks better the more it
  crashes); nothing eligible returns `None`, never `0.0`. Non-participating rows
  come back as diagnostics under their own heading — "is this comparison
  trustworthy" is a different question from "what did it find". It is additive and
  reads already-materialized CSVs, so it cannot perturb a published number; it
  independently reproduces the ADR-017 bake-off result as a test.
- **The ADR-017 classical baseline runs in a browser now** (#148, `web/`,
  `scripts/export_baseline.py`). Phase 1 is artifacts only — no page is built, and
  nothing is re-measured; 72.2% / 66.7% stay the frozen record in
  `evals/baseline_eval.txt`. The risk it carries is a hand-ported sklearn
  preprocessing chain, which fails *quietly* by returning a plausible label, so it
  is gated: `scripts/parity_check.mjs` (bare `node`, no npm) checks 354 rows × 2
  axes against sklearn's own scores at 1e-6 and asserts **every** vocabulary term
  is exercised — the first draft was gold-rows-only and could be shown not to catch
  a perturbed coefficient.
- **Two CI lanes changed.** #146 added `docker.yml`: the serving image is now built
  and a container smoke-tested on `/health` before merge, path-filtered to
  `Dockerfile`, `requirements-api.txt`, `src/api.py`, `src/classify.py` — before
  it, a base-image bump could go fully green without the shipped artifact ever
  being built. The PR deliberately broke the image on a second commit to prove the
  job goes red, then reverted. #144 and #150 walked the advisory review lane back
  to on-demand ([ADR-016](decisions/016-claude-code-action-pr-review.md) Amendment
  1): #144 dropped the automatic `pull_request: [opened]` pass, and #150 fixed the
  gap that made the remaining gate a fiction — supplying a `prompt:` puts the
  action in **agent mode**, which bypasses `@claude` mention checking entirely, so
  the effective trigger was *any* OWNER comment (`lgtm`, `merging`) each spending a
  billed review. It now requires the phrase explicitly.
- **`CLAUDE.md` was cut 17.5KB → 11.9KB** (#145), dropping rules that constrained
  without informing and replacing the shipped-version roadmap table with a pointer
  to `CHANGELOG.md` + tags. Relevant to how you work here: the small-steps rule is
  no longer unconditional — checkpoint where a wrong turn is expensive (design
  calls, the gold set, published numbers, API spend), batch what an ADR already
  specifies.
- **In flight, not yours unless it stalls:** two Dependabot PRs, both **green on
  every check**, both open — #147 (`codeql-action` 4 → 4.37.3) and #123 (the
  python-minor-patch group, 6 updates, open since 2026-07-25). Neither touches
  runtime behavior or a published number. They are the only open PRs.

## Next jobs, in order (each its own branch → PR)

1. ~~**`v3.2.0` scaled region eval.**~~ **DONE — run 2026-08-02, shipped.** Region
   **88.3%** 95% CI [84.2%, 91.5%] (265/300), macro-F1 0.904; category 91.7%,
   domain 89.3%. The CI narrows from 18 points at n=54 to 7. Verdict and both
   design forks (published as frozen dated prose per the bake-off precedent; **no
   `thresholds.toml` floor** — one run has no run-to-run noise under it) are in
   [ADR-022](decisions/022-scaled-region-eval-verdict.md); report in
   `evals/scale_eval_v3.txt`. The `[Unreleased]` CHANGELOG gap flagged in State
   was closed in the same release. **What is left is owner-only: the tag and the
   GitHub release** (below).
2. ~~**The named `global` cluster still wants a prompt clause.**~~ **DONE — run
   2026-08-02, clause REVERTED.** Both arms ran (408 calls) against the
   pre-registered rule in [the spec](docs/specs/global-boundary-clause.md) §6.
   Scale (n=295 after dropping duplicate snippets from the pairing): region
   **88.5% → 92.2%**, 12 of 17 named pulls fixed against 7 correct rows dragged to
   `global`, net +11 — at **McNemar p=0.0522**, missing the pre-registered p<0.05
   by 0.0022. Guardrails clean (category p=0.75; domain *improved* +3.7%,
   p=0.0192, which is an unexplained secondary observation and was **not** counted
   toward shipping — it was registered as a kill condition, not as evidence). Gold
   (n=54, human labels): region **87.0% → 94.4%**, all 7 named misses fixed
   against 3 broken, every `thresholds.toml` floor clear. The rule's own text
   calls a marginal result a revert; San ruled 2026-08-02 to honor it. Verdict,
   rationale and both arms' tables:
   [ADR-023](decisions/023-global-boundary-clause-verdict.md). **The shipped
   classifier is unchanged** (`SYSTEM_PROMPT` still `a59689e8…`), so no published
   number moved, no version bump, no marker cascade. The harness
   (`src/region_clause_ab.py`, 51 tests) and the frozen `region_clause_*` eval
   artifacts merged as the reproducible record; the clause itself did not.
   **This was reopened deliberately on 2026-08-02 — see job 3.** Do not re-run the
   same 295 rows to break the tie; that is the p-hacking the rule forbids, and the
   follow-up does not do it.
3. **The higher-power re-run — RUN-READY, awaiting owner-driven execution.**
   ADR-023's own named condition, now costed. `src/mcnemar_power.py` prices it
   exactly: at n=295 that experiment had **~49% power** against the effect it
   observed, so p=0.0522 is what a coin flip looks like when it lands on the wrong
   side by a hair. 80% power needs **n=545**, 90% needs **n=713**; one more
   300-snippet collection buys 84% *only if* the true effect is exactly what was
   measured (58% if it is three-quarters of that). Target is therefore ~730
   effective pairs. Pre-registration, power tables, decision rule and run protocol:
   [the spec](docs/specs/global-boundary-clause-rerun.md), canonical for §6 and §7.
   Harness `src/region_clause_rerun.py`; collector `scripts/extend_scale_set.py`.

   **Two design changes worth knowing before running it.** The clause is applied
   **at run time** — `classify.SYSTEM_PROMPT` is never edited, so there is no
   expected-red CI, no waiver, no revert to perform, and the Opus judge still grades
   under the shipped prompt (it must: `classify()` defaults *both* models to
   `SYSTEM_PROMPT`). And the 295 rows ADR-023 already measured are **reused, not
   re-bought** — the composed prompt is pinned by digest to the fingerprint the paid
   run recorded, so only new snippets are classified, at 3 calls each. Nothing runs
   below the pre-registered n=545 floor; `report()` raises rather than scoring.

   **Owner commands and cost are in the spec §7** (~1305 calls at the target size,
   ≈$5.75 batch / ≈$11.45 synchronous — estimates, and step 0 is the free pre-check).
   The gold arm is **deferred** to step 5, run only if rule 1 passes: it is a
   non-regression check, and last round it cost 108 calls plus a delete-and-restore
   across the published gold record for an arm that could not decide anything alone.
4. **Option, explicitly NOT a commitment: a structurally narrowed critic.** L4's
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
  `l4_eval.txt` and their prediction CSVs, and the five `region_clause_*`
  artifacts (ADR-023). The three scale-arm `region_clause_*` files additionally
  **cannot** be regenerated: `--report` refuses, because
  `assert_candidate_matches_the_live_prompt` correctly sees that the live prompt
  is no longer the reverted candidate. That refusal is the guard working.
- **Published numbers are generated, not typed.** `evals/metrics.json` is the
  artifact outward surfaces assert against; `gen_metrics_artifact.py` reads the
  version from `pyproject.toml`, so a version bump turns CI red until you
  regenerate the artifact *and* update the pinned literal in
  `tests/test_metrics_artifact.py`. That is the guard working, not a bug. The full
  ripple of a version bump, across all four repos and in dependency order, is
  inventoried in [docs/v3.2.0-release-runbook.md](docs/v3.2.0-release-runbook.md).
- **Other generated artifacts that must never be hand-edited**, each with a
  `--check` or parity gate that fails the build on a stale copy:
  `contracts/classify-response.schema.json` (`gen_contract_schema.py`),
  `evals/metrics.json` (`gen_metrics_artifact.py`), the README metrics block
  (`gen_readme_metrics.py`), `evals/gold_predictions_v3.provenance.json` (written
  by `gold_eval.py` at run time — hand-editing it fabricates a pairing nobody
  verified; the *only* legal hand edit is adding a named `waiver` block), and
  `web/baseline_export.json` + its parity fixture (`export_baseline.py`,
  `generate_parity_fixture.py`).
- **Run logs are gitignored by policy** (`evals/optimize/`, `evals/ml_loop/`,
  `evals/l4/`). The verdict in the ADR is the durable record; if a run needs to
  be published, embed it deliberately rather than un-ignoring the directory.
- **Batch `custom_id`s** must match `^[a-zA-Z0-9_-]{1,64}$` — `::` 400s; use
  `__` or bare ids (regression-tested).
- **Safety-layer refusals are an expected per-row outcome** on this content
  (s151 precedent). Record-and-continue with a sentinel; never let one row kill
  a batch retrieval (#85 pattern). ADR-021 generalized this: the sentinel set is
  now `paired_compare.HARNESS_ERROR_SENTINELS` (`__unclassified__`,
  `__incomplete__`, `__refused__`), all of which pair but are **never scored as a
  miss** — a harness failure attributed to the model is a fabricated error rate.
- **Do not hand-roll another retry loop.** New code that calls the API goes
  through `api_retry.call_with_retry` (ADR-021). The five-copies-of-the-wrong-
  `except`-tuple bug is exactly what a sixth local loop reintroduces, and its
  failure mode is silent: the run aborts on a 529, or bills a retry storm against
  an exhausted credit balance.
- **Measure-first is now six-for-six** (ADR-012, ADR-013, ADR-018, ADR-019,
  ADR-020, ADR-023): nothing ships past the eval, and thresholds come from
  measured numbers only. Five of the six declined a change with data — and
  ADR-023 is the hard case, declining a change whose target metric moved the
  right way with no measured harm, because it missed a **pre-registered**
  threshold by 0.0022. Do not re-litigate a pre-registered rule after seeing the
  numbers; that is the whole point of writing it down first.
- `evals/scale_eval`'s answer key **is the Opus judge** — never grade a
  judge-model variant against it; human gold only for quality verdicts.
- **Tags never work from containers** (proxy 403). Tag pushes are owner-only;
  hand over exact commands rather than attempting them.
- **Live runs are owner-driven.** Anything that spends tokens against the API —
  gold passes, scale passes, the L3 loops, the L4 pipeline — gets handed to San
  as an exact command, not launched from a session.

## Owner-only actions pending

- **Tagging and releasing `v3.2.0`.** The release commit is on `main`; everything
  else in job 1 is done. Tags never work from a container (proxy 403), so this is
  owner-only:

  ```bash
  git -C <repo> checkout main
  git -C <repo> pull
  git -C <repo> tag -a v3.2.0 -m "v3.2.0 - the ruler shrinks: the region axis, measured at n=300"
  git -C <repo> push origin v3.2.0
  gh release create v3.2.0 -R sanlee-ys/defense-news-classifier --title "The ruler shrinks" --notes-file <notes>
  ```

  Release notes point at the `[3.2.0]` CHANGELOG entry and ADR-022.
- **Running the higher-power re-run (job 3).** The harness, the collector and the
  pre-registration are merged and run-ready; every command that spends is owner-driven
  by repo contract. Start at the spec's §7 step 0 (free), and check the achieved
  extension size against the n=545 floor before step 2.
- Deciding whether the narrowed-critic experiment (job 4) is worth a spec at all.
  The honest default is no. The ladder is complete, measured, and now fully
  published — there is no documentation debt left to trade against, so this
  would be new build work on a rung that already returned its answer.
