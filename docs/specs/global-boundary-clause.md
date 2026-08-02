# Feature Spec — the `global`-boundary prompt clause, and its A/B

**Version:** 2.0 — **revised after adversarial review** (see §11 for what changed and why)
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

> **This document is canonical for the decision rule (§6) and the run protocol (§7).** The
> PR body summarizes and points here; where the two ever differ, this file wins.

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
model infers a theater from the US *actor* when the snippet anchors nothing.

ADR-020 proved the cluster is fixable: its critic corrected 6 of the 7 gold rows. It was
declined at ~4× calls. **A prompt clause is the cheap alternative**, and ADR-022 built the
ruler it has to be measured against.

## 2. What the evidence actually says

Reading all 17 scale pulls and all 7 gold misses against their snippets, they are one
failure in three surface forms:

| Form | Scale ids | Gold ids | What the model saw |
|---|---|---|---|
| **No place at all — only US institutions** | s157, s129, s141, s204, s288, s131, s259, s107, s020, s256, s263 | g017, g019, g026, g047, g048 | Commands, program offices, contractors, unit designations, named officials. It read "American institution" as "American theater". |
| **Geography attached to the actor, not the activity** | s134 (`NAVFAC Far East`, in a job title), s271 (`Texas-based` contractor), s283 (`DAHLGREN, Va.` dateline), **s126** (`Redstone Arsenal`, the contracting office) | g013 (`7th Fleet`, in a career history), g054 (`NEWPORT NEWS, Va.` dateline) | A geographic token that anchors the actor rather than the described activity. |
| **Orbital story with a terrestrial actor** | s067, s070 | — | The rule that orbital stories with no terrestrial theater are `global` exists; the actor's ground location overrode it. |

**The gap the clause closes.** The current rubric says to use "what the snippet states or
unambiguously implies". A snippet reading *"Marine Corps Systems Command awarded a
contract"* **does** unambiguously imply the United States — that inference is *correct*,
and the prompt's own wording licenses it. The rubric's intent is that an institution's
nationality is not a theater; its phrasing never says so.

**Only the first form is targeted.** Forms two and three are where the collateral lives
(§2.2), and the first form alone is 11 of 17 scale rows and 5 of 7 gold rows. Chasing the
other two costs far more than it buys.

### 2.1 The answer key is noisy on exactly this boundary

Measured from the committed artifacts, not asserted:

- **s024 and s025 are byte-identical snippets** (different DVIDS ids) that the answer key
  labels **`europe`** and **`middle-east`**. At most one can be right, so at least one row
  is unwinnable for any classifier, including a perfect one.
- **The EUCOM cluster.** Six rows share one sentence shape — a submarine returning to
  Naval Submarine Base New London from a *"U.S. European Command area of
  operations/responsibility"* deployment. The key says **`americas`** for s028/s029 and
  **`europe`** for s030/s031/s032/s039. Same shape, opposite answers.
- **The Dahlgren cluster.** Five rows share a `DAHLGREN, Va.` dateline plus NSWCDD as the
  actor. The key says **`global`** for s283 and **`americas`** for s292/s293/s297/s300.
- **Four exact-duplicate snippet groups** exist in the set (found by normalized-text
  comparison): s022/s023, s024/s025, s078/s079/s080, s239/s240 — **nine rows, five of them
  redundant.**

**Consequences, folded into the protocol rather than noted and forgotten:**

1. **Duplicates leave the pairing.** They violate McNemar's independence assumption in the
   anti-conservative direction. The first occurrence is kept; **effective n = 295**.
   Nothing is relabelled and no file is rewritten — this experiment does not get to edit
   its own ruler.
2. **The contested clusters are measurement noise of the same order as the effect.** At
   the tolerance margins in §6.1 the rule swings on 2–4 rows, and the EUCOM cluster alone
   is 6 rows the key answers inconsistently. A result inside that band is noise, and §6
   treats it as such.
