# Feature Spec — measuring what L4's unguarded edges cost

**Version:** 1.0 — **PRE-REGISTRATION.**
**Status:** **OPEN — instrument built, nothing measured. No arm has been run against this
document as of the commit that adds it.** §1–§11 are written before the first paid call and
are to be left exactly as written, including the estimates a run may go on to contradict.
That is what makes this a pre-registration rather than a summary.
**Author:** San Lee
**Last updated:** 2026-08-09
**Roadmap fit:** unversioned. This measures the pipeline; it does not change the
`{category, operational_domain, region}` contract, the shipped prompt, or any published
number. A result ships an ADR, and possibly a writeup, and no version at all.
**Related:**
[ADR-020](../../decisions/020-l4-multi-agent-pipeline.md) (the pipeline, built and declined) ·
[autonomy-ladder §4](autonomy-ladder.md) (the asymmetry this measures) ·
[l4-multi-agent](l4-multi-agent.md) §9.1 (design fork 1 — why `classify` is blind to triage) ·
[ADR-023](../../decisions/023-global-boundary-clause-verdict.md) /
[`src/mcnemar_power.py`](../../src/mcnemar_power.py) (the power instrument) ·
[SYS-022](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-022-org-graph-and-the-mechanization-split.md)
(the parent finding, and its Amendment 1) ·
[SYS-019](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-019-assert-claims-dont-list-them.md)
(why the cell matrix is asserted against this file rather than listed in it)

> **This document is canonical for the hypothesis (§1), the cell matrix (§5), the scoring
> rules (§4), the decision rule (§6) and the run protocol (§9).** `src/l4_inject.py` implements
> it and `tests/test_l4_inject.py::test_the_registered_matrix_matches_the_pre_registration`
> pins the two together, so neither can move alone. Where prose and code disagree, this file
> states the intent and the test is the enforcement.

---

## 1. The claim, and the framing that is the whole difference

**The tautology this must not be.** "We deleted information from a message and the recipient
made worse decisions" is not a finding, it is the definition of information. A reader who takes
only that from the piece is right to stop reading, and no amount of statistics rescues it.

**The actual claim.** ADR-020 built three governance primitives for the L4 graph — a
fail-closed challenge gate (`challenge_violations`), a structural bounce cap (exactly one
re-classify call site), and a critic charter (`CRITIC_SYSTEM_PROMPT`). **All three guard
against a bad critic. Not one of them validates upstream state.** There is no schema check, no
presence check and no shape assertion at any node boundary; the three triage evidence field
names appear in exactly one file in the repo. So the hypothesis is not about information, it is
about *where instrumentation was placed*:

> **H1.** A payload dropped on an edge the guards do not watch ships a wrong answer without
> the pipeline's three governance primitives registering anything. The measured share of such
> drops is the bill for having built the guards at the boundary that was easy to reason about
> rather than the one carrying the risk.

> **H2 (the interesting one, and the insurance).** A meaningful share of what these edges carry
> is **not load-bearing** — dropping it changes nothing. If that share is large, the piece is
> no longer about removing information; it is about which parts of a carefully-specified edge
> are real, and most of them are not.

H1's framing is available today: the asymmetry is a grep result, not an experimental outcome.
H2 depends on the data. **If neither lands, this does not get published** — it gets an ADR
recording a negative result, which is in-genre here (ADR-012, ADR-013, ADR-020 and ADR-023 all
declined something) and a tautology dressed up is not.

## 2. The rig, and the edge that does not exist

`src/l4_pipeline.py` is **not modified by this work.** `L4Backend` is a Protocol, the backend
is `process_row`'s first positional argument, and the existing tests already inject fakes
through it, so the entire injection apparatus is a wrapper class. State on every edge is a
plain JSON-serializable dict, `json.dumps`'d unmodified into both the critic prompt and the
audit trail.

| Edge | What crosses | Where the wrapper corrupts it |
|---|---|---|
| `triage → critic` | the evidence dict: `category_evidence`, `domain_evidence`, `region_evidence`, `ambiguous_axes` | `critic(evidence=…)` |
| `classify → critic` | the label dict: `{category, operational_domain, region}` | `critic(label=…)` |
| `critic → classify` (backward) | the reviewer note string, on a bounce | `classify(note=…)` |

