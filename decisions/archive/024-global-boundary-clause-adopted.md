# ADR-024: The `global`-boundary prompt clause — re-run at adequate power, and adopted

**Status:** Accepted — verdict recorded 2026-08-03: **all four pre-registered rules pass, clause adopted**
**Date:** 2026-08-03
**Deciders:** San Lee

**Related:** [ADR-023](023-global-boundary-clause-verdict.md) (the same clause, measured at
n=295 and **reverted** at p=0.0522 — amended with a pointer to this record, its body left
verbatim) · [spec](../../docs/specs/global-boundary-clause-rerun.md) (canonical pre-registration,
§6 decision rule, §7 run protocol, §9 the adoption path this ADR executes) ·
[ADR-022](022-scaled-region-eval-verdict.md) (the n=300 ruler this extends to n=595) ·
[ADR-014](../014-region-field-design.md) (the ratified region conventions the clause restates) ·
[ADR-020](020-l4-multi-agent-pipeline.md) (the declined critic — the alternative fix at ~4×
cost, and the overcorrection precedent sentence 2 of the clause exists to prevent) ·
[ADR-007](../007-evals-as-ci-gate.md) (floors come from measured runs) ·
[ADR-015](../015-public-domain-data-sourcing.md) (why the extension snippets could be collected
at all)

---

## Context

ADR-023 measured this clause and declined it. Region moved the right way on both rulers — scale
88.5% → 92.2%, human-graded gold 87.0% → 94.4% with all seven named misses fixed — and the
guardrails were clean. It still reverted, because **McNemar landed at p=0.0522 against a
pre-registered p<0.05**, and the rule's own text says a marginal result reverts.

That ADR then named the one thing that would change the answer: *"A higher-power ruler, and
essentially nothing else."*

**The honest lesson, and it is not the one that flatters the first run.** `src/mcnemar_power.py`
turned that sentence into arithmetic, and the answer was uncomfortable: **ADR-023 ran at about
49% power against the effect it observed.** The experiment was a coin flip on whether it could
detect its own effect. p=0.0522 is exactly what a coin flip looks like when it lands on the
wrong side by a hair.

So the reversal recorded here is **not** "the rule was wrong." The rule was right, and honoring
it was right. What was wrong was the **design**: n=295 could never have decided this question
either way, and the correct reading of ADR-023 is *underpowered*, not *refuted*. A repo whose
thesis is measure-first has to be able to say that about its own completed experiment without
either renegotiating the old threshold or pretending the old verdict was a mistake. Both records
stand, each correct on its date.

### What was re-registered, and what was deliberately held fixed

The spec is a genuine pre-registration: §6 was written before any number existed and is
**unchanged since**. Held fixed from ADR-023, on purpose: the same clause (pinned by `sha256` to
`b0202d06…`, so a one-character drift refuses the run), the same models, the same axes, the same
guardrails, the same p<0.05. Only the ruler grew.

Two new things the design added, both of which paid off:

- **A power floor enforced in code, not printed.** Rule 0 refuses to score below **n=545** — the
  80%-at-observed point. Lowering it after seeing the data is outcome-switching, and the spec
  forbids it in writing.
- **Duplicate snippet text removed *before* anything was bought.** ADR-023 found four duplicate
  groups only after grading them. Five redundant rows were excluded here up front, which is why
  the effective n is 595 rather than 600.

## Decision

**The clause is adopted.** `classify.SYSTEM_PROMPT` now carries it, inside the region-rules
block, immediately after the "concrete identifiable location" bullet:

> - A US institution is not an American theater. Naming a service, command, program office,
>   contractor, unit, or official identifies the actor, not a place: a story whose only geography
>   is institutional has no anchor, so it is global rather than americas. This does not narrow
>   the evidence above -- a named command's or fleet's area of operations or responsibility names
>   a theater, and so do a named base, installation, city, country, or body of water, wherever
>   the story places the activity.

Sentence 1 is the fix, narrowed to institutional-only geography after an adversarial review
returned FIX FIRST on the first draft. Sentence 2 is the anti-overcorrection gate, and ADR-020
is the measured precedent for why it has to be there.

**The shipped prompt now hashes to `b0202d06a876cc0641f50e8910368d7c8a4eb0295f662ac472f9fdd6abf4e963`
— byte-for-byte the candidate arm that was measured.** That is pinned by a test rather than
asserted here, so what ships is the arm the 595-row report describes and not a retyping of it.