3. **The ceiling is below 100%.** The ruler is not self-consistent on the boundary being
   tested.

### 2.2 What the clause must NOT disqualify — the collateral analysis

An earlier draft of this clause disqualified *"a geographic word inside an organization's
name, the site of its headquarters, or a story's dateline."* Joined against the snippets,
that wording killed the **only** region evidence for a large set of **currently-correct**
rows:

| Evidence form the draft killed | Currently-correct rows it would have broken |
|---|---|
| A command's or fleet's **area of operations/responsibility** | s002, s015 (5th Fleet AO → `middle-east`), s169, s198 (CENTCOM AOR → `middle-east`), s030, s031, s039 (EUCOM AO/AOR → `europe`) |
| **"based on \<named base\>"** | s057 (`Peterson Air Force Base in Colorado Springs` → `americas`) |
| A **geographic word in a unit name** | s116 (`Maryland Air National Guard` → `americas`) |
| A **dateline naming an actual theater** | s004 (`PHILIPPINE SEA` + JMSDF → `indo-pacific`) |

That is ~14 high-confidence breaks against at most 17 possible fixes, plus a second tier
of ~22 rows one charitable reading from flipping (named bases as sole evidence, contractor
facilities, homeports).

**Worse, it contradicted two ratified things:**

1. **`data/gold/README.md` ratifies "the Mediterranean counts as `europe` (6th Fleet /
   EUCOM water)"** — a fixed mapping *defined by a fleet and a command*. "Commands and unit
   designations are not theaters" flatly contradicts a ratified convention.
2. **The bullet directly above it** says *"a concrete identifiable location makes an anchor
   even at home: training at a named US base … is `americas`."* The corpus's dominant shape
   is "unit X, based at base Y, did Z" — and the two adjacent bullets gave it opposite
   answers.

**So the clause was narrowed to the first failure form only, and made to say what it
protects.** `tests/test_region_clause_ab.py::test_the_clause_preserves_the_evidence_forms_it_could_have_broken`
pins the protections and pins the over-reaching phrases as *absent*, so the same
over-reach cannot walk back in.

### 2.3 Residual risk under the narrowed clause

Hand-verified by reading every candidate row (a bounded estimate, not a measurement — the
regex pass that produced the shortlist over-flags, so its 24 residuals were read
individually):

- **F ≤ 13.** Four of the 17 named pulls carry evidence the narrowing now protects and are
  no longer targeted: **s126** (Redstone Arsenal), **s067** (California), **s271**
  (Atlantic Ocean / Texas), **s283** (`DAHLGREN, Va.`). Giving these up is the price of not
  breaking the rows in §2.2, and it is worth paying.
- **B ≈ 9 plausible.** Nine currently-correct `americas` rows whose only geography is
  institutional: **s165, s140, s260, s101, s097, s251, s290, s081, s183**. Every one is the
  *same shape as the 17 named pulls* — the key just went `americas` instead of `global`.
  That is §2.1 made concrete: ~9 at-risk rows plus the 7 converse over-call rows (s118,
  s096, s115, s223, s137, s262, s149, which name no place and which the key calls a
  specific region) is ~16 rows where the answer key applies the inference the rubric
  forbids.
- **s116 stays borderline.** Dropping the org-name rule means "Maryland" is simply a state
  named in the text, which should protect it — but the clause does call a unit an actor, so
  it is flagged rather than claimed safe.

## 3. The clause

One bullet, added to the `Region rules:` block of `classify.SYSTEM_PROMPT`, immediately
after the existing "a concrete identifiable location makes an anchor even at home" rule:

> - A US institution is not an American theater. Naming a service, command, program office,
>   contractor, unit, or official identifies the actor, not a place: a story whose only
>   geography is institutional has no anchor, so it is global rather than americas. This
>   does not narrow the evidence above — a named command's or fleet's area of operations or
>   responsibility names a theater, and so do a named base, installation, city, country, or
>   body of water, wherever the story places the activity.

