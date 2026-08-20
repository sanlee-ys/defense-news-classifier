# Feature Spec — the `global`-boundary clause, re-registered at adequate power

**Version:** 1.2
**Status:** **COMPLETE — all steps run, all four rules PASSED, clause ADOPTED as
`v3.2.1` on 2026-08-03 ([ADR-024](../../decisions/archive/024-global-boundary-clause-adopted.md)).**
§6 was written before any number existed and is **unchanged since** — including through
the verdict; that is what makes it a pre-registration rather than a summary. See
*Run status* below.
**Author:** San Lee
**Last updated:** 2026-08-02
**Roadmap fit:** unversioned until measured. A shipped clause would be a **PATCH**
(`v3.2.1`) — a fix, no new capability, the `{category, operational_domain, region}`
contract untouched. A negative result ships an ADR and no version at all. Identical to
the ADR-023 round, deliberately.
**Related:** [ADR-023](../../decisions/archive/023-global-boundary-clause-verdict.md) (the
verdict this follows from, and the condition it named) ·
[the first pre-registration](global-boundary-clause.md) (§1–§11 of which are the
evidence base this reuses; §12 is the result being re-tested) ·
[ADR-022](../../decisions/archive/022-scaled-region-eval-verdict.md) (the n=300 ruler) ·
[ADR-014](../../decisions/014-region-field-design.md) (the ratified region conventions
the clause restates) · [ADR-020](../../decisions/archive/020-l4-multi-agent-pipeline.md) (the
declined critic — the overcorrection cautionary tale) ·
[ADR-015](../../decisions/015-public-domain-data-sourcing.md) (why the extension may be
collected from DVIDS at all) · [ADR-007](../../decisions/007-evals-as-ci-gate.md)
(floors come from measured runs)

> **This document is canonical for the decision rule (§6) and the run protocol (§7).**
> Where it and any other surface differ, this file wins.

---

## 1. Problem statement

ADR-023 measured the `global`-boundary clause and declined it:

| | |
|---|---|
| Scale region, baseline → candidate | 88.5% → **92.2%** (+3.7 pts) |
| Discordant pairs (cand / base) | **19 / 8** |
| McNemar exact, two-sided | **p = 0.0522** |
| Pre-registered bar | p < 0.05 |
| Named pulls fixed / correct rows broken | F = 12, B = 7 |
| Gold arm (human labels, n=54) | 87.0% → **94.4%**, all 7 named misses fixed |

Three of four rules passed; rule 1 missed by 0.0022. The verdict was **MARGINAL →
REVERT**, and honoring it was the point.

The ADR then named its own condition for re-testing: *"A higher-power ruler, and
essentially nothing else."* This spec turns that sentence into a number, a collection
plan, and a rule.

**What was never in doubt:** that the effect is in the right direction, that the gold
arm moved 7.4 points on human labels, or that the clause is grounded in ratified
convention. What was in doubt is whether n=295 could tell 12-fix / 7-break apart from
noise. §2 answers that: it could not, and it was never going to.

## 2. Power analysis — what n=295 could and could not decide

Computed by `src/mcnemar_power.py`, which asks the repo's own
`baseline_ml.mcnemar_exact` for its critical region rather than approximating it. Two
nested binomials, no normal approximation and no simulation — which matters, because
the verdict being re-litigated turned on 0.0022. Reproduce with:

```bash
uv run python src/mcnemar_power.py
```

### 2.1 Sample size, at α = 0.05 two-sided

Scenarios hold the **discordant rate** at the observed 27/295 and shrink the **net
lift**. That is the harder and more honest question: scaling both rates together would
model a *quieter* experiment as well as a smaller effect, which flatters the sample
size.

| Scenario | Net lift | n for 80% | exp. discordants | n for 90% | exp. discordants | power @ n=295 | power @ n=595 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Observed (19/8)** | +3.73% | **545** | 50 | **713** | 65 | **0.490** | 0.837 |
| 75% of observed | +2.80% | 970 | 89 | 1273 | 117 | 0.281 | 0.575 |
| 50% of observed | +1.86% | 2152 | 197 | 2842 | 260 | 0.132 | 0.280 |

### 2.2 What this says, plainly

