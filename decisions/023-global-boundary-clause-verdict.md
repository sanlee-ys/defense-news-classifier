# ADR-023: The `global`-boundary prompt clause — measured, marginal, and reverted

**Status:** Accepted — verdict recorded 2026-08-02: **marginal (p=0.0522), clause reverted**
**Date:** 2026-08-02
**Deciders:** San Lee

> **Amendment 1 (2026-08-03) — pointer only; nothing below is edited.**
> The condition this ADR named for re-testing ("a higher-power ruler, and essentially nothing
> else") was met. The same clause, byte-identical and pinned by digest, was re-registered and
> re-run at **effective n=595** and cleared all four rules — region 89.9% → 94.1% at **McNemar
> p=0.0002**, design power 0.837 — and **has been adopted** into `classify.SYSTEM_PROMPT` as
> `v3.2.1`. See **[ADR-024](024-global-boundary-clause-adopted.md)**.
>
> **This record is not superseded and is not wrong.** Its verdict was correct on its date and
> under its design: at p=0.0522 against a pre-registered p<0.05, marginal reverts. What ADR-024
> adds is the reason the question was still open — this run had about **49% power** against the
> effect it observed, so it was never able to decide either way. The finding was *underpowered*,
> not *refuted*, and honoring the rule here is what made the adoption there mean anything. The
> body below stays verbatim, deliberately.

**Related:** [ADR-022](022-scaled-region-eval-verdict.md) (the n=300 ruler this was measured
against, and the cluster counts) · [ADR-014](014-region-field-design.md) (the ratified region
conventions the clause restated) · [ADR-020](020-l4-multi-agent-pipeline.md) (the declined
critic — the alternative fix, and the restraint-in-a-prompt cautionary tale) ·
[ADR-019](019-knn-exemplar-fewshot.md) / [ADR-013](013-decline-tiered-routing.md) /
[ADR-012](012-retire-bm25-grounding.md) (the measured-and-declined precedents this joins) ·
[ADR-018](018-agent-driven-ml-loop.md) (rung 2's C-veto — the same discipline, one rung down) ·
[ADR-007](007-evals-as-ci-gate.md) (floors come from measured runs) ·
[spec](../docs/specs/global-boundary-clause.md) (canonical pre-registration, §6 decision rule)

---

## Context

`region` had exactly one systematic, named error, and it had been counted twice.

- **On the human-graded gold 54:** all **seven** region misses were answer-key `global` rows
  the model pulled to a specific region, inferring a theater from the US *actor* where the
  snippet anchored no place.
- **At n=300 (ADR-022):** 70 answer-key `global` rows, **17 pulled** to a specific region, 16
  of them to `americas` — **49% of all 35 region disagreements**. A behavior, not a run of
  luck.

ADR-020 had already proved the cluster is *fixable*: its L4 critic corrected 6 of the 7 gold
rows. It was declined at ~4× calls per row. **A prompt clause was the cheap alternative**, and
ADR-022 had just built the ruler — a 7-point interval instead of 18 — that could tell a real
region change from noise. That is HANDOFF job 2.

The gap the clause aimed at is narrow and real. The shipped rubric says to use "what the
snippet states or unambiguously implies". A snippet reading *"Marine Corps Systems Command
awarded a contract"* **does** unambiguously imply the United States — the inference is
*correct*, and the prompt's own wording licenses it. The rubric's *intent* is that an
institution's nationality is not a theater; its phrasing never said so.

### The adversarial review round, which changed the clause before it was ever run

The first draft was sent for independent adversarial review and came back **FIX FIRST**. The
review re-derived the harness architecture, the judge-reuse argument and every decision-rule
p-value and confirmed them clean — then found the clause itself over-reached.

**Draft clause (never run):**

> - An organization is not a theater. Commands, program offices, unit designations,
>   contractors, and named officials say who is acting, not where — and neither does a
>   geographic word inside an organization's name, the site of its headquarters, or a story's
>   dateline. A snippet whose only geography is of that kind has named no place: label it
>   global. A specific region still needs a place the snippet puts the described activity in.

Joined against the actual snippets, that wording removed the **only** region evidence for
~14 **currently-correct** rows — a command's or fleet's area of operations (5th Fleet AO,
CENTCOM/EUCOM AOR), "based at Peterson Air Force Base in Colorado Springs", a geographic word
in a unit name (Maryland Air National Guard), a dateline that *is* the theater (`PHILIPPINE
SEA`) — plus a second tier of ~22 one charitable reading from flipping. It also contradicted
two ratified things: `data/gold/README.md`'s "the Mediterranean counts as `europe` (6th Fleet /
EUCOM water)", which is a mapping *defined by a fleet and a command*, and the bullet directly
above it, which says a named US base **is** an anchor.

**Revised clause, as run:**

> - A US institution is not an American theater. Naming a service, command, program office,
>   contractor, unit, or official identifies the actor, not a place: a story whose only
>   geography is institutional has no anchor, so it is global rather than americas. This does
>   not narrow the evidence above — a named command's or fleet's area of operations or
>   responsibility names a theater, and so do a named base, installation, city, country, or
>   body of water, wherever the story places the activity.

Sentence 1 is the fix, deliberately narrowed to *institutional-only* geography. Sentence 2 is
the anti-overcorrection gate, and it is doing most of the work — ADR-020 is the measured
precedent for what happens when restraint lives only in a prompt. The review also produced six
guard defects in the harness (all fixed: real completeness guards on both arms, string-typed
loading so the blank-cell check can fire, a live-prompt pin, the resume check moved ahead of
the early return, `B` computed as the rule prices it, a batch-path judge-independence test).

### The answer key is noisy on exactly this boundary

Measured from the committed artifacts, not asserted:

- **s024 and s025 are byte-identical snippets** the key labels `europe` and `middle-east`. At
  most one can be right, so at least one row is unwinnable for any classifier.
- **Four exact-duplicate snippet groups** (s022/s023, s024/s025, s078/s079/s080, s239/s240) —
  nine rows, five redundant. Duplicates violate McNemar's independence assumption in the
  anti-conservative direction, so they leave the **pairing** (nothing is relabelled, no file is
  rewritten — this experiment does not get to edit its own ruler). **Effective n = 295.**
- **The EUCOM cluster:** six rows sharing one sentence shape (a submarine returning to Naval
  Submarine Base New London from a *"U.S. European Command area of operations"* deployment).
  The key says `americas` for two and `europe` for four.
- **The Dahlgren cluster:** five rows sharing a `DAHLGREN, Va.` dateline with NSWCDD as the
  actor. The key says `global` for one and `americas` for four.

**That noise is the same order as the effect being measured**, and §6.1 of the spec said so
before the run: at the tolerance margins the rule swings on 2–4 rows, and the EUCOM cluster
alone is 6 rows the key answers inconsistently.

### The rule, pre-registered before any call was made

From the spec's §6, written and committed while nothing was measured. **SHIP** required all
four of:

1. Scale region `F − B > 0` with **McNemar p < 0.05** (p over *all* discordant pairs on the
   axis, not only over F and B).
2. **No significant guardrail harm** on category or domain — a kill condition, not a tiebreak.
3. Gold region ≥ 87.0% and no `evals/thresholds.toml` floor breached.
4. Harness health clean: 295 eligible pairs, nothing dropped or errored.

And, in the rule's own words: **"Call it MARGINAL, and revert, when region improves but
p ≥ 0.05."**

## Decision

**The clause is reverted. `classify.SYSTEM_PROMPT` on `main` is byte-for-byte the prompt that
produced the v3.0.0 gold numbers** (`prompt_sha256 a59689e8…`). The measurement, the harness
and this record ship; the behavior change does not.

### Arm 1 — scale (the primary ruler, effective n=295)

Full report: [`evals/region_clause_ab.txt`](../evals/region_clause_ab.txt). Per-row candidate
predictions in `evals/region_clause_candidate.csv` with its provenance sidecar. Answer key: the
frozen `claude-opus-4-8` judge column from `evals/scale_predictions_v3.csv`, **not re-run**
(digest `346b905682342ed8`) — `classify()` defaults *both* models to `SYSTEM_PROMPT`, so a
fresh judge pass would have graded under the candidate prompt and moved the answer key between
arms.

| Axis | Baseline | Candidate | Lift | cand-better / base-better / tie | McNemar p |
|---|---|---|---|---|---|
| **region** (target) | 88.5% | **92.2%** | **+3.7%** | 19 / 8 / 268 | **0.0522** |
| category (guardrail) | 91.5% | 92.2% | +0.7% | 6 / 4 / 285 | 0.7539 |
| operational_domain (guardrail) | 89.5% | 93.2% | +3.7% | 15 / 4 / 276 | 0.0192 |

The named cluster, priced exactly as the rule prices it:

| | |
|---|---|
| Named pulls in the baseline | 17 |
| **F** — fixed by the clause | **12** (71%) |
| …still pulled | 5 (s020, s271, s204, s070, s283) |
| **B** — correct rows dragged to `global`| **7** (s144, s101, s116, s276, s241, s299, s251) |
| Regressions on any label | 8 |
| Region correct | 261/295 → **272/295** (net **+11**) |

Harness health: `region`, `category`, `operational_domain` each 295 groups / 295 pairs / 295
eligible — clean, every group paired and scored. Rule 4 passes.

### Arm 2 — gold (the human-graded half, n=54)

Frozen under `evals/region_clause_gold_eval.txt` and `evals/region_clause_gold_candidate.csv`
(see *Where the candidate's gold numbers live*, below). Baseline is the shipped v3.0.0 record.

| Measure | Baseline | Candidate |
|---|---|---|
| **Region accuracy** | 87.0% (47/54) | **94.4%** (51/54) |
| Region macro-F1 | 0.927 | 0.964 |
| `global` recall | 0.632 (12/19) | **1.000** (19/19) |
| Category accuracy | 92.6% | 94.4% |
| Operational domain accuracy | 92.6% | 94.4% |
| Judge-vs-human region agreement | 100.0% | 96.3% (2 disagreements) |

Row-level, against human labels: **all seven** named misses fixed (g013, g017, g019, g026,
g047, g048, g054) against **three** currently-correct `americas` rows broken — g024 (`Fleet
Readiness Center East` → `global`), g037 (→ `global`), g030 (→ `middle-east`). Net +4.

Two notes the numbers earn. **The spec called g024 in advance** as the single plausible break
under the narrowed clause (§5); g030 and g037 were not predicted. And the clause fixed g013
(`7th Fleet` in a career history) and g054 (a `NEWPORT NEWS, Va.` dateline) — both explicitly
*outside* its targeted failure form, so on gold it reached further than its own scope claimed.

**No floor was breached.** `judge_region_agreement` floors at 0.93 and landed at 0.963 (2
disagreements against a budget of 3); `region_accuracy` floors at 0.78. Rule 3 passes.

### The verdict: marginal, and the rule is honored

Rules 2, 3 and 4 all pass. **Rule 1 fails by 0.0022** — p=0.0522 against a pre-registered
p<0.05. That is the "region improves but p ≥ 0.05" branch, and its pre-registered answer is
*revert*.

**Why honor a rule that missed by two ten-thousandths.** Because a pre-registration that binds
only when it is convenient is not a pre-registration — it is a post-hoc rationalization with
better typography, and this repo has spent two rungs of the autonomy ladder demonstrating why
that matters. Rung 2's whole finding is that the loop's own best-by-B iteration was **vetoed by
a held-out split it never saw** (B +6.0, C −8.6): the guard was worth having precisely because
the number it killed looked good. ADR-020's finding is the mirror image — restraint that lived
only in a prompt did not hold, and the critic over-challenged at 57.4% against an expected 13%.
A repo whose thesis is *measure first, and let the measurement decide* cannot then negotiate
with a threshold it wrote down beforehand. p=0.0522 with a documented ruler that disagrees with
itself on 6+ rows of exactly this boundary is **an unresolved question, not a small win**.

There is a second, non-ceremonial reason. §2.1's answer-key noise is the same size as the
margin: the EUCOM cluster alone is six inconsistently-labelled rows and the collateral tolerance
band at F=12 is about four. A result inside that band cannot be distinguished from the ruler's
own disagreement with itself, whatever the p-value rounds to.

### The domain +3.7% (p=0.0192), recorded honestly as an unexplained observation

The clause moved `operational_domain` from 89.5% to 93.2%, discordants 15/4, **p=0.0192** — a
larger and more significant move than the region lift it was written for, **on an axis it says
nothing about**. Three things follow, in this order:

1. **It is not evidence for shipping.** Domain was registered as a *guardrail*, and a guardrail
   is a kill condition in one direction only. Reading an unregistered improvement as support is
   exactly the outcome-switching the pre-registration exists to prevent, so the guardrail's
   kill condition never fired and the guardrail contributed nothing else to the verdict.
2. **It is not explained.** The clause touches only the region rules block. A plausible story
   is that a prompt saying "the actor is not the place" makes the model read subject-activity
   more carefully across all three axes; another is that ~15 rows moved on 295 and the axis has
   its own contested boundaries. Nothing here distinguishes them.
3. **It is the most interesting thing to re-test** if the higher-power follow-up below is ever
   run — as a *registered* hypothesis with its own rule, not as a rescue of this one.

### What would change the answer

**A higher-power ruler**, and essentially nothing else. At n=295 with F=12 the rule survives
about four broken rows; seven is over budget. The gold arm is the human-graded read and it
moved 87.0% → 94.4% with all seven named misses fixed, which is the strongest single signal
here — and n=54 is far too small to carry it. A **larger judge-graded key** (or, better, more
human-labeled rows on this boundary, which would also fix the s024/s025 and EUCOM
inconsistencies the current key cannot resolve) would let the same clause be re-registered and
re-run at a power where 12-fix / 7-break is decidable.

**That is parked as an option, not a commitment.** The near-term direction is to finish and
polish what exists rather than open a fourth front, and a larger human-labeled set is a real
labeling project. This ADR records the condition; it does not schedule the work.

## Consequences

- **The shipped classifier is unchanged.** Same prompt (`a59689e8…`), same single call, same
  `{category, operational_domain, region}` contract. No version bump, no `metrics.json` change,
  no published-marker cascade; all eight gated floors stay byte-identical.
- **The named `global` cluster remains open, and is now *sized* on both rulers.** It is not a
  mystery — it is a known, quantified, prompt-addressable error whose fix could not clear a
  pre-registered bar at this n. That is a materially better state than "we should try a clause
  someday".
- **The measurement machinery survives the negative result.** `src/region_clause_ab.py` plus 51
  tests stay as the reproducible record and as the ruler a higher-power re-run would reuse — the
  ADR-013/ADR-019 dormant-harness pattern.
- **`--report` will refuse to re-derive the frozen report on `main`**, because
  `assert_candidate_matches_the_live_prompt` correctly observes the live prompt is no longer the
  one that produced the candidate arm. That is the guard working. `evals/region_clause_ab.txt`
  is a frozen record and is read, not regenerated.
- **Measure-first is now six-for-six** (ADR-012, ADR-013, ADR-018, ADR-019, ADR-020, this) — and
  five of the six declined a change with data. It is the first to decline a change whose
  **target metric moved the right way with no measured harm** — ADR-012 and ADR-020 declined
  changes that did harm, ADR-013 and ADR-019 declined changes that did nothing. That is the
  harder case, and it is the reason the rule was written down first.
- **The cost is real and stated:** 408 API calls (300 scale + 108 gold) bought a documented
  negative. The gold arm's numbers do not vanish — they are frozen artifacts and the tables
  above, and they are the strongest argument for the higher-power re-run.

### Where the candidate's gold numbers live

The gold arm was run by deleting and regenerating `evals/gold_predictions_v3.csv` + its
sidecar, so the candidate's numbers briefly occupied the **shipped** record. Per the spec's §9
plan, the shipped record is restored from git — a published number must not be re-baselined
under a prompt that does not ship — and the candidate's raw data is preserved under frozen
`region_clause_` names instead:

- `evals/region_clause_gold_candidate.csv` — the 54 per-row predictions, byte-identical to what
  the paid run produced.
- `evals/region_clause_gold_eval.txt` — the rendered gold report from that run, byte-identical.

**No provenance sidecar is carried for these two.** The sidecar is generated by `gold_eval.py`
and records the path of the predictions it describes; copying it under a new name would mean
hand-editing a generated file, which this repo permits only for a named waiver block. The
fingerprint is on the record regardless: the gold arm ran under the same candidate prompt as
the scale arm, `prompt_sha256 b0202d06a876cc0641f50e8910368d7c8a4eb0295f662ac472f9fdd6abf4e963`,
committed verbatim in `evals/region_clause_candidate.provenance.json`. The derived artifacts
(the confusion matrices, `metrics.json`, the README block) are not preserved — they are
regenerable from the predictions, and keeping a second copy of a published surface is how a
retracted number gets re-quoted.

## Alternatives considered

- **Ship it anyway, on the strength of the gold arm and "0.0522 is basically 0.05".** Rejected:
  see the verdict rationale. The gold arm at n=54 is the ruler ADR-022 exists to replace, and
  the whole point of pre-registering a threshold is that it is not renegotiated afterward.
- **Re-run the scale arm to break the tie.** Rejected. A second run of the same 295 rows against
  the same frozen key is not more power, it is a coin flipped twice with the same bias; and
  choosing to re-run *because* the first result was close is the p-hacking the rule forbids.
- **Loosen the rule to p < 0.10, or drop the guardrail requirement.** Rejected, and it is the
  clearest case of the rule doing its job: both edits were only attractive *after* seeing the
  numbers.
- **Ship a narrower clause targeting only the 12 fixed rows' shape.** Rejected as unmeasured —
  a clause fitted to the rows it fixed on the ruler it was scored against is overfitting to the
  answer key, and would need its own pre-registration and its own paid run to mean anything.
- **Keep the candidate gold arm as the new published baseline.** Rejected (spec §9 recommended
  this rejection in advance): re-baselining published numbers under a prompt that does not ship
  would make `metrics.json` describe a classifier nobody can call.
- **Revisit ADR-020's critic instead.** Out of scope here and already declined at ~4× cost; a
  structurally narrowed critic is HANDOFF job 3, which is explicitly not a commitment.

## Downstream surfaces

Touched by this change (all in this PR):

- `src/region_clause_ab.py`, `tests/test_region_clause_ab.py` — the A/B harness and its 51
  tests, landing **without** the `SYSTEM_PROMPT` change. Two tests inverted: the pair that
  pinned the clause's presence and placement now pin its **absence** from the shipped prompt
  and the survival of the ratified evidence forms the draft would have killed. The placement
  requirement (inside the region block, for ADR-020's critic and `optimize`'s freeze) is kept in
  the docstring for whoever re-runs this.
- **Eval artifacts (new, frozen records):** `evals/region_clause_ab.txt`,
  `evals/region_clause_candidate.csv`, `evals/region_clause_candidate.provenance.json`,
  `evals/region_clause_gold_candidate.csv`, `evals/region_clause_gold_eval.txt`. Never
  regenerated or overwritten, per the repo's frozen-record rule — and the first three cannot be,
  by the live-prompt guard.
- `docs/specs/global-boundary-clause.md` — §12 **Results and verdict** appended. §1–§11 are the
  pre-registration and are left exactly as written before the run; that is the point of them.
- `CHANGELOG.md` `[Unreleased]`, `decisions/README.md` index row, `HANDOFF.md` (job 2 → closed;
  measure-first now six-for-six; the frozen-record caution extended to the `region_clause_*`
  artifacts), `CLAUDE.md` (the "nearest candidate" roadmap line).
- `README.md` — **prose only, no generated block touched.** Two passages named the clause as a
  *future* target ("a precise target for a future prompt clause"; "now a measurable target for
  a prompt clause rather than an anecdote"); both now say it was measured and reverted, with
  the numbers. `gen_readme_metrics.py --check` still passes, and no `data-metric` /
  SYS-019-managed value moves — nothing in `evals/metrics.json` changed.

Deliberately **not** touched:

- `src/classify.py` — the clause is reverted; `SYSTEM_PROMPT` hashes to `a59689e8…` as before.
- `evals/gold_predictions_v3.csv` + sidecar, `evals/gold_eval_v3.txt`, `evals/gold_confusion_v3*`,
  `evals/metrics.json`, `README.md` — restored byte-identical to `main`. No published number
  moves, so no version bump and **no marker cascade** in portfolio, architecture, learning-notes
  or kb-agent.
- `evals/thresholds.toml`, `src/eval_gate.py` — no floor is added or moved. This run measured a
  candidate that does not ship; ADR-007's rule is untouched.
- `data/gold/*` and every frozen v2/v3 record. The answer key was **not** relabelled, including
  the s024/s025 contradiction and the EUCOM/Dahlgren clusters — an experiment does not get to
  edit its own ruler.

Still deliberately open:

- **The higher-power re-run.** Parked as an option with its condition stated above, not
  scheduled. It needs a larger human-labeled or judge-graded key, and it needs its own
  pre-registration.
- **No portfolio or learning-notes writeup is claimed here.** If one is ever written, the number
  to lead with is the *decision*, not the lift — and any quoted figure inherits SYS-019 marker
  obligations plus ADR-022's answer-key caveat.