**Grounding.** Restates ratified convention language rather than inventing policy: *"the
geographic theater of the story's subject activity… not the actor's nationality"*
(ADR-014 §1, `data/gold/README.md`). No new label, no new boundary, no worked example
added or edited, nothing touched on the category or domain axes.

**Why worded this way.**

- **Sentence 1 is the fix**, and it is deliberately narrow: it names *institutional-only*
  geography, and it names the specific wrong answer (`americas`) rather than a general
  preference for `global`.
- **Sentence 2 is the anti-overcorrection gate**, and after §2.2 it is doing most of the
  work. ADR-020's critic is the measured cautionary tale: restraint that lived only in a
  prompt produced a **57.4%** challenge rate against an expected 13% and did statistically
  significant harm to the domain axis (**p=0.016**). This clause therefore states what it
  protects, out loud, in the same breath as what it forbids.
- **Deliberately dropped from the earlier draft:** "the site of its headquarters" (the
  single highest-value deletion — it collided head-on with the bullet above it), the
  dateline claim (the first bullet already covers datelines, and s004 shows a dateline can
  *be* the theater), and the broad "geographic word inside an organization's name".

**Placement is load-bearing and tested.** `l4_pipeline` embeds
`extract_region_block(SYSTEM_PROMPT)` verbatim and `optimize.region_rubric_violations`
freezes that same block. A clause outside it would be invisible to both.

**Gold-set independence:** the clause quotes and paraphrases nothing from any gold or
scale snippet.

## 4. Arm 1 — scale (the primary ruler, effective n=295)

### 4.1 The judge is not re-run, and that is the correct design

`gold_eval.run_predictions` classifies each row with the workhorse and the judge
**independently, from the snippet text alone** (`src/gold_eval.py:180-181`; the batch path
does the same at `:238-249`). Neither model is shown the other's answer, so a judge label
carries **no dependence on the workhorse's prediction**.

**Two independence facts, and they are not the same fact — conflating them is the trap:**

| Claim | Holds? |
|---|---|
| A judge label is independent of the **workhorse's prediction** | ✅ True. This is what makes reusing the committed judge column as a frozen answer key valid. |
| A judge label is independent of **`SYSTEM_PROMPT`** | ❌ **False.** `classify()` defaults *both* models to `SYSTEM_PROMPT` (`src/classify.py:406`), so the judge reads the clause too. |

The second row is precisely why the judge **must not** be re-run on the scale arm: a fresh
judge pass on this branch would grade under the new prompt, moving the answer key between
arms and confounding the comparison outright. Freezing it is what makes this paired — and
it costs 300 calls instead of 600 as a side effect, not as the reason.

Both facts are asserted, not trusted: `test_judge_is_classified_from_the_snippet_alone`
covers the synchronous path and `test_judge_is_snippet_only_on_the_BATCH_path_too` covers
the batch path, **which is the one the run protocol actually uses.**

### 4.2 Guards — each one blocks a well-formed report of nothing

| Guard | Blocks |
|---|---|
| `assert_answer_key_is_complete` | An answer key that is not exactly the committed scale set: missing ids, extra ids, repeated ids, or blank labels. (The earlier version checked only column presence — a 50-row hand-made file passed it.) |
| `assert_candidate_is_complete` | A partial candidate arm. The batch path skips unparseable rows, so an interrupted run otherwise yields a clean-looking 250-row report. This **enforces** decision rule #4 instead of printing it. |
| `assert_arms_differ` | Two arms sharing a prompt hash (nothing to measure) or disagreeing on a model id (a confounded model A/B). |
| `assert_candidate_matches_the_live_prompt` | A candidate produced by some *third* prompt — which `assert_arms_differ` alone happily accepts. |
| `assert_resume_is_honest` | Appending today's prompt's rows onto yesterday's. Runs **before** the "nothing to do" early return, since a complete stale CSV is the case that most needs catching. |
| `judge_digest` | Nothing by itself — it prints a recomputable fingerprint of the answer key actually used, so a reviewer can tell two reports were graded by the same ruler. |