- **ADR-023 ran at about 49% power against the effect it observed.** The experiment was
  a coin flip on whether it could detect its own effect, and p=0.0522 is exactly what a
  coin flip looks like when it lands on the wrong side by a hair. That reframes the
  verdict without changing it: the rule was right to revert, *and* the design could
  never have been trusted to decide either way.
- **This is a design figure, not a retro-diagnosis.** Feeding the observed discordants
  back in and calling the result "the power that run had" is post-hoc power, which is a
  monotone transform of the p-value already reported and therefore says nothing new
  (Hoenig & Heisey 2001). The number above is used to *size the next run*, and it rests
  on an assumption whose consequences are shown across a band.

### 2.3 What "300 more snippets" does and does not buy

This is the question worth being blunt about, because +300 is the natural instinct and
it is only half an answer.

**It buys:** n≈595 effective, and **84% power** if the true effect is exactly what was
observed. That clears the conventional 80% bar and would make a repeat of the ADR-023
result decisive rather than marginal.

**It does not buy:**

1. **Protection against the effect being smaller than it looked.** At 75% of the
   observed lift, n=595 is **58%** powered — worse than a coin flip. And the observed
   effect is systematically the *optimistic* estimate: a result noticed because it
   nearly cleared a threshold is, conditional on being noticed at all, more likely to
   be an overestimate than an underestimate. Powering exactly at the observed point
   estimate is the winner's-curse trap.
2. **A better ruler.** Power is a variance instrument. ADR-023 §2.1 documented *bias* in
   the same answer key — `s024`/`s025` are byte-identical snippets labelled `europe`
   and `middle-east`, the EUCOM cluster answers six same-shaped rows inconsistently, the
   Dahlgren cluster five. Sampling more rows from the same source reproduces that
   inconsistency at the same rate. A larger judge-graded key shrinks the interval
   around a slightly-wrong center; only **human** labels would move the center, and
   that is a labeling project this spec does not open.
3. **Any change to what is being tested.** Same clause, same models, same axes, same
   guardrails. If the clause were also revised, the follow-up would be measuring a new
   thing at higher power rather than the old thing at adequate power.

**So the target is n≈730, not n≈595** — the 90%-at-observed point, which is also ~67%
powered if the true effect is three-quarters of what was seen. The floor below which
the run is not worth making is **n = 545** (80% at observed), and it is enforced in
code, not printed: `region_clause_rerun.report()` refuses beneath it.

### 2.4 The design decision this encodes, stated as a decision

Powering at 90%-of-observed rather than 80% costs roughly 170 extra snippets (~510
extra API calls, ~$2). Powering at 80% *of a 75%-sized effect* would cost n=970 — 675
new snippets and roughly double the spend — and was rejected as disproportionate for a
prompt clause worth 3.7 points on one axis. **That is a judgement about how much this
question is worth, not a statistical necessity**, and it is recorded here so the choice
is visible rather than implied by a number.

## 3. What is measured, and what is deliberately unchanged

The clause is **verbatim** the one ADR-023 ran ([its spec §3](global-boundary-clause.md)),
and this is enforced rather than asserted: `src/region_clause_rerun.py` composes the
candidate prompt and checks `sha256` against
`b0202d06a876cc0641f50e8910368d7c8a4eb0295f662ac472f9fdd6abf4e963`, the fingerprint the
paid ADR-023 run recorded in `evals/region_clause_candidate.provenance.json`. A drift of
one character refuses the run.

**The clause is applied at run time. `classify.SYSTEM_PROMPT` is never edited.** ADR-023's
branch carried the clause in the shipped prompt, which cost it four provenance-pinned
test failures plus a red offline gate (its spec §8 budgeted for exactly that). Here the
composed prompt is passed down the existing call path, so:

- CI on this branch is green, with no waiver and no expected-red table.
- The answer-key pass runs under the **shipped** prompt — mandatory, because
  `classify()` defaults *both* models to `SYSTEM_PROMPT`, so a globally-installed clause
  would have the Opus judge grading the new rows under the very clause being tested
  while the frozen 295 stayed graded under the baseline.
- "Is the clause shipped?" stops being a question about which commit you are standing on.

### 3.1 Cost, and why it is ~3 calls per new snippet rather than ~6