**`triage → classify` is not on that list, and the absence is a finding rather than a gap.**
`classify()` takes no evidence argument at all — design fork 1, resolved 2026-07-25 so the run
would measure the critic's marginal value and not a different classifier. Two of the three
edges that do exist terminate at the verifier. **A dropped field here therefore does not
contaminate a downstream producer; it blinds the verifier.** That is narrower than
"propagation" and it is the thing that can actually be defended.

**Corruption is applied to the consumer's argument, never to a producer's return value.** On
`classify → critic` the critic reviews a corrupted label while the label that ships is
untouched. That distinction is what makes this a context-loss experiment rather than an
answer-tampering one, and it is pinned by
`test_classify_to_critic_blinds_the_verifier_not_the_shipped_label`.

**One offline trap, handled.** `DryRunBackend.critic` subscripts `evidence["region_evidence"]`
and `label["region"]` directly, so every omission cell would raise there and the free harness
would only ever exercise `CRASHED`. The live path does not raise — it serializes whatever it
was handed — so the crash is the canned backend's artifact, not the behaviour under test.
`GuardedDryRunBackend` reads a missing key the way the live critic would: as evidence that
states nothing.

## 3. Ground truth is two references, not one

| Question | Reference |
|---|---|
| **Is the final answer wrong?** | The 54-row human-labelled gold set, `data/gold/gold.csv`. Real public DVIDS snippets, disjoint from the retrieval corpus; label semantics and the ratified region boundary in `data/gold/README.md`. |
| **Did the drop cause it?** | The paired un-injected control run on the same rows, scored through `src/paired_compare.py` and `baseline_ml.mcnemar_exact` — the same machinery every A/B in this repo goes through. |

**There is no ground truth for intermediate node output and there will not be.** Nobody has
hand-labelled what triage *should* have said about a snippet's region evidence, and producing
that gold would be a bigger project than this one. This is why the obvious-sounding metric
"fraction of downstream nodes contaminated" is **rejected rather than deferred**: it silently
assumes a gold that does not exist. Stating that here is the honest limitation, not an
omission to be discovered by a reader.

The consequence is a real narrowing, and it is the price of the design: this measures
**terminal** contamination against gold and **attributes** it via the paired control. It does
not observe contamination mid-graph.

**Hard boundary.** `faithfulness-judge`'s claim gold is not touched, not relabelled and not
used as a judge here. No LLM judge is used at all — the task has a categorical gold, and adding
a nondeterministic scorer on top of a nondeterministic system is two noise sources where one
will do.

## 4. The metric

### 4.1 "Propagation distance" is retired as the headline, and here is why

The phrase is the reason the idea is attractive and it is the first thing that has to go.
**Hop count is bounded by graph depth, and graph depth is a free parameter someone chose.**
Publishing "the wrong answer travelled two hops before detection" in a graph designed with
three nodes publishes an architecture decision with error bars on it: make the graph deeper and
the number goes up, which is a property of the diagram, not of context loss.

Two aggravating facts specific to this rig. The graph is three nodes, so the maximum observable
distance is 2 — a scalar with range `{0, 1, 2}` plus an undefined "never" bucket is a category
label wearing a number. And two of the three stateful edges terminate at the verifier, so there
is barely room for anything to propagate.

Displacement survives only as a **distribution with an explicit `never` mass**
(`displacement_distribution`). There is deliberately no mean and no median in the module, and a
test asserts the absence: averaging a bounded index over an undefined bucket is exactly the
number the partition replaces.

### 4.2 The headline is a rate over a partition

Every (row × injection × axis) trial lands in exactly one bucket. **A rate normalizes against
depth** — "38% of drops on this edge shipped a wrong answer unnoticed" does not change when a
node is added; a hop count does.

| Bucket | Definition | What it means |
|---|---|---|
| **CRASHED** | the run raised rather than answered | A robustness fact, not a context-loss fact. Counted, reported separately, **excluded from every denominator** — folding it in charges a robustness failure to context loss. |
| **CAUGHT** | a *valid* challenge named the affected axis **and** the shipped label matches gold | The guard worked. Checked **before** ABSORBED on purpose: a drop the critic caught and repaired back to the control's answer is a working guard, not an inert edge. |
| **ABSORBED** | the shipped label equals the control's | The payload was not load-bearing. **H2's bucket, and the headline number** — see §4.2.1. |
| **CORRECTED** | changed, right, and no guard fired | Not in the original four. It is what makes the partition **exhaustive** — a drop that changes the answer and lands on gold has to go somewhere, and folding it into ABSORBED or CAUGHT would each be a lie of a different kind. |
| **CONTAMINATED** | wrong, different from the control, shipped | Wrong, attributable, and out the door. **Secondary**, because it is the bucket whose claim needs the significance test the design is weakest at. |