All prediction files load through `paired_compare.read_predictions`
(`dtype=str, keep_default_na=False`); with a bare `read_csv` a blank cell arrives as `NaN`
and the blank check compares `"nan"` against `""`, so it could never fire.

### 4.3 What is measured

- **Paired comparison on all three axes** through `src/paired_compare.py` unchanged.
  Region is the target; **category and domain are guardrails**, not optional — a
  region-only report would have scored ADR-020's critic a success.
- **F and B computed exactly as §6 prices them.** `F` = named pulls fixed. `B` = rows the
  baseline got **right** that the candidate drags to `global`. The report also prints
  "newly over-called `global`", which is a *different, weaker* quantity: it counts rows
  that were already wrong on another region, where a move to `global` costs nothing. Only
  `B` enters the decision.
- **Harness health**, reported separately from the lift.

### 4.4 Artifacts (all new; nothing frozen is touched)

`evals/region_clause_candidate.csv`, `evals/region_clause_candidate.provenance.json`,
`evals/region_clause_ab.txt`. The v3.2.0 records are opened **read-only**.

## 5. Arm 2 — gold (the human-graded half, and the provenance unblock)

The gold arm re-measures the clause against **human** labels (87.0% baseline, the 7 named
misses), and its provenance sidecar rewrite is what returns `gen_metrics_artifact.py` and
`src/eval_gate.py` to green.

**The deletion is mandatory, not tidiness.** `gold_eval.main()` only makes calls when
`set(gold["id"]) - done_ids` is non-empty. With all 54 rows present it skips the API
entirely, never rewrites the sidecar, and the gates stay red.

**The gold arm DOES re-run the judge** — 108 calls, 54 workhorse + 54 judge — and, per
§4.1, **the judge reads the new prompt**. So `judge_*_agreement` is genuinely recomputed
under the clause. That is not an inconsistency with the scale arm: there the judge *is* the
answer key and must stay frozen; here the answer key is the **human labels** and the
judge's numbers are separate gated metrics.

**Precisely which numbers move on a gold re-run:**

| Recomputed | Because |
|---|---|
| `category/domain/region_accuracy`, `*_macro_f1` | The workhorse reads the new prompt. |
| `judge_category/domain/region_agreement` | The **judge also reads the new prompt**. |
| `evals/metrics.json`, README table, `gold_confusion_v3*` | All derive from the regenerated predictions. |
| The provenance sidecar | Rewritten with the new prompt hash — this is what un-reds CI. |

**The exposure, stated correctly.** `judge_region_agreement` floors at **0.93** against a
measured 1.000. At n=54 that allows **at most 3** judge-vs-human region disagreements; a
4th fails the gate on the *floor*, not on provenance. This is a **realistic outcome, not a
tail risk**, because the judge is reading the clause for the first time. It is also a
genuine signal: if the clause makes the *Opus judge* disagree with humans on region, the
clause is wrong.

**Gold-side collateral, re-derived under the narrowed clause.** All 35 specific-region gold
rows are currently correct, so gold can only lose there against at most 7 gains. Under the
*earlier* draft, nine rows were plausible breaks (g004, g005, g012, g014, g018, g024, g027,
g041, g043) — which would land 45/54 = 83.3% and fail rule 3. Under the narrowed clause
that list collapses to **one, g024** (`Fleet Readiness Center East`, institution-only),
with g041 borderline: g004 (GROTON + New London + SOUTHCOM AOR), g005 and g014 (Joint Base
Pearl Harbor-Hickam), g012 (Boone National Guard Center), g018 (WATERVLIET ARSENAL, N.Y.),
g027 (University of California Davis) and g043 (DAHLGREN, Va.) all carry evidence the
clause explicitly protects. **That collapse is the single clearest argument for the
narrowing.**