The 295 rows ADR-023 already measured are **reused, not re-bought**: both arms and the
answer key for `s001..s300` are committed artifacts produced by exactly the prompts and
models this run uses. Re-running them would spend ~900 calls to reproduce numbers
already on disk, and would let run-to-run sampling noise move the half of the experiment
that is supposed to be fixed. `assert_frozen_arms_are_still_ours` checks both sidecars
against the live fingerprints before a row is scored, so the reuse is guarded rather
than assumed.

Per **new** snippet: 1 baseline workhorse call + 1 Opus judge call (one pass, via
`gold_eval.run_predictions`) + 1 candidate workhorse call = **3**.

## 4. The extension set

`scripts/extend_scale_set.py`, which **imports** its queries and filters from
`scripts/build_scale_set.py` rather than restating them — a copy could drift, an import
cannot. Same 24 queries, same relevance sort, same title deny-list, same 200-character
minimum, same official DVIDS search endpoint. ADR-015 governs the source and is
unamended: DVIDS is US-government public-affairs work, public domain under 17 U.S.C.
§ 105, retrieved through the API rather than scraped.

**Why the original 300 stopped where it did, and why there is headroom.** The rows land
in exact 25-row blocks with boundaries at every multiple of 25, which is the signature of
`PER_QUERY_KEEP = 25` filling `TARGET = 300` and then breaking out of the query loop.
Twelve queries filled their quota; the tail of the list was never reached, and every
query's results beyond its 25th were never examined.

**The one documented deviation:** the per-query keep cap rises from 25 to the full result
page. Nothing else changes. The consequence is real and named rather than hidden — the
original set is evenly spread across its consumed queries, while the extension leans
toward whichever queries return more usable results. That shifts **topic mix**, not
label definitions, and the combined region distribution is reported by the eval rather
than engineered (the ADR-015 skew argument applies unchanged).

**Exclusions, per precedent, plus one new one:**

| Exclusion | Status | Why |
|---|---|---|
| Corpus + gold DVIDS ids | inherited | The judge must never grade its own validation data. |
| The frozen scale set's DVIDS ids | new | One snippet must not carry two answer-key rows. |
| **Exact-duplicate snippet text** | **new, and the ADR-023 lesson** | That run found four duplicate groups (s022/s023, s024/s025, s078/s079/s080, s239/s240 — nine rows, five redundant) only *after* grading them, and dropped them from the pairing. Here duplicates are removed **before** anything is bought, against both the frozen set and the extension itself. |

New ids continue at `s301`, and the output is a **separate file**
(`data/scale/scale_set_ext.csv`). Appending to `data/scale/scale_set.csv` would silently
redefine what every committed `s001..s300` artifact is a measurement *of*, and would
break `region_clause_ab`'s answer-key completeness guard.

**The ceiling is not knowable before collection.** 24 queries × 60 results is an upper
bound of 1440 raw hits before filters, exclusions and duplicates; the achieved number is
whatever it is. The script prints a `CEILING REACHED` notice when it falls short and
says explicitly not to add queries to hit a number — a widened sampling frame is a
different set, and that is a decision, not a tuning knob.

## 5. Expected collateral — unchanged, and not re-derived

The residual-risk analysis in the first spec (§2.2, §2.3) still stands and is not
repeated here; nothing about the clause or the corpus has changed. The one honest update
is that ADR-023 replaced its estimates with measurements: F was predicted ≤13 and landed
at **12**; B was predicted ≈9 and landed at **7**. Those measured values are the best
available prior for the extension rows, and §6.1 prices the rule against them.

## 6. Pre-registered decision rule *(canonical)*

`F` = named pulls fixed. `B` = currently-correct region rows the clause drags to
`global`. McNemar exact via the repo's own `mcnemar_exact`, over **all** discordant
pairs on the axis — not only over F and B. Effective `n` is post-deduplication.

**Rule 0 — the run does not happen below the power floor.** Effective n must be
**≥ 545**. Enforced by `region_clause_rerun.report()`, which raises rather than scoring.
Below that the design cannot decide the question either way, and spending on it is the
thing the power analysis exists to prevent. **Lowering this floor after seeing the data
is outcome-switching and is forbidden by this document.**

**SHIP the clause** when **all four** hold:

1. **Scale region improves significantly**: net region rows `F − B > 0` with
   **p < 0.05**.