### The four rules, with their measured values

Full report: [`evals/region_clause_rerun.txt`](../../evals/region_clause_rerun.txt) (scale arm) and
[`evals/region_clause_gold_rerun.txt`](../../evals/region_clause_gold_rerun.txt) (gold arm).

| Rule (spec §6) | Bar | Measured | Verdict |
|---|---|---|---|
| **0.** Effective n ≥ 545 | 545 | **595** (295 frozen + 300 extension − 5 duplicates) | ✅ |
| **1.** Region `F − B > 0`, p < 0.05 | p < 0.05 | **+12 net**, discordants **35/10**, **p = 0.0002** | ✅ |
| **2.** No significant guardrail harm | no significant paired loss | category +0.7% p=0.4807; domain **+3.5% p=0.0011** (an improvement) | ✅ |
| **3.** Gold region ≥ 87.0%, no gated floor breached | 87.0% | **92.6%** (50/54) human-graded; all eight floors pass | ✅ |
| **4.** Harness health clean | every pair present | 595 groups / 595 pairs / 595 eligible, all three axes | ✅ |

Design power at this n, computed **before** the numbers: **0.837** against the observed effect
(0.575 if the true effect is three-quarters of it). ADR-023's was 0.490.

### Arm 1 — scale (the primary ruler, effective n=595)

| Axis | Baseline | Candidate | Lift | cand/base/tie | McNemar p |
|---|---|---|---|---|---|
| **region** (target) | 89.9% | **94.1%** | **+4.2%** | 35 / 10 / 550 | **0.0002** |
| category (guardrail) | 93.4% | 94.1% | +0.7% | 11 / 7 / 577 | 0.4807 |
| operational_domain (guardrail) | 89.4% | 92.9% | +3.5% | 30 / 9 / 556 | 0.0011 |

The named cluster, priced exactly as the rule prices it: **F = 20** of 32 named pulls fixed
(62%), **B = 8** correct rows dragged to `global`, net region rows 535/595 → **560/595** (+25).

**A repeat of ADR-023's result at 2× the ruler is what happened, and it is decisive rather than
marginal.** §6.1 priced this in advance: at the observed effect the rule ships at p≈0.0013, and
it bites at about 60% of that effect. The measured p=0.0002 is comfortably inside.

### Arm 2 — gold (the human-graded non-regression check, n=54)

Rule 3's answer key is the **frozen human labels**, which no API call produces. Run through the
guarded `--run-gold` path: **54 workhorse calls, zero judge calls**, nothing published written.

| Measure | Baseline (published v3.2.0) | Candidate |
|---|---|---|
| **Region accuracy** | 87.0% (47/54) | **92.6%** (50/54) |
| Category accuracy | 92.6% | 94.4% |
| Operational domain accuracy | 92.6% | 90.7% |

Six of the seven named `global` pulls fixed (g017, g019, g026, g047, g048, g054); g013 still
pulled; two correct rows dragged to `global` (g024, g037) and one moved region (g030).

**Rule 3 is a non-regression check by design: it can veto the clause, it cannot carry it.** n=54
is the small ruler ADR-022 exists to supplement. Note also that ADR-023's paid gold arm scored
**94.4%** on these same 54 rows with this byte-identical clause; the 1.8-point gap between the
two draws is n=54 sampling noise, and reading it as an effect would be over-reading.

### The gold re-run under the adopted prompt, and the eight floors

Adoption changes the prompt fingerprint, which forces a full re-run of the published gold record
(workhorse **and** judge — `judge_region_agreement` is a gated floor and had to be re-measured
under the adopted prompt, not inherited).

**All eight gated floors pass, as written. None was moved, waived, or added.**

| Gated metric | Floor | v3.2.0 (published) | v3.2.1 (adopted) | Result |
|---|---|---|---|---|
| `category_accuracy` | 0.83 | 92.6% | **94.4%** | PASS |
| `category_macro_f1` | 0.85 | 0.911 | **0.930** | PASS |
| `domain_accuracy` | 0.83 | 92.6% | **98.1%** | PASS |
| `domain_macro_f1` | 0.83 | 0.933 | **0.982** | PASS |
| `judge_category_agreement` | 0.83 | 92.6% | **94.4%** | PASS |
| `judge_domain_agreement` | 0.88 | 98.1% | **92.6%** | PASS |
| `region_accuracy` | 0.78 | 87.0% | **94.4%** | PASS |
| `judge_region_agreement` | 0.93 | 100.0% | **96.3%** | PASS |