## 6. Pre-registered decision rule *(canonical — the PR body points here)*

`F` = named pulls fixed (of 17, realistically ≤13 per §2.3). `B` = currently-correct region
rows the clause drags to `global`. McNemar exact via the repo's own `mcnemar_exact`.

**SHIP the clause** when **all four** hold:

1. **Scale region improves significantly**: net region rows `F - B > 0` with **p < 0.05**.
   *(p is computed over all discordant pairs on the axis, not only over F and B.)*
2. **No significant guardrail harm**: neither category nor domain shows a significant
   paired loss (p < 0.05). A **kill condition**, not a tiebreak — ADR-020 is the precedent.
3. **Gold region does not regress**: human-graded region accuracy ≥ 87.0%, and no gated
   floor in `evals/thresholds.toml` is breached (including `judge_region_agreement`).
   ⚠️ **The 87.0% bar is a MANUAL READ, not a gate.** `thresholds.toml` floors
   `region_accuracy` at 0.78, and no threshold is added by this branch (ADR-007: floors
   come from measured runs, and this run does not exist yet). The floors *are* enforced by
   `eval_gate.py`; the 87.0% bar is San's read of `evals/gold_eval_v3.txt`. An unrun gate
   is not a pass, so it is labelled rather than implied.
4. **Harness health is clean**: 295 eligible pairs, no dropped or errored rows. Enforced by
   `assert_candidate_is_complete`.

**SHIP THE NEGATIVE RESULT** (revert the clause, keep the ADR) when region is flat or down,
or any guardrail shows significant harm, or a floor breaks.

**Call it MARGINAL, and revert**, when region improves but p ≥ 0.05. A marginal result is
not a small win — at this n it is *an unresolved question*, and the repo's standard is that
an unmeasured improvement does not ship (ADR-012 and ADR-013 both declined on this).

### 6.1 Revised break-count table — computed on the deduplicated set

Baseline region on the effective set: **261/295 = 88.5%**.

| F fixed | B broken | net | accuracy | McNemar p | reading |
|---:|---:|---:|---:|---:|---|
| 13 | 0 | +13 | 92.9% | 0.0002 | ship |
| 13 | 1 | +12 | 92.5% | 0.0018 | ship |
| 13 | 2 | +11 | 92.2% | 0.0074 | ship |
| 13 | 3 | +10 | 91.9% | 0.0213 | ship |
| 13 | 4 | +9 | 91.5% | 0.0490 | ship *(barely)* |
| 13 | 6 | +7 | 90.8% | 0.1671 | **marginal → revert** |
| 13 | 9 | +4 | 89.8% | 0.5235 | **marginal → revert** |
| 11 | 2 | +9 | 91.5% | 0.0225 | ship |
| 11 | 3 | +8 | 91.2% | 0.0574 | **marginal → revert** |
| 9 | 1 | +8 | 91.2% | 0.0215 | ship |
| 9 | 2 | +7 | 90.8% | 0.0654 | **marginal → revert** |
| 7 | 0 | +7 | 90.8% | 0.0156 | ship |
| 7 | 1 | +6 | 90.5% | 0.0703 | **marginal → revert** |

**The honest limits, stated before the run:**

- **The realistic operating point is F≈13, B≈9 — which is a marginal result.** §2.3's
  estimates land almost exactly on the revert side. This experiment is genuinely
  uncertain, and that is the reason to run it rather than merge it.
- **The collateral budget is 4 rows.** At F=13 the rule survives B=4 (p=0.0490) and dies at
  B=6. At F=9 it dies at B=2.
- **Below F=7 almost nothing passes**: F=7,B=0 gives p=0.0156, but F=7,B=1 already gives
  0.0703.