2. **No significant guardrail harm**: neither category nor domain shows a significant
   paired loss (p < 0.05). A **kill condition, not a tiebreak** — ADR-020 is the
   precedent, and its critic fixed a region cluster while doing significant damage to
   domain in the same run.
3. **Gold region does not regress**: human-graded region accuracy ≥ 87.0%, and no gated
   floor in `evals/thresholds.toml` is breached (including `judge_region_agreement`).
   ⚠️ **The 87.0% bar is a MANUAL READ, not a gate** — `thresholds.toml` floors
   `region_accuracy` at 0.78, and no threshold is added by this branch (ADR-007: floors
   come from measured runs, and this run does not exist yet). Labelled rather than
   implied, because an unrun gate is not a pass.
4. **Harness health is clean**: every eligible pair present, nothing dropped or errored.
   Enforced by `assert_complete` on both arms.

**SHIP THE NEGATIVE RESULT** (do not adopt the clause, keep the ADR) when region is flat
or down, or any guardrail shows significant harm, or a floor breaks.

**Call it MARGINAL, and do not adopt**, when region improves but p ≥ 0.05. **At this n
that verdict means something ADR-023's could not**: an adequately-powered miss is
evidence the effect is smaller than it looked, not an unresolved question. That is the
substantive difference between this round and the last one, and it is the reason the
round is worth running.

### 6.1 What the rule survives at the target n

Priced at n = 730 with the discordant structure scaled from ADR-023's measurement
(F = 12, B = 7 on 295 → roughly F = 30, B = 17 on 730, with the same 27/295 discordant
rate):

| Scale | cand-better / base-better | McNemar p | Reading |
|---|---|---:|---|
| ADR-023's exact result, at 2.47× | 47 / 20 | 0.0013 | **ship** |
| Lift 75% of observed | 44 / 23 | 0.0139 | **ship** |
| Lift 60% of observed | 42 / 25 | 0.0498 | ship *(barely)* |
| Lift 50% of observed | 40 / 27 | 0.1421 | **marginal → do not adopt** |
| Lift 33% of observed | 38 / 29 | 0.3284 | **marginal → do not adopt** |

**The honest limits, stated before the run:**

- **A repeat of ADR-023's exact result ships comfortably** (p = 0.0011). That is the
  whole purpose of the higher-power ruler, and it is why the round is worth its cost.
- **The rule now bites at about 60% of the observed effect.** Anything weaker than that
  fails, which is the correct behavior: an effect half the size of the one measured is
  not what the clause was justified on.
- **The answer key's self-inconsistency is unchanged and does not shrink.** ADR-023 §2.1
  found ~6 rows the key answers inconsistently in 295; a proportional extension carries
  roughly 15 in 730. More n does not fix that, and a result sitting inside that band is
  still hard to distinguish from the ruler disagreeing with itself. What changes is that
  the *sampling* margin is no longer the binding constraint.
- **The guardrails remain more sensitive than they look**: on a larger n a smaller
  percentage move clears p < 0.05 on category or domain, so guardrail harm is *more*
  likely to be detected, not less. That is the kill condition working.
- **The unexplained domain result is registered, or it does not count.** ADR-023 saw
  domain move +3.7% at p = 0.0192 on an axis the clause says nothing about, and recorded
  it as an observation rather than banking it. It remains a **guardrail** here.
  Registering it as a second hypothesis would need its own rule and its own justification
  written before the run; this spec deliberately does not do that, so an improvement on
  domain still cannot contribute to shipping. Reading an unregistered gain as support is
  precisely the outcome-switching the pre-registration exists to prevent.

## 7. Run protocol (owner-driven — nothing here is launched from a session)

Every command from the repo root. **Step 1 is free.** Steps 2–3 spend; the counts scale
with the achieved extension size `k`.

### Run status *(record of what has happened — the rules above are unchanged)*

