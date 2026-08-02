# Feature Spec — the `global`-boundary prompt clause, and its A/B

**Version:** 1.0
**Status:** Proposed — **the clause is written, the protocol is built, nothing is measured.**
This branch is deliberately unmerged: the numbers decide, not the code.
**Author:** San Lee
**Last updated:** 2026-08-02
**Roadmap fit:** unversioned until measured. A shipped clause would be a **PATCH**
(`v3.2.1`) — a fix, no new capability, the `{category, operational_domain, region}`
contract untouched. A negative result ships an ADR and no version at all.
**Related:** [ADR-014](../../decisions/014-region-field-design.md) (the ratified region
conventions this clause is grounded in) ·
[ADR-022](../../decisions/022-scaled-region-eval-verdict.md) (the n=300 ruler and the
cluster counts) · [ADR-020](../../decisions/020-l4-multi-agent-pipeline.md) (the declined
critic — and the overcorrection cautionary tale this clause is written against) ·
[ADR-007](../../decisions/007-evals-as-ci-gate.md) (floors come from measured runs) ·
[`data/gold/README.md`](../../data/gold/README.md) (the conventions as ratified on review)

---

## 1. Problem statement

`region` has one systematic, named error. ADR-022 measured it at n=300:

| | |
|---|---|
| Answer-key `global` rows | 70 |
| …pulled to a specific region | **17** |
| …of which to `americas` | 16 |
| All region disagreements | 35 |
| The pull's share of them | **49%** |

The same shape is **all seven** of the region misses on the human-graded gold 54. The
model infers a theater from the US *actor* when the snippet anchors nothing — precisely
what the ratified rubric forbids.

ADR-020 proved the cluster is fixable: its critic corrected 6 of the 7 gold rows. It was
declined at ~4× calls. **A prompt clause is the cheap alternative**, and ADR-022 built the
ruler it has to be measured against: region's 95% CI is now 7 points wide, not 18.

## 2. What the evidence actually says

Read all 17 scale pulls and all 7 gold misses against their snippets. They are one
failure in three surface forms:

| Form | Scale ids | Gold ids | What the model saw |
|---|---|---|---|
| **No place at all — only US organizations** | s157, s129, s141, s204, s288, s131, s259, s107, s020, s256, s263 | g017, g019, g026, g047, g048 | Commands, program offices, contractors, unit designations, named officials. It read "American institution" as "American theater". |
| **Geography attached to the actor, not the activity** | s126, s134, s271, s283 | g013, g054 | A geographic word inside an organization's name, a company's home state, a dateline. Two of these are already forbidden by name in the current rubric — and still failed. |
| **Orbital story with a terrestrial actor** | s067, s070 | — | The rule that orbital stories with no terrestrial theater are `global` exists; the actor's ground location overrode it. |

**The gap that lets all three through.** The current rubric says to use "what the snippet
states or unambiguously implies". A snippet reading *"Marine Corps Systems Command awarded
a contract"* **does** unambiguously imply the United States — that inference is *correct*,
and the prompt's own wording licenses it. The rubric's intent is that an institution's
nationality is not a theater; its phrasing never says so. The clause closes exactly that.

### 2.1 The finding that bounds this experiment

The 10 converse rows — where the baseline over-called `global` and the answer key named a
region — were read the same way. **Seven of the ten (s118, s096, s115, s223, s137, s262,
s149) are snippets that name no identifiable place at all.** On those rows the *judge*
applied the US-actor inference the rubric forbids. Only s155 (a named base) is a clean
model miss; s066 and s007 are contestable.

This is a measured property of the answer key, and it matters three ways:

1. **Those 7 rows are a floor, not a target.** The clause makes the model *more* likely to
   answer `global` there, which is what it already answers. They stay wrong.
2. **They are evidence the boundary is contested inside the answer key**, so some of the
   148 `americas` rows the baseline currently gets right are right for the same
   inference-based reason — and the clause will convert an unknown number of them into
   misses. That number is the experiment's whole risk, and it cannot be estimated from the
   baseline alone. It is why this is measured rather than merged.
3. **It caps the honest ceiling.** The clause cannot reach 100% region agreement, because
   the ruler itself is not self-consistent on the boundary being tested.

This is stated up front rather than discovered at verdict time.

## 3. The clause