#### 4.2.1 ABSORBED is the headline, CONTAMINATED is the attribution — amended 2026-08-09

**Amended after §7's power table was read and before any paid call**, which is the only window
in which this may move. As adopted, this document called CONTAMINATED the headline. That put the
whole piece behind the design's weakest instrument.

The two claims need different machinery, and only one of them is underpowered:

- **ABSORBED is a proportion**, and a proportion needs no significance test. At `n=44` a Wilson
  interval is perfectly usable near an extreme — a cell landing at 95% absorbed carries roughly
  84–99%, which is a reportable finding. There is nothing to correct for and no family to
  belong to.
- **CONTAMINATED is a difference**, and a difference against a paired control is what McNemar
  is for — the test §7 shows needs a 24-point effect uncorrected at `n=44`.

So the headline is *how much of what these edges carry turns out not to matter*, which is H2,
and which is also the claim that rescues §1's tautology objection. CONTAMINATED remains
reported in full and remains H1's evidence; it is the attribution number, and it is bounded by
what §7.1 says the test can see.

This does not soften anything. It stops the piece from depending on the one instrument its own
power analysis says is weak, and it does so *before* the arms run rather than after a null.

"Valid" is the charter's own definition, read through `l4_pipeline.challenge_violations` rather
than re-derived — a challenge the pipeline discards must not be credited as the guard firing.
Rates carry Wilson intervals (`eval.wilson_interval`); neither eval repo has bootstrap CIs, so
nothing is reported that would need one.

**Axis discipline, learned from ADR-020.** A cell that names an affected axis is scored on that
axis as its headline, with the other two reported as **guardrails**. A region-only report would
have scored ADR-020's critic a success while it was doing significant harm to the domain axis.

### 4.3 Secondaries

Calls burned after the drop (`calls_after_injection`), and the displacement distribution above.
**Calls, not tokens:** `AgentReply.tokens` is computed by the live backend and then discarded
by the driver's event dict, `classify` reports zero tokens by design, and no latency is captured
anywhere in the pipeline. Calls per row is the axis the repo already records and already has a
measured baseline for (4.15 on gold).

## 5. The pre-registered cell matrix

Twelve cells: one negative control and eleven live. Fixed before the first paid call, committed
in the same PR as the harness, and asserted against `l4_inject.CELLS` by a test — which is
`SYS-019`'s move applied to this experiment's own contract, and the only thing standing between
this and post-hoc cell selection.

| # | Cell | Affected axis | Tier | Why it is in the matrix |
|---:|---|---|---|---|
| 0 | `triage->critic/payload/null` | — | control | **The negative control.** A full-cost pass-through arm: same calls, same scoring, no corruption. |
| 1 | `triage->critic/region_evidence/omit` | region | **primary** | The `SYS-022` failure verbatim — the edge does not carry it — on the axis the pipeline's own hypothesis lives on. **The one confirmatory test**, per §5.1. |
| 2 | `triage->critic/region_evidence/empty` | region | secondary | The sharpest pair in the matrix against #1: for a `json.dumps`'d payload, does the field's **presence** matter or its **content**? |
| 3 | `triage->critic/region_evidence/truncate` | region | secondary | The realistic form — a brief that fits, badly. |
| 4 | `triage->critic/region_evidence/stale` | region | secondary | The nastiest and most realistic: another row's value, plausible, well-formed, wrong. This is what a stale hand-carried brief actually is. |
| 5 | `triage->critic/category_evidence/omit` | category | secondary | Is the effect about region, or about evidence in general? Without this cell the result is a single-axis anecdote. |
| 6 | `triage->critic/ambiguous_axes/omit` | — | secondary | **The anti-tuned cell.** A schema-*required* field with **no critic rubric rule**. If dropping it changes nothing, a required field is decorative. If it does, the critic uses state nobody documented it as using. Both are findings, and both are ABSORBED-rate findings that never needed a test. |
| 7 | `classify->critic/region/omit` | region | secondary | Blind the verifier to the thing it is verifying. |
| 8 | `classify->critic/region/stale` | region | secondary | The verifier reviews a different row's region against this row's evidence. |
| 9 | `critic->classify/payload/omit` | — | descriptive | The backward edge carries nothing: the bounce happens, the reason does not arrive. |
| 10 | `critic->classify/payload/truncate` | — | descriptive | The reason arrives half-stated. |
| 11 | `critic->classify/payload/stale` | — | descriptive | The bounce carries another row's complaint. |