**Steps 1–4 ran on 2026-08-02, owner-driven** (PR #164). The report is committed at
[`evals/region_clause_rerun.txt`](../../evals/region_clause_rerun.txt) and is the source
for every number here.

| | Achieved |
|---|---|
| Effective n (post-deduplication) | **595** (295 frozen + 300 extension, 5 exact duplicates excluded) |
| Design power at the observed effect | **0.837** |
| Scale region, baseline → candidate | 89.9% → **94.1%** (**+4.2%**) |
| Region discordants (cand / base) | **35 / 10**, **McNemar p = 0.0002** |
| Category (guardrail) | +0.7%, p = 0.4807 — flat |
| Operational domain (guardrail) | +3.5%, p = 0.0011 — an *improvement* |
| Named pulls fixed / correct rows broken | **F = 20** of 32, **B = 8** |
| Harness health | clean: 595 groups / 595 pairs / 595 eligible on all three axes |

| Rule (§6) | Status |
|---|---|
| 0. Effective n ≥ 545 | ✅ **passes** (595) |
| 1. Region `F − B > 0` and p < 0.05 | ✅ **passes** (+12 net, p = 0.0002) |
| 2. No significant guardrail harm | ✅ **passes** (kill condition never fired) |
| 3. Gold region ≥ 87.0%, no gated floor breached | ✅ **passes** (92.6%; all eight floors clear) |
| 4. Harness health clean | ✅ **passes** |

**Step 5 ran 2026-08-03** through the guarded `--run-gold` path — 54 workhorse calls, zero
judge calls, nothing published written. Human-graded region **87.0% → 92.6%** (47/54 →
50/54) against the pre-registered 87.0% bar. Report:
[`evals/region_clause_gold_rerun.txt`](../../evals/region_clause_gold_rerun.txt).

**Rule 3's second half was answered at adoption**, as §7 step 5 said it had to be: the clause
entered `SYSTEM_PROMPT`, the full gold record was re-run (workhorse *and* judge, 108 calls),
and `src/eval_gate.py` graded all eight floors under the adopted prompt. **All pass, none
moved or waived.** `judge_region_agreement` — the floor this rule names explicitly — fell
100.0% → **96.3%** against its 0.93 floor, i.e. 2 judge-vs-human disagreements against a
budget of 3. That is the number that would have stopped the release.

**VERDICT: all four rules pass → SHIP.** The clause is adopted, `SYSTEM_PROMPT` moves
`a59689e8…` → `b0202d06…`, and the version is `v3.2.1` (PATCH) exactly as §9 planned. The
adoption record, including the §9 marker cascade, is
[ADR-024](../../decisions/archive/024-global-boundary-clause-adopted.md).

**The domain improvement is recorded, not banked** — §6.1's registration rule is
unchanged and an unregistered gain still cannot contribute to shipping.

**Step 5 is the only outstanding work, and its procedure was rewritten** on 2026-08-03
after the original instruction ("run ADR-023 spec §7 step 2 verbatim") was found to be
both destructive and uninformative under this spec's own §3 design. Step 5 below carries
the correction and the reasoning. **No pre-registered rule, threshold, power floor, or
verdict wording was changed** — only the procedure that answers rule 3.

### Step 0 — free pre-checks

```bash
uv run python src/mcnemar_power.py
uv run --env-file .env python scripts/cache_diagnostics.py
uv run --env-file .env python scripts/cache_diagnostics.py --model claude-opus-4-8
```

The cache checks need a key but make no billed call (`count_tokens` is free). **Run both
— the default reports the workhorse only, and the judge's prefix is a different size**
(token counts are model-specific). Read the `gap to floor` line on each; both should say
`caching is ACTIVE` before ~1300 calls are placed.

> **Corrected 2026-08-02 — "caching is a no-op on the judge passes" was wrong, and is now
> disproven by measurement.** It rested on a stale floor: `MIN_CACHEABLE_PREFIX_TOKENS`
> recorded Opus 4.8 at 4096 tokens, so the prefix looked like it could never cache. Two
> independent corrections landed:
>
> 1. **The published floor.** Re-fetched from
>    [Anthropic's prompt-caching docs](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching),
>    **Opus 4.8's floor is 1024**, as is Sonnet 5's — not 4096.
> 2. **A live measurement on the judge model itself**
>    (`scripts/cache_diagnostics.py --live --model claude-opus-4-8`, run 2026-08-02):
>    `call 1: cache_creation=3625, cache_read=0` → `call 2: cache_creation=0,
>    cache_read=3625`. **Prompt caching engages on the Opus judge.** Note this run
>    cached at **3625 tokens — below the 4096 the old table claimed as the floor** — so
>    the measurement disproves the stale value on its own, without appeal to the docs.
>
> The judge was never a separate call shape to begin with: `gold_eval.py` reaches it via
> `classify_retry(..., JUDGE_MODEL)`, i.e. `classify()`'s own `cache_control`-marked
> system block with only the model swapped. The no-op line was an inference from the bad
> floor, never an observation.
>
> **The prefix is ~3700–3764 tokens, not ~2425 — on both models.** Measured 2026-08-02:
> **3764** on Sonnet 5, **3700** on Opus 4.8. The ~2425 figure quoted throughout this repo
> dates from **v2.1.0 (2026-07-17)** and was obsoleted the very next day by **v3.0.0**,
> which added the `region` label and its boundary rubric to `SYSTEM_PROMPT`. It has been
> stale in the prose ever since.
>
> The 64-token spread between the two models is ordinary tokenizer variation (~1.7%), not
> a meaningful difference — an earlier revision of this block claimed the gap was ~50% and
> model-specific, which the measurement above refutes. **The lesson is the simpler one:
> prefix size tracks the prompt, so any prompt edit invalidates every quoted figure.**
> Re-run step 0 rather than citing a number from prose — including this one.

### Step 1 — collect the extension (free; DVIDS, no LLM call)

```bash
uv run --env-file .env python scripts/extend_scale_set.py --target 435
```

Needs `DVIDS_API_KEY` (the public read-only key, already in `.env.example`). Refuses to
overwrite an existing extension. **Read the output**: if it prints `CEILING REACHED`,
stop and check the achieved n against Rule 0 before spending anything.

### Step 2 — extend the answer key (2k calls)

```bash
uv run --env-file .env python src/region_clause_rerun.py --run-key --batch
```

Workhorse + Opus judge over the new snippets only, under the **shipped** prompt, through
`gold_eval.run_predictions` unchanged. Resume-safe; a resume across a prompt or model
change is refused rather than blended.

### Step 3 — the candidate arm on the new snippets (k calls)

```bash
uv run --env-file .env python src/region_clause_rerun.py --run-candidate --batch
```

Workhorse only, under the composed clause prompt. Refuses before building a client if
the composed prompt is not ADR-023's.

### Step 4 — report (free, offline, repeatable)

```bash
uv run python src/region_clause_rerun.py --report
```

### Step 5 — the gold arm, only if steps 2–4 clear rule 1

**Deliberately deferred, and that is a change from the ADR-023 round.** Last time the
gold arm was run alongside the scale arm and cost 108 calls plus a delete-and-restore
dance across the published `evals/gold_predictions_v3.csv`, whose numbers five repos'
markers hang off — for an arm that could not decide anything on its own at n=54. Rule 3
is a *non-regression* check on the human labels, so it only has to be answered if rule 1
passes.

```bash
uv run --env-file .env python src/region_clause_rerun.py --run-gold
uv run python src/region_clause_rerun.py --gold-report
```

**54 workhorse calls. Zero judge calls. Nothing published is written.** Add `--batch`
for the ~50% discount if an unattended run is preferred; at n=54 the synchronous path
is usually the better trade, because batch results land only when the whole batch ends.

**Cost: ≈$0.32 synchronous, ≈$0.16 batch** — derived from this spec's own per-call rate
below (870 Sonnet 5 workhorse calls at $5.15 sync / $2.60 batch), so it inherits the
same caveats: the ~2425-token prefix sizing is stale-low and caching is not banked, and
those push in opposite directions. Under $0.50 either way. `--gold-report` is free and
repeatable.

#### Why this step was rewritten *(procedure only — the rule in §6 is untouched)*

The earlier text said to run "the ADR-023 spec's §7 step 2 verbatim, including its undo
line". **That instruction was written for a design that no longer exists, and following
it here would have been destructive and uninformative at the same time.** ADR-023's arm
lived inside `classify.SYSTEM_PROMPT` on a branch, so deleting the published gold record
and re-running `src/gold_eval.py` genuinely measured the candidate — the shipped prompt
*was* the candidate prompt on that checkout. §3 of this spec replaced that with run-time
clause application, and step 5 was never updated to match. On `main`, verbatim, it would:

1. **Delete `evals/gold_predictions_v3.csv` and its sidecar** — the published v3.2.0
   record, restored only by a hand-typed `git checkout --` that an aborted run leaves
   unrun. A convention, not a guard.
2. **Spend ~108 calls** — `gold_eval.main()` re-runs the workhorse *and* the Opus judge.
3. **Measure the BASELINE.** `main`'s `SYSTEM_PROMPT` carries no clause, and neither
   `src/gold_eval.py`'s CLI (`--batch` only) nor `src/region_clause_rerun.py`'s
   (`--run-key`, `--run-candidate`, `--report`) had any way to point a gold pass at the
   clause-applied prompt. The run would have answered nothing about the clause.

The corrected protocol fixes all three, and each fix is enforced in code rather than
written down:

- **The clause, pinned.** `--run-gold` composes the candidate prompt through the same
  run-time mechanism `--run-candidate` uses, under the same `sha256` pin to
  `b0202d06…`, plus `assert_prompt_carries_the_clause` on the exact string going on the
  wire. The report side refuses a candidate arm whose sidecar records the shipped
  prompt, so "this cannot run under the shipped prompt" holds end to end.
- **The published record is unwritable.** `assert_writable_gold_artifact` refuses any
  destination resolving to `gold_predictions_v3.csv`, its sidecar, `gold_eval_v3.txt`,
  `metrics.json`, or ADR-023's frozen gold arm. **There is therefore no undo line, and
  the one that used to be here is deleted rather than reworded** — a restore step is
  only needed by a protocol that breaks something first. New artifacts, in the
  `region_clause_gold_*` family ADR-023 established for paid gold data, with this
  round's `_rerun` suffix: `evals/region_clause_gold_rerun.csv`, its
  `.provenance.json`, and `evals/region_clause_gold_rerun.txt`.
- **54 calls, not 108.** Rule 3's answer key is the **frozen human labels** in
  `data/gold/gold.csv`, which no API call produces. ADR-023's 108 came from `gold_eval`
  re-running a judge pass; the judge is a *scalable stand-in* for human labels and is
  simply not needed where the human labels themselves are the ruler. The pass runs
  through `region_clause_ab.run_workhorse`, which has no judge request to build, and a
  test pins that no call carries `JUDGE_MODEL`.

#### What the report says, and what it deliberately does not

`--gold-report` prints candidate human-graded region accuracy against the published
87.0% baseline, the per-claim fixed/broken id lists, the human-graded named-`global`
cluster accounting, and category/domain as **secondary context, not gates** — the
pre-registered guardrail test is rule 2 and it runs on the scale arm, where it has power.

**Rule 3's second half — "no gated floor in `evals/thresholds.toml` is breached,
including `judge_region_agreement`" — is an adoption-time question, and this arm cannot
breach it.** `src/eval_gate.py` grades those floors against
`evals/gold_predictions_v3.csv`, the published record produced by `classify.SYSTEM_PROMPT`,
which this measurement leaves byte-identical; `judge_region_agreement` is a judge-vs-human
number no call here produces. Those floors can only move when the clause enters
`SYSTEM_PROMPT` and the full gold re-run happens — see §9.

**Context the report also prints, and which is worth reading before spending.** ADR-023's
paid gold arm ran this **byte-identical** clause over these **same 54 rows** and scored
**94.4%** region against the human labels; rule 3 passed there. That arm is frozen at
`evals/region_clause_gold_candidate.csv` and is not re-bought. So step 5 is an
*independent confirmatory draw*, not the only evidence available — and a disagreement
between the two should be read as n=54 sampling noise before it is read as an effect.
Whether that prior arm alone is sufficient to answer rule 3 for this round is an owner
call this spec does not make: it has no provenance sidecar (ADR-023 §*Where the
candidate's gold numbers live* explains why), so its reuse can be argued but not
*guarded*, and this repo's practice is guarded reuse.

### Step 6 — free verification

```bash
uv run pytest
uv run ruff check .
uv run black --check .
uv run mypy src
```

### Cost, as an estimate

At the target `k = 435` new snippets: **1305 calls** — 870 Sonnet 5 workhorse (baseline
+ candidate) and 435 Opus 4.8 judge. Sizing at the repo's measured ~2425-token cacheable
prefix plus a ~180-token snippet and ~60 output tokens per call, with the Batches API's
50% discount and **no cache discount assumed**:

> **Two corrections to the table's inputs, 2026-08-02 — both left un-recomputed on
> purpose, because they push in opposite directions and the net is favorable.** (a) The
> ~2425-token prefix is a **v2.1.0** measurement, obsoleted by v3.0.0's region rubric; the
> real size is **~3700–3764 on every row**, so *all three* rows understate input tokens by
> ~50%, not just the judge. (b) Caching is now **measured working** on both models (step
> 0), and the table assumes none. A cache read bills at roughly a tenth of base input
> against a prefix that is ~95% of each call's input — so (b) dominates (a) by a wide
> margin and the totals should come in **under** $5.75, not over. The numbers stay as
> written because a spend ceiling is more useful honest-and-high than re-derived from two
> estimates.

| | Calls | ≈ Cost (batch) | ≈ Cost (synchronous) |
|---|---:|---:|---:|
| Sonnet 5 workhorse ×2 arms | 870 | $2.60 | $5.15 |
| Opus 4.8 judge | 435 | $3.15 | $6.30 |
| **Total** | **1305** | **≈ $5.75** | **≈ $11.45** |

**These are estimates**, and three things move them: Sonnet 5's introductory rate expires
2026-08-31 (after which the Sonnet half rises ~50%), the snippet-length distribution is
long-tailed (median 327 characters, mean 633), and the token estimate is a calculation
rather than a measurement — `scripts/cache_diagnostics.py` in step 0 is the free way to
tighten it. ADR-023 spent 408 calls for its verdict; this is ~3.2× that, and the power
analysis is the argument for why.

**The table is an upper bound, and the cache is the reason.** Every call in it — both
arms and the judge — carries the same `cache_control`-marked prefix, measured 2026-08-02
at ~3764 tokens on Sonnet 5 and ~3700 on Opus 4.8. That prefix is ~95% of each call's
input; the per-call variable part is only the ~180-token snippet. It clears every floor
involved, caching is **measured working on both models** (step 0), and a cache read bills
at roughly a tenth of base input. So the *input* side of every line above should fall by
most of its value: the ~1300 calls pay the full prefix once per cache window rather than
1300 times.

**Do not bank the saving in advance.** What step 0 proves is that the prefix *can* cache
— two back-to-back identical probes hit. It does not prove a 1300-call production run
will hit at that rate: the 5-minute ephemeral TTL and the Batches API's scheduling make
hit rate a property of how the run is actually dispatched, and a batch spread across
windows re-pays the write each time. That is why the table keeps its no-discount
numbers. Budget them, treat the discount as recovered margin, and **read
`cache_read_input_tokens` off the actual run** — the remaining open question is not
*whether* the prefix caches but *what fraction of 1300 dispatched calls hit*, and only
the run itself answers that.

## 8. Explicitly NOT in this branch

No merge of a prompt change · no `SYSTEM_PROMPT` edit · no version bump · no
`thresholds.toml` change · no metrics regeneration · no gold-set edit · no
frozen-artifact change · no answer-key relabelling · no provenance waiver · no ADR (spec
first, ADR at verdict — the ADR-017/ADR-023 pattern) · **no live API call**.

## 9. What the post-run session does

### If the clause ships

1. ADR-024 recording the verdict, with a `## Downstream surfaces` section
   (`scripts/lint_decisions.py` enforces it on new ADRs).
2. **A decision this spec does not pre-empt:** shipping means moving the clause into
   `classify.SYSTEM_PROMPT`, which changes the prompt fingerprint and forces the full
   gold re-run plus the published-marker cascade in `docs/v3.2.0-release-runbook.md` —
   with runbook item 25's verified-negative **void**, because gold values would move.
   Version → `3.2.1` (PATCH).
3. Amend ADR-023 with a pointer rather than editing its verdict: it recorded a true
   finding about a design that could not decide, and rewriting it would erase the
   measure-first record this repo is built on.

### If the result is negative or marginal

1. ADR-024 recording it — the seventh measure-first data point, and the first where the
   *design* was adequate. That is a materially stronger negative than ADR-023's, and the
   ADR should say so.
2. No version bump, no marker cascade, no threshold change, no revert to perform: the
   clause never entered `SYSTEM_PROMPT`, which is the design's second dividend.
3. The extension set stays. It is a bigger ruler for whatever is measured next, and it
   cost nothing but the collection.