One bullet, added to the `Region rules:` block of `classify.SYSTEM_PROMPT`, immediately
after the existing "a concrete identifiable location makes an anchor even at home" rule so
the two read as a contrast:

> - An organization is not a theater. Commands, program offices, unit designations,
>   contractors, and named officials say who is acting, not where — and neither does a
>   geographic word inside an organization's name, the site of its headquarters, or a
>   story's dateline. A snippet whose only geography is of that kind has named no place:
>   label it global. A specific region still needs a place the snippet puts the described
>   activity in.

**Grounding.** Every element restates ratified convention language rather than inventing
policy: *"the geographic theater of the story's subject activity… not the actor's
nationality and not the dateline"* (ADR-014 §1, `data/gold/README.md`). The clause adds no
new label, no new boundary, and no worked example.

**Why it is written this way.**

- **The last sentence is the anti-overcorrection gate**, and it is not decoration.
  ADR-020's critic failed at exactly this: a charter that lived only in a prompt produced a
  57.4% challenge rate against an expected 13%, and did statistically significant damage to
  the domain axis (p=0.016). So the clause gates on **evidence in the snippet** — it says
  what does *not* count as a place and then re-asserts what does. It never says "prefer
  `global`", because a blanket preference is the failure mode with measured precedent here.
- **It names the actor categories the evidence actually contains** (commands, program
  offices, unit designations, contractors, officials) rather than gesturing at "an
  organization", so the model does not have to infer the extension.
- **Scoped to region only.** No category or domain guidance is touched; no worked example
  is added or edited; the prompt is not restructured.

**Placement is load-bearing and tested.** ADR-020's critic embeds
`extract_region_block(SYSTEM_PROMPT)` verbatim rather than restating the rubric, and
`optimize.region_rubric_violations` freezes that same block against the optimization loop.
A clause added outside it would be invisible to both — reopening the gap ADR-014's missing
downstream sweep left. `tests/test_region_clause_ab.py` asserts the clause is inside the
block.

**Gold-set independence.** The clause quotes and paraphrases nothing from any gold or scale
snippet. It is written from the rubric's vocabulary only.

## 4. Arm 1 — scale (the primary ruler, n=300)

### 4.1 The judge is not re-run, and that is the correct design

`gold_eval.run_predictions` classifies each row with the workhorse and the judge
**independently, from the snippet text alone** (`src/gold_eval.py:180-181`; the batch path
does the same at `:238-249`). Neither model is shown the other's answer. A judge label is
therefore a function of (snippet, judge model, judge prompt) with **no dependence on the
workhorse's prediction or prompt**.

So the judge labels already committed in `evals/scale_predictions_v3.csv` are reused as a
**frozen answer key**. Two consequences:

- **The candidate arm costs 300 calls, not 600.** No judge calls at all.
- **More importantly, it is the only sound choice.** `classify()` defaults *both* models to
  `classify.SYSTEM_PROMPT`, so a fresh judge pass on this branch would grade under the new
  prompt — moving the answer key between arms and confounding the comparison outright.
  Holding it frozen is what makes this paired.

`src/region_clause_ab.py` enforces this rather than documenting it:
`assert_answer_key_is_frozen` refuses a key with missing or blank judge columns, and
`assert_arms_differ` refuses to report when the two arms share a prompt hash (nothing to
measure) or disagree on either model id (a confounded model A/B).

### 4.2 What is measured

- **Paired comparison on all three axes**, through `src/paired_compare.py` unchanged —
  the repo's existing, tested pairing, McNemar and harness-health code, not a private
  reimplementation. Region is the target; **category and domain are guardrails**, and they
  are not optional: a region-only report would have scored ADR-020's critic a success.
- **The named cluster, both directions**: how many of the 17 named pulls the clause fixed,
  how many rows it *newly* over-called `global`, and the net region row change. The ids are
  derived from the committed baseline, never hardcoded — a pinned list would be a second
  source of truth for a fact the CSV already states.
- **Harness health**, reported separately from the lift, per `paired_compare`'s rule.

### 4.3 Artifacts (all new; nothing frozen is touched)

| Path | Written by |
|---|---|
| `evals/region_clause_candidate.csv` | `--run` (appended per row; resume-safe) |
| `evals/region_clause_candidate.provenance.json` | `--run`, only on a pass that made calls |
| `evals/region_clause_ab.txt` | `--report` (atomic whole-file write) |