**`judge_region_agreement` was the floor to watch, and it is the one that moved most.**
It floors at 0.93 — at n=54 that is a budget of **at most 3** judge-vs-human disagreements — and
it fell from a perfect 100.0% to **96.3%, i.e. 2 disagreements**. One inside the budget, and the
clause ships. Two things are worth saying about that rather than filing it as a pass:

1. **It is expected, not alarming.** `classify()` defaults *both* models to `SYSTEM_PROMPT`, so
   the clause is now in the Opus judge's prompt as well as the workhorse's. A perfect 100.0%
   agreement at n=54 was always a wide interval — ADR-022 said so when it used this figure as
   the gate for scaling — and 96.3% is well inside it.
2. **This is the floor that had real authority over this decision.** If it had broken, the clause
   would not have shipped, and the pre-registration says so in §6 rule 3. Recording it as "the
   one that nearly mattered" is more honest than recording eight uniform PASSes.

Note also that **`judge_domain_agreement` fell 98.1% → 92.6%** even as domain *accuracy* rose
92.6% → 98.1%. The workhorse got better on domain and the judge agreed with the humans less;
both stay above their floors, and neither is explained here. It is a second unexplained
observation on the same axis as the one below, and it is registered as an open question rather
than a result.

### The domain improvement is recorded, not banked

`operational_domain` moved +3.5% at p=0.0011 on an axis the clause says nothing about —
reproducing ADR-023's unexplained +3.7% at p=0.0192. It is registered as a **guardrail**, and
§6.1's rule is explicit: an unregistered gain cannot contribute to shipping. So it contributed
nothing to this verdict, the kill condition simply never fired.

It is now the most interesting thing in the repo that nobody has explained. Two rounds at
different n have both seen it, which makes "~15 rows moved by chance" a much weaker story than it
was at ADR-023. Re-testing it would need its own pre-registration and its own rule, written before
the run. This ADR does not open that.

## Consequences

- **The shipped classifier changes behavior for the first time since v3.0.0.** Same single call,
  same models, same `{category, operational_domain, region}` contract — one more bullet in the
  region rubric. **PATCH (`v3.2.1`)**: no new capability, no contract change, just more correct.
- **The published gold numbers move**, and with them every marked figure across the fleet. This
  is the first release since the marker chain existed where `gold` values actually change, so
  the v3.2.0 runbook's item-25 verified-negative ("16 markers stay green") is **void** — the
  cascade is real this time.
- **The named `global` cluster is closed as far as a prompt clause can close it.** 20 of 32 named
  pulls fixed on the scale ruler, 6 of 7 on the human one. The residual 12 are not a mystery
  either; they are listed by id in the report.
- **Measure-first is now seven-for-seven, and this is the first *adoption*.** ADR-012, ADR-013,
  ADR-018, ADR-019, ADR-020 and ADR-023 all declined a change with data. This one ships a change
  with data, at a pre-registered bar, and that asymmetry mattered: the rule that reverted this
  exact clause three weeks of measurement ago is the reason its adoption means anything.
- **The measurement machinery goes dormant, and says so.** `src/region_clause_rerun.py` now
  refuses every run and report entry point once the clause is in `SYSTEM_PROMPT`. Both arms of
  both rulers were bought against the pre-adoption baseline (`a59689e8…`), which the tree no
  longer contains, so nothing can honestly re-derive the comparison. The committed reports are
  frozen records, read rather than regenerated — the same treatment ADR-023 gave
  `evals/region_clause_ab.txt` when the verdict went the other way.
- **The specific trap that refusal closes.** After the adoption re-run,
  `evals/gold_predictions_v3.csv` is produced *by* the clause prompt, so
  `assert_gold_baseline_is_the_shipped_arm` would pass and `--gold-report` would compare the
  candidate arm against itself and print a 0.0-point lift as though it had measured something.
- **The cost, stated:** 1305 calls for the scale arm and extension, 54 for the gold arm, 108 for
  the adoption re-run. ADR-023 spent 408 for the negative that made this run worth designing.

## Alternatives considered

- **Keep the revert and treat ADR-023 as settled.** Rejected: the ADR itself named the condition
  for re-testing, and declining to meet a condition you wrote down is the same failure as
  renegotiating a threshold you wrote down, in the other direction.