- **§2.1's answer-key noise is the same size as the margin.** The EUCOM cluster alone is 6
  inconsistently-answered rows; the tolerance band is 4. A result inside that band cannot
  be distinguished from the ruler's own disagreement with itself.
- **The guardrails are more sensitive than they look**: ~6 net-broken rows on category or
  domain alone clears p<0.05 — a 2-point move.

## 7. Run protocol (owner-driven — nothing here is launched from a session)

Every command from the repo root. **Total spend: 408 calls.**

### Step 1 — the scale arm (300 workhorse calls, no judge calls)

```bash
uv run --env-file .env python src/region_clause_ab.py --run --batch
uv run python src/region_clause_ab.py --report
```

`--batch` is roughly half the per-token cost and non-interactive. The synchronous
alternative (drop `--batch`) gives per-row progress at full price. Both are resume-safe.
`--report` is free, offline, and repeatable.

Optional independent cross-check through the untouched CLI (note: this one does **not**
deduplicate, so it reports n=300 and will differ slightly by design):

```bash
uv run python src/paired_compare.py --axis region --baseline evals/scale_predictions_v3.csv --candidate evals/region_clause_candidate.csv --answer-key evals/scale_predictions_v3.csv --truth-column judge_region
```

### Step 2 — the gold arm (108 calls: 54 workhorse + 54 judge)

**Write down the undo line before running the delete.** The two files being removed are the
shipped v3.2.0 record that five repos' published markers hang off; if the batch aborts, this
restores them:

```bash
git checkout -- evals/gold_predictions_v3.csv evals/gold_predictions_v3.provenance.json
```

Then:

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
nothing gates and which would otherwise describe a run that no longer exists.
`eval_gate.py` last, to confirm green.

### Step 3 — free verification

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
2048-token cacheable floor. A confirmation, not a risk.

## 8. Expected-red CI on this branch, and exactly why

Four test failures and one workflow failure, **all from one cause**: #137/#142 pinned the
published snapshot to the prompt that produced it, and the clause changes
`classify.SYSTEM_PROMPT`.

```
prompt_sha256 snapshot: a59689e8ac238d655c0b64c8aaaf3fef6d391267e2015f1740f24e120ed903cd
prompt_sha256 code now: b0202d06a876cc0641f50e8910368d7c8a4eb0295f662ac472f9fdd6abf4e963
```

| Leg | Status | Why |
|---|---|---|
| **evals / offline-gate** | **RED** | `src/eval_gate.py` → `check_provenance()` → exit 1 before grading. |
| **tests** | **RED** | Fails at the *"Metrics artifact is current"* step (`gen_metrics_artifact.py --check`), which runs **before** pytest — so the suite is never reached in CI. |
| tests → `test_metrics_artifact.py::test_the_snapshot_still_matches_the_prompt_that_produced_it` | fails locally | Same provenance check. |
| tests → `test_eval_gate.py` ×3 | fail locally | Same provenance check. |
| docker, CodeQL | green | Untouched. |

**No waiver is filed, deliberately.** The snapshot genuinely does not describe this
classifier. The red is the guard doing its job, and §7 step 2 is the remedy it names.

## 9. What the post-run session does

### If the clause ships

1. ADR-023 recording the verdict, with a `## Downstream surfaces` section
   (`lint_decisions.py` enforces it on new ADRs).
2. Version → `3.2.1` (PATCH) across the chain: `pyproject.toml`, regenerated
   `evals/metrics.json`, the pinned literal + docstring in `tests/test_metrics_artifact.py`,
   `src/api.py`'s FastAPI `version=`. CHANGELOG entry.