### 5.1 Tiers — amended 2026-08-09, after the power table and before any paid call

As adopted, all eleven live cells were co-equal, which forced the choice between an uncorrected
α that carries a ~43% family-wise error rate and a Bonferroni α needing **33 points at `n=44`
and 51 on the backward edge**. Neither is a design that can conclude. The fix is to stop
splitting the confirmatory budget eleven ways.

| Tier | Cells | What it may claim |
|---|---|---|
| **control** | #0 | Gates readability of the run (§6's void condition). Makes no claim. |
| **primary** | #1 | **One** confirmatory test, exact two-sided McNemar at **α = 0.05, uncorrected**. A single pre-registered test is not a family and is owed no correction. MDR at `n=44`: **24 points**. |
| **secondary** | #2–#8 | Rate, Wilson interval **and** p-value all reported in full. **No secondary p-value is read as a discovery.** H2 lives here and is a rates question, so the tier costs it nothing. |
| **descriptive** | #9–#11 | Rates and intervals only. `n≈25` puts the *uncorrected* MDR at 36 points, so a comparative claim is unsupportable at any α. Reporting their p-values as tests would be the "not detectable here → no effect" slide §7.1 forbids. |

**#1 is the primary because it is the surgical form of the failure** — one field, not the whole
payload — **on the axis ADR-020 built the critic to fix.** If the critic does not notice that
its region evidence is gone, on the cluster it exists for, the guard is decorative and the
finding needs no help from the other ten cells. The negative control (#0) stays as the check
that the instrument fires at all.

**This is the last moment this may change.** The tiering was chosen from the power table, which
is computed from `n` and assumed effect sizes and contains no data. Re-tiering after the first
paid call is post-hoc selection and voids the pre-registration exactly as re-scoping a cell
would; `l4_inject.CellTier` carries the same warning and a test pins the assignment.

**Not registered, and why** — recorded so "we did not run that" stays separable from "we ran
that and buried it":

| Combination | Reason |
|---|---|
| `classify->critic/*/truncate` | A label value is a single enum token. It has no clause to cut, so truncation degenerates into either omission or a corrupt token. |
| `critic->classify/*/empty` | The backward edge carries a bare string, so emptying it and omitting it are the same injection. Only omission is registered. |
| `triage->classify/*/*` | **The edge does not exist** (§2). Not a gap in the matrix. |

**On the negative control, and a deliberate departure from the design brief.** The brief
proposed dropping "a field the consumer provably never reads." No such field exists on any of
the three edges. `ambiguous_axes` is the closest candidate and it is cell #6 — a live research
question, and a live question cannot double as the arm that proves the instrument is quiet. A
full-cost pass-through arm is the stronger control anyway: it measures the whole apparatus's own
noise floor end to end, including the stability filter.

**Donor rows for the three `stale` cells are fixed by protocol**, not chosen per trial: row *i*
is donated to by row *i+1*, wrapping. A stale cell that got to pick its donor could be tuned to
hurt.

## 6. Pre-registered decision rule, and the void condition

Let `n` be the stable set (§8, C2). Every rate below is over that set, on the cell's affected
axis, with the other two axes reported as guardrails.

**The void condition, checked first.** The run is **VOID** and nothing else in it is readable
if the negative control (#0) shows **CONTAMINATED ≥ 3 of `n` on any axis**. At `n=44` that is
6.8%, whose Wilson upper bound is 18.2% — wide enough that a lower count cannot be
distinguished from residual noise, and a higher one means the stable set is not stable and every
cell's number is uninterpretable. The control's rate is reported **beside every cell's rate**,
as the floor, in every table. No cell result is ever corrected by subtracting it; that would be
a post-hoc adjustment.

**H1 is supported** when, on the **primary cell** (#1) and its affected axis, CONTAMINATED is
substantially above the control floor *and* CAUGHT is near zero — the drop ships wrong answers
and the three governance primitives do not fire. **That single test is the confirmatory
claim**: exact two-sided McNemar, injected vs control, at α = 0.05 **uncorrected**, because one
pre-registered test is not a family (§5.1).

The seven secondary cells are reported in full — rate, Wilson interval and p-value, boring ones
included — and **no secondary p-value is read as a discovery**. They place the primary in
context and answer H2; they do not multiply the confirmatory claim. The three descriptive cells
report rates only. The Bonferroni threshold α = 0.05/11 = 0.0045 is still printed beside the
power table as **the cost the tiering avoids**, not as a threshold in force.

**H2 is supported** when ABSORBED is large on cells whose payload the schema requires —
cell #6 (`ambiguous_axes`) is the sharpest test, and cells #2 vs #1 decide whether presence or
content is what the edge is really carrying. **H2 is the headline** (§4.2.1) and it is a claim
about proportions, so it is decided by rates and their Wilson intervals with no significance
test involved, at any tier.

**Publish nothing** when the null control voids the run, or when the result is CONTAMINATED ≈
100% and ABSORBED ≈ 0 across the board. That outcome has confirmed a tautology at the cost of
about three thousand API calls, and §11 says so in advance so it cannot be re-read as a success
afterwards. It ships an ADR and stops.

**A pre-registration that binds only when convenient is not one.** ADR-023 is this repo's
precedent: three of four rules passed, the fourth missed by 0.0022, and the clause was reverted.

## 7. Power analysis, run before anything was spent

Computed with `src/mcnemar_power.py` — exact two-sided McNemar, no normal approximation, no
simulation — via `uv run python src/l4_inject.py --power`. `p_b` is the per-row probability the
injected arm is wrong where the control was right (the contamination being powered for); the
reverse rate is held at 0.02 rather than 0, because pretending a drop can never improve an
answer flatters the sample size.

Three sample sizes matter. `n=54` is the gold set. `n=44` is the stable-set assumption (§8, C2).
**`n≈25` is the backward edge**, and that is the single largest `n` cost in the design: cells
#9–#11 only fire on rows that bounce, which was 31 of 54 (57.4%) in the ADR-020 run, so 44
stable rows yield about 25 usable trials.

**Power at α = 0.05 (uncorrected):**

| assumed contamination | n=25 | n=44 | n=54 | n for 80% |
|---|---:|---:|---:|---:|
| 40% | 0.882 | 0.995 | 0.999 | 22 |
| 30% | 0.650 | 0.945 | 0.981 | 32 |
| 20% | 0.274 | 0.685 | 0.807 | 54 |
| 15% | 0.111 | 0.421 | 0.560 | 81 |
| 10% | 0.023 | 0.145 | 0.230 | 153 |

**Power at α = 0.0045 (Bonferroni over 11 live cells):**

| assumed contamination | n=25 | n=44 | n=54 | n for 80% |
|---|---:|---:|---:|---:|
| 40% | 0.531 | 0.945 | 0.986 | 34 |
| 30% | 0.221 | 0.725 | 0.869 | 49 |
| 20% | 0.032 | 0.291 | 0.450 | 84 |
| 15% | 0.006 | 0.101 | 0.193 | 126 |
| 10% | 0.000 | 0.013 | 0.034 | 249 |

**Minimum detectable contamination rate at 80% power:**

| | n=25 (backward edge) | n=44 (stable set) | n=54 (all gold) |
|---|---:|---:|---:|
| α = 0.05 | **36%** | **24%** | 20% |
| α = 0.0045 | 51% | 33% | 28% |

### 7.1 The verdict, stated plainly

**This design's significance test detects large effects and cannot distinguish a modest one
from zero.** At the expected `n=44` the primary cell needs a **24-point** contamination rate to
reach 80% power at its uncorrected α; the backward edge would need 36 even uncorrected, which is
why §5.1 registers those three as descriptive rather than pretending otherwise. A cell that
comes back at 10% contamination will be indistinguishable from the null control, and that must
be reported as *not detectable here*, **never** as "no effect."

**This is precisely why the headline is a rate and not a test** (§4.2.1). The partition rate is
the primary reporting unit and McNemar is only for attribution on one cell. But a rate at `n=44`
still carries a Wilson interval about 26 points wide near 30%, so the honest reporting unit is a
wide interval, not a point estimate — and the intervals are narrowest exactly where H2's
interesting answers live, near the extremes.

**What follows from this, decided in advance rather than after the numbers arrive.** If the
observed effects are large, this is a result piece. If they are modest, **this is a methods
piece** — here is how you instrument an edge, here is the power analysis that says what the
instrument can see, here is why the answer is inconclusive at this `n` — and that is a smaller
piece than the idea promises. Both outcomes are acceptable. A third outcome, reading a
non-significant cell as evidence of absence, is not.

**What more rows cannot buy.** Power is a variance instrument. The gold set's own boundary
disagreements (ADR-022 §2.1, ADR-023) do not shrink with `n`. There is also no larger substrate
available: the n=300 scale set has no region ground truth, so two of three axes only.

## 8. Confounds

Ordered by how fast a skeptical reader reaches for them.

### C1 — "You removed information and things got worse. So what?"

**The strongest objection, and it is a framing problem rather than a statistics problem.**
Controlled only by §1's framing and by the ABSORBED bucket carrying real weight. **Partially
controlled, by design, not by analysis** — and if ABSORBED ≈ 0 while CONTAMINATED ≈ 100%, §6
says do not publish.

### C2 — Model nondeterminism

**Controlled, with existing machinery, and this is the strongest answer here.** Five un-injected
control passes establish the per-row **stable set** — rows whose label is identical across every
run, on all three axes — and every injected trial is scored **only on the stable set**. A row
that flips on its own is discarded as noise rather than counted as contamination. The method and
the 2×-σ decision rule are `src/stability.py`'s, ratified there; `l4_inject.stable_ids` adds only
the return type (ids rather than a fraction, three axes rather than two), and
`control_consistency` cross-checks itself against `stability.label_consistency` so the two
cannot silently disagree.

**No determinism is promised.** Current models reject a non-default temperature with a 400 and
no seed exists at the API level in either eval repo, so stability is *measured* rather than
forced.

**The control costs `n`.** If the stable set is 44 of 54, every interval below is computed on 44
and the backward-edge cells on about 25. **The stable-set size is a headline input, reported
before any rate, never a footnote.**

### C3 — Underpowered `n`

**Controlled by running the power analysis first and publishing the answer** (§7), which is
`SYS-019`'s posture applied to this experiment's own result. It may honestly conclude the design
is underpowered for the interesting cells; §7.1 pre-commits to what happens then.

### C4 — "Your verifier was tuned to catch exactly your injection"

**Only partly controllable, and this is the confound to be most honest about.**

Real partial controls: the critic charter **predates the experiment** — `CRITIC_TOOL` and the
charter were written for ADR-020 in July, to fix a named region error cluster, for an entirely
different purpose. The negative control detects a verifier that fires on anything. And cell #6
is an injection the charter has *no* rubric rule for, deliberately anti-tuned.

**The control that does not exist: the charter and the injection matrix have the same author.**
Pre-registration constrains post-hoc selection; it does not fix single-author bias. **Recorded
as an uncontrolled confound.** An adversarial pass by another vendor writing the matrix blind to
the charter would help and is worth one round before the paid arms.

### C5 — An artificially fragile graph

The counter is strong: the graph **was not built for this.** It was built under ADR-020 to fix a
named error cluster, run live on 2026-07-25, measured, and **declined as configured** — the rig
predates the hypothesis, which is unusual and worth saying.

The counter-counter is stronger: it was declined *because it made things worse* (gold category
92.6 → 90.7, domain 92.6 → 81.5, region 87.0 → 75.9). Injecting faults into a graph already
known to be bad and reporting fragility is weak.

**The control:** every injected arm is scored **against the L4 control run, never against the
v3 single-call baseline.** That factors out "L4 is worse than one call" entirely. The v3
comparison appears once, as context, and never in a headline number.

### C6 — Cherry-picked task and cherry-picked cells

Controlled by this document, committed before the first call and asserted against the code, and
by reporting **all** cells including the boring ones. Not controlled at all for *task*: one rig,
one task, one model. **Nothing here is claimed to generalize** to other graph shapes, tasks, or
model families.

### C7 — The synthetic fault is unrealistically clean

**Not controllable. Disclosed.** Real context loss happens because a human or an agent forgot
something at a boundary nobody was watching. A wrapper deleting a dict key is a *model* of that;
the `stale` cells are the closest approximation and the reason they are in the matrix. The gap
between "a field is absent" and "a brief was written badly" is not closed by this design.

### C8 — Cost instrumentation is incomplete

Tokens are computed and discarded, `classify` reports zero by design, and there is no latency
capture. **Disclosed, and cost is reported in calls** (§4.3). Closing it means editing
`src/l4_pipeline.py`, which this branch deliberately does not do.

## 9. Run protocol

Every command from the repo root.

### Step 1 — free, offline, and the only step this PR expects to be run

```bash
uv run python src/l4_inject.py --cells --power
uv run python src/l4_inject.py --control-arm --dry-run
```

The first prints the matrix, the infeasible combinations and the call budget, then the power
tables in §7. The second exercises the whole harness end to end against the offline backend and
spends nothing. Then the free verification:

```bash
uv run pytest
uv run ruff check .
uv run black --check .
uv run mypy src
```

### Step 2 — the control arm (**paid**, ~1,120 calls, owner-driven)

```bash
uv run --env-file .env python src/l4_inject.py --control-arm
```

Five un-injected passes over gold at the measured 4.15 calls/row. Each pass is individually
resume-safe, so an interruption costs at most one call.

**The committed ADR-020 record is never opened.** `control_arm` repoints
`l4_pipeline.RUN_PATHS` at `evals/l4_inject/` for the duration and restores it in a `finally` —
the same seam the pipeline's own tests use, and the reason this needs no edit to
`src/l4_pipeline.py`. There is no `rm` in this protocol and no undo line is required, which is
the point of doing it this way rather than moving `evals/l4_gold_predictions.csv` aside five
times.

**Before this step runs**, add `evals/l4_inject/*.jsonl` to `.gitignore` — audit trails are
transient run artifacts under the same policy as `evals/l4/audit_*.jsonl`. The per-run
prediction CSVs are committed.

### Step 3 — the injected arms (**paid**, ~1,960 calls) — *not in this branch*

The injected runner is deliberately **not built here**. §7's answer decides whether it is worth
building at all, and building the spender before reading the power analysis is the sequence this
document exists to prevent. When it is built it reuses `InjectingBackend`, the same
`RUN_PATHS` repoint, and `pending_rows` resume, one CSV per cell.

Total if every step runs: about **3,080 calls**.

## 10. Explicitly NOT in this branch

No edit to `src/l4_pipeline.py` · no version bump · no CHANGELOG entry · no ADR (spec first,
ADR at verdict — the ADR-017 pattern) · no change to `evals/metrics.json` or any published
number · no `thresholds.toml` change · no gold-set edit · no injected-arm runner · **no live API
call.**

## 11. What would make this not worth publishing

1. **It is a tautology wearing lab coats.** §1 is the whole defense. If ABSORBED is negligible
   and the piece reduces to "information matters", write the ADR and stop.
2. **The graph is too shallow for the name.** Three nodes, two of three stateful edges
   terminating at the verifier, `classify` blind to `triage` by construction. §4.1 handles it by
   retiring the metric, and the retirement has to be the **first** substantive section of any
   writeup, argued rather than buried. **The tempting fix is the trap:** adding nodes to make the
   number bigger converts an independently-motivated rig into a purpose-built one and hands C5
   straight back.
3. **It re-derives an existing verdict.** ADR-020 already concluded the L4 critic is not worth
   its cost. "The critic is weak" adds nothing. The differentiator is **why**: a critic blind to
   upstream state is a different diagnosis than a critic bad at its job, and it points at a
   different fix — validate the edge — than the one ADR-020 implies, which is drop the node.
4. **The numbers are too small to say anything.** §7.1 pre-commits: that outcome is a methods
   piece, and it is acceptable.
5. **It reads as self-indulgent.** A graph built, broken and written about by one person on a
   task with no user. The mitigating facts are real and have to be visible early: the rig
   predates the hypothesis, the gold is human-labelled from public sources, the baseline is
   committed, and the verdict on the graph was already negative before this was conceived.
6. **Scope creep into the fleet.** The pull toward "and therefore the vendor-to-vendor edge
   should be mechanized" is real. One closing sentence is fine. Building it here is two projects
   in one PR.