`evals/scale_predictions_v3.csv`, its sidecar, `scale_eval_v3.txt` and
`scale_confusion_v3_region.csv` are the shipped v3.2.0 record and are opened **read-only**.

## 5. Arm 2 — gold (the human-graded half, and the provenance unblock)

The gold arm does two jobs at once: it re-measures the clause against **human** labels
(87.0% baseline, the 7 named misses), and its provenance sidecar rewrite is what returns
`gen_metrics_artifact.py` and `src/eval_gate.py` to green.

**The deletion is mandatory, not tidiness.** `gold_eval.main()` only makes calls when
`set(gold["id"]) - done_ids` is non-empty. With all 54 rows already present it skips the
API entirely, never rewrites the sidecar, and the gates stay red. The CI live job deletes
both files for this exact reason.

**Judge re-runs ARE needed here, unlike the scale arm** — and the difference is not an
inconsistency. On scale, the judge is the answer key and must stay frozen. On gold, the
answer key is the **human labels**; the judge's numbers are the separate
`judge_*_agreement` metrics, three of which are gated floors. Those must be re-measured
under the shipped prompt or the floors would describe a judge that is not the one on disk.

**A sharp risk this creates.** `judge_region_agreement` has a floor of **0.93** against a
measured 1.000. At n=54 that allows **at most 3** judge-vs-human region disagreements — a
4th fails the gate on the floor rather than on provenance. That is a real way this branch
stays red after a correct, paid re-run, and it is also a genuine signal: if the clause
makes the *Opus* judge disagree with humans on region, that is direct evidence the clause
is wrong. All 7 gold misses are rows where the human and the judge already agree on
`global`, so the exposure is the 35 gold rows carrying a specific human region label (22 of
them `americas`).

## 6. Pre-registered decision rule

Written before the run, per the repo's measure-first method. `F` = named pulls fixed (of
17); `B` = currently-correct region rows the clause drags to `global`. McNemar exact over
the discordant pairs, the repo's own `mcnemar_exact`.

**SHIP the clause** when **all four** hold:

1. **Scale region improves significantly**: net region rows `F - B > 0` with **p < 0.05**.
2. **No significant guardrail harm**: neither category nor domain shows a significant
   paired loss (p < 0.05 against the candidate). This is a **kill condition**, not a
   tiebreak — ADR-020's verdict is the precedent.
3. **Gold region does not regress**: human-graded region accuracy ≥ 87.0%, and no gated
   floor in `evals/thresholds.toml` is breached (including `judge_region_agreement`).
4. **Harness health is clean**: 300 eligible pairs, no dropped or errored rows.

**SHIP THE NEGATIVE RESULT** (revert the clause, keep the ADR) when region is flat or down,
or any guardrail shows significant harm, or a floor breaks.

**Call it MARGINAL, and revert**, when region improves but p ≥ 0.05. A marginal result is
not a small win — at this n it is *an unresolved question*, and the repo's own standard is
that an unmeasured improvement does not ship. ADR-013 and ADR-012 both declined on exactly
this reasoning.

### 6.1 What is and is not resolvable at n=300 — computed, not asserted

Baseline region: **265/300 = 88.3%**, 95% Wilson CI [84.2%, 91.5%].

| F fixed | B broken | net | accuracy | McNemar p | reading |
|---:|---:|---:|---:|---:|---|
| 17 | 0 | +17 | 94.0% | 0.0000 | ship |
| 17 | 4 | +13 | 92.7% | 0.0072 | ship |
| 17 | 6 | +11 | 92.0% | 0.0347 | ship |
| 17 | 8 | +9 | 91.3% | 0.1078 | **marginal — revert** |
| 12 | 2 | +10 | 91.7% | 0.0129 | ship |
| 12 | 4 | +8 | 91.0% | 0.0768 | **marginal — revert** |
| 10 | 2 | +8 | 91.0% | 0.0386 | ship |
| 10 | 4 | +6 | 90.3% | 0.1796 | **marginal — revert** |
| 6 | 0 | +6 | 90.3% | 0.0312 | ship (the floor case) |
| 5 | 0 | +5 | 90.0% | 0.0625 | **marginal — revert** |