- **Re-run the original 295 rows instead of extending.** Rejected in the spec, before any number:
  a second run of the same rows against the same frozen key is not more power, it is a coin
  flipped twice with the same bias.
- **Power at 80% of a 75%-sized effect (n=970).** Rejected as disproportionate — roughly double
  the spend for a prompt clause worth ~4 points on one axis. Recorded as a judgement about what
  the question is worth, not as a statistical necessity.
- **Also register the domain improvement as a second hypothesis, now that two rounds have seen
  it.** Rejected: registering a hypothesis after seeing it twice is not registering it. It needs
  its own rule written before its own run.
- **Revise the clause to also fix the 12 residual pulls.** Rejected as unmeasured and as
  overfitting: a clause fitted to the rows it missed on the ruler it was scored against would
  need its own pre-registration and its own paid run to mean anything.
- **Rewrite ADR-023's verdict now that the clause ships.** Rejected. It recorded a true finding
  about a design that could not decide, and rewriting it would erase the measure-first record
  this repo is built on. It gets a dated **pointer** to this ADR; its body stays verbatim.

## Downstream surfaces

Touched by this change:

- `src/classify.py` — `SYSTEM_PROMPT` carries the clause; fingerprint `a59689e8…` → `b0202d06…`.
- `src/region_clause_rerun.py`, `tests/test_region_clause_rerun.py`,
  `tests/test_region_clause_ab.py` — the harness goes dormant behind
  `assert_the_clause_has_not_shipped_yet`; two pins **inverted** (the clause is now *in* the
  shipped prompt) and three added for the refusal. Guard coverage is preserved rather than
  deleted: a `pre_adoption` fixture reconstructs the baseline by stripping the clause and
  verifies it against `PRE_ADR024_BASELINE_PROMPT_SHA256`.
- **The published gold record, re-run under the adopted prompt:**
  `evals/gold_predictions_v3.csv` + its provenance sidecar, `evals/gold_eval_v3.txt`,
  `evals/gold_confusion_v3*`, `evals/metrics.json`, and the generated README metrics block.
- **New frozen records:** `evals/region_clause_gold_rerun.csv`, its `.provenance.json`, and
  `evals/region_clause_gold_rerun.txt` (the rule-3 arm).
- `pyproject.toml` → `3.2.1`, `src/api.py` version string,
  `tests/test_metrics_artifact.py`'s pinned literal + its measured-at docstring, `CHANGELOG.md`,
  `decisions/README.md`, `CLAUDE.md`, `HANDOFF.md` (job 2 → **closed as ADOPTED**, recording the
  revert-then-adopt arc rather than erasing the revert).
- `docs/specs/global-boundary-clause-rerun.md` — run status and §9 outcome.
- `README.md` — the generated metrics block plus the prose that described the clause as reverted.
- **Across repos** (each its own PR, in dependency order, after this repo's `metrics.json` is on
  `main`): **architecture** `program/README.md` (`version:classifier` → 3.2.1 and the marked gold
  metrics), **portfolio** (the homepage stat strip and the classifier project page, asserted by
  `scripts/check-published-metrics.cjs`), **learning-notes** `03-reading-the-numbers.md` (six
  markers), **kb-agent** `kb/projects/defense-news-classifier.md` (then `ingest.py --accept` and
  `index.py`).

Deliberately **not** touched:

- `data/gold/*` and every frozen v2/v3 record. The answer key was **not** relabelled — including
  the s024/s025 contradiction and the EUCOM/Dahlgren clusters ADR-023 documented. An experiment
  does not get to edit its own ruler, and an adopted one does not either.
- `evals/thresholds.toml` — **no floor was moved, waived, or added.** The eight floors were
  re-graded under the adopted prompt and passed as written. Moving one to accommodate this change
  would have been the whole failure mode ADR-007 exists to prevent.
- ADR-023's body, and every other ADR's body. Decision records are amended with pointers, not
  rewritten.
- `evals/region_clause_ab.txt` and ADR-023's frozen `region_clause_*` arms.
- The `{category, operational_domain, region}` contract and
  `contracts/classify-response.schema.json` — untouched, which is what makes this a PATCH.

Still deliberately open:

- **The unexplained domain improvement**, seen twice now. Needs its own pre-registration.
- **The 12 residual named pulls** on the scale ruler, listed by id in the report.
- **The answer key's self-inconsistency**, unchanged by more rows. Only human labels move the
  center of that ruler, and that remains a labeling project nobody has scheduled.