3. **The full published-marker cascade.** Use `docs/v3.2.0-release-runbook.md` as the *map*
   of where markers live, but **its verified-negatives do not transfer**: they were
   established for a version-only bump where *no gold value moved*. Here the gold numbers
   move, so:
   - **portfolio**: runbook item 25's "all 16 markers stay green because no gold value
     moves" **is void**. Re-check all 16 `data-metric` markers via
     `scripts/check-published-metrics.cjs`.
   - **architecture**: `program/README.md` — the `<!-- version:classifier -->` marker (never
     backticked) plus the six gold `metric:` markers at line 77.
   - **learning-notes**: `03-reading-the-numbers.md`'s six gold markers; `glossary.md:97,119`
     (the tooltip source of truth).
   - **kb-agent**: `kb/projects/defense-news-classifier.md`, then `ingest.py --accept` and
     `scripts/index.py`, or ChromaDB serves the old text.
   - Order matters: the classifier's `metrics.json` must be on `main` before architecture's
     guard is fixed (it live-fetches, ~5 minute raw.githubusercontent cache).

### If the result is negative or marginal

1. **Revert the clause** — `src/classify.py` back to the baseline prompt. That restores the
   provenance hash **but not the sidecar**, which the paid gold run has by then rewritten.
2. **The decision that leaves behind, stated now so it is not improvised then:** restore the
   pre-run gold artifacts from git (`gold_predictions_v3.csv` + sidecar + `gold_eval_v3.txt`
   + `metrics.json`) rather than keep a re-baseline measured under a prompt that no longer
   ships. The re-run's numbers do not vanish — they become the **dated evidence quoted in
   the ADR**, the bake-off precedent for a figure that must not track a live artifact.
   **Recommended, but an owner call**, since keeping the fresh baseline is defensible only
   if the prompt is *not* reverted.
3. ADR recording the negative result — a third data point beside ADR-012 and ADR-013.
4. No version bump, no marker cascade.

## 10. Explicitly NOT in this branch

No merge · no version bump · no CHANGELOG · no ADR (spec first, ADR at verdict — the
ADR-017 pattern) · no `thresholds.toml` change · no metrics regeneration · no gold-set edit
· no frozen-artifact change · no answer-key relabelling · no provenance waiver · **no live
API call.**

## 11. Revision log

**v2.0 (2026-08-02)** — revised after an independent adversarial review returned FIX FIRST.
The harness architecture, the judge-reuse argument and every decision-rule p-value were
re-derived by the reviewer and confirmed clean. What changed:

| Finding | Resolution |
|---|---|
| The clause over-reached: ~14 currently-correct rows lost their only region evidence | **Clause rewritten** (§3), narrowed to institutional-only geography and made to state what it protects. "The site of its headquarters" deleted; the dateline and org-name claims dropped. |
| Two ratified-convention contradictions (Mediterranean = 6th Fleet/EUCOM water; the adjacent named-base bullet) | Both resolved by the rewrite; a test pins the protections and the absence of the over-reaching phrases. |
| Answer key is noisy on this exact boundary; exact-duplicate snippets | §2.1 added. Duplicates now leave the pairing (**effective n=295**); contested clusters named; folded into §6.1's honest limits. |
| Six guard defects | All fixed (§4.2): real completeness guards for both arms, string-typed loading so the blank check can fire, a live-prompt pin, resume check moved before the early return, B computed as the rule defines it, batch-path judge-independence test added. |
| Missing undo line before the `rm` | Added (§7 step 2). |
| Rule 3's 87.0% bar is enforced by nothing | Labelled **manual read** (§6), with the reason it is not a gate. |
| s126 misfiled in the evidence table | Moved to "geography attached to the actor" (§2). |
| Spec and PR body could drift | This document declared canonical for §6 and §7; the PR body points here. |
| *Reviewer note that the judge's labels are prompt-independent* | **Pushed back, with code.** `classify()` defaults **both** models to `SYSTEM_PROMPT` (`src/classify.py:406`), so the judge does read the clause. The independence that holds is from the *workhorse's prediction*, not from the prompt. §4.1 now separates the two explicitly, and §5 restates the gold-arm exposure as a realistic outcome rather than a tail risk. |