**The honest limits, stated before the run:**

- **Fewer than 6 fixes cannot pass, however clean.** F=6, B=0 gives p=0.0312; F=5, B=0
  gives p=0.0625. With ~17 target rows in 300, a partial fix is simply not resolvable here.
  The clause must work on most of the cluster or it does not measurably work at all.
- **Collateral is expensive fast.** At a perfect F=17 the clause tolerates 6 broken rows
  and dies at 8. At F=10 it dies at 4.
- **The guardrails are more sensitive than they look**: 6 net-broken rows on category or
  domain alone clears p<0.05. That is a 2-point move — an easy amount of damage for a
  prompt edit to do.
- **§2.1 caps the ceiling.** At least 7 answer-key rows are inference-based in the
  direction the clause argues against, so a perfect-in-principle clause still cannot clear
  ~94%.

## 7. Run protocol (owner-driven — nothing here is launched from a session)

Every command from the repo root. Call counts and costs are per-command.

### Step 1 — the scale arm (300 workhorse calls, no judge calls)

```bash
uv run --env-file .env python src/region_clause_ab.py --run --batch
uv run python src/region_clause_ab.py --report
```

`--batch` is roughly half the per-token cost and non-interactive; results land when the
batch ends. The synchronous alternative (`--run`, no `--batch`) gives per-row progress at
full price. Both are resume-safe. `--report` is free, offline, and repeatable.

Optional independent cross-check of the same numbers through the untouched CLI:

```bash
uv run python src/paired_compare.py --axis region --baseline evals/scale_predictions_v3.csv --candidate evals/region_clause_candidate.csv --answer-key evals/scale_predictions_v3.csv --truth-column judge_region
```

### Step 2 — the gold arm (108 calls: 54 workhorse + 54 judge)

```bash
rm evals/gold_predictions_v3.csv evals/gold_predictions_v3.provenance.json
uv run --env-file .env python src/gold_eval.py --batch
uv run python scripts/gen_metrics_artifact.py
uv run python scripts/gen_readme_metrics.py
uv run python src/eval_confusion.py
uv run python src/eval_gate.py
```

The deletion is required (§5). `gen_metrics_artifact.py` and `gen_readme_metrics.py` move
the published gold numbers; `eval_confusion.py` refreshes the `_v3` confusion record, which
would otherwise describe a run that no longer exists. `eval_gate.py` last, to confirm green.

### Step 3 — free verification, no key needed beyond the two runs above

```bash
uv run pytest
uv run ruff check .
uv run black --check .
uv run mypy src
```

Optionally, the prompt cache floor (`count_tokens` is free but needs a key):

```bash
uv run --env-file .env python scripts/cache_diagnostics.py
```

The clause **adds** tokens, so the ~2425-token prefix moves further above Sonnet 5's
2048-token cacheable floor. This is a confirmation, not a risk.

**Total spend: 408 calls** — 300 workhorse (scale, batched) + 108 (gold, batched).

## 8. Expected-red CI on this branch, and exactly why

Four test failures and one workflow failure, **all from one cause**: #137/#142 pinned the
published snapshot to the prompt that produced it, and the clause changes
`classify.SYSTEM_PROMPT`.

```
prompt_sha256 snapshot: a59689e8ac238d655c0b64c8aaaf3fef6d391267e2015f1740f24e120ed903cd
prompt_sha256 code now: 0664625160640b2248e67de95803e52ba48aaadb3cbb6a79d389968367d86e19
```

| Leg | Status | Why |
|---|---|---|
| **evals / offline-gate** | **RED** | `src/eval_gate.py` → `check_provenance()` → exit 1 before grading. |
| **tests** | **RED** | Fails at the *"Metrics artifact is current"* step (`gen_metrics_artifact.py --check`), which runs **before** pytest — so the suite is never reached in CI. |
| tests → `test_metrics_artifact.py::test_the_snapshot_still_matches_the_prompt_that_produced_it` | fails locally | Same provenance check. |
| tests → `test_eval_gate.py` ×3 (`test_provenance_passes_on_the_real_committed_snapshot`, `test_main_succeeds_on_the_real_committed_snapshot`, `test_the_live_jobs_explicit_default_path_is_still_checked`) | fail locally | Same provenance check. |
| docker, CodeQL | green | Untouched. |

**Locally: 548 passed, 4 failed** — and the 4 are the list above, nothing else.

Everything else on the tests lane passes on this branch and was run: `ruff check .`,
`black --check .`, `mypy src` (28 files), `gen_contract_schema.py --check`,
`gen_readme_metrics.py --check`, `lint_decisions.py` (22 ADRs), `parity_check.mjs`
(354 rows × 2 axes).

**No waiver is filed, deliberately.** `provenance.check` supports one, and using it here
would be exactly wrong: the snapshot genuinely does not describe this classifier. The red
is the guard doing its job, and the gold re-run in §7 step 2 is the remedy it names.

## 9. What the post-run session does

### If the clause ships

1. ADR-023 recording the verdict, with a `## Downstream surfaces` section
   (`lint_decisions.py` enforces it on new ADRs).
2. Version → `3.2.1` (PATCH) across the chain the runbook names: `pyproject.toml`,
   regenerated `evals/metrics.json`, the pinned literal + docstring in
   `tests/test_metrics_artifact.py`, `src/api.py`'s FastAPI `version=`. CHANGELOG entry.
3. **The full published-marker cascade — and this is the part the v3.2.0 runbook does *not*
   cover.** Use `docs/v3.2.0-release-runbook.md` as the *map* of where markers live, but
   **its verified-negatives do not transfer**: they were established for a version-only
   bump where *no gold value moved*. Here the gold numbers move, so:
   - **portfolio**: runbook item 25's "all 16 markers stay green because no gold value
     moves" **is void**. All 16 `data-metric` markers must be re-checked against the new
     `metrics.json` via `scripts/check-published-metrics.cjs`.
   - **architecture**: `program/README.md` — the `<!-- version:classifier -->` marker (never
     backticked) plus the six gold `metric:` markers at line 77, which the runbook could
     treat as unchanged and now cannot.
   - **learning-notes**: `03-reading-the-numbers.md`'s six gold markers, gated by its own
     checker, likewise now live. `glossary.md:97,119` carries the tooltip source of truth.
   - **kb-agent**: `kb/projects/defense-news-classifier.md`, then `ingest.py --accept` and
     `scripts/index.py`, or ChromaDB serves the old text.
   - Order matters: the classifier's `metrics.json` must be on `main` before architecture's
     guard is fixed (it live-fetches, with a ~5 minute raw.githubusercontent cache).

### If the result is negative or marginal

1. **Revert the clause** — `src/classify.py` back to the baseline prompt. That alone
   restores the provenance hash… **but not the sidecar**, which the paid gold run has by
   then already rewritten with the clause's hash and the clause's numbers.
2. **The decision that leaves behind, stated now so it is not improvised then:** the gold
   re-run happened and its numbers are real. Reverting the prompt makes the *old* committed
   snapshot correct again, so the honest close is to **restore the pre-run gold artifacts
   from git** (`gold_predictions_v3.csv` + sidecar + `gold_eval_v3.txt` + `metrics.json`)
   rather than keep a re-baseline measured under a prompt that no longer ships. The
   re-run's numbers do not vanish — they are the *evidence in the ADR*, quoted as a dated
   measurement, which is the bake-off precedent for a figure that must not track a live
   artifact. **Recommended, but flagged as an owner call**, because the alternative (keep
   the fresh baseline, waive nothing, accept a sidecar describing a reverted prompt) is
   defensible only if the prompt is *not* reverted.
3. ADR recording the negative result: the cluster is real, prompt-level narrowing was
   measured against a 7-point ruler, and it did not pay. That result is worth as much as a
   positive one and is the third data point alongside ADR-012 and ADR-013.
4. No version bump, no marker cascade — nothing published moves.

## 10. Explicitly NOT in this branch

- **No merge.** The numbers decide.
- **No version bump, no CHANGELOG entry, no ADR.** The repo's pattern is spec first, ADR at
  verdict time (ADR-017 landed with its run, not with its spec).
- **No threshold.** Nothing is added to `evals/thresholds.toml`; `src/eval_gate.py` is
  untouched. Floors come from measured runs (ADR-007), and this measurement does not exist.
- **No metrics regeneration, no gold-set edit, no frozen-artifact change.**
- **No waiver** in the provenance sidecar (§8).
- **No live API call was made building any of this.**
