# Feature Spec — L4: Multi-Agent Classification (triage → classify → critic)

**Version:** 1.0 (all §9 forks resolved 2026-07-25 — ready to build)
**Status:** Accepted
**Author:** San Lee
**Last updated:** 2026-07-25
**Roadmap fit:** new **MINOR** when built (additive pipeline + measurement; the shipped single-call classifier and its `{category, operational_domain, region}` contract are untouched — L4 *wraps* the classifier, it never modifies it).
**Related:** [autonomy-ladder](autonomy-ladder.md) §4 (the honesty test), §7 (build-vs-adopt: **hand-roll, decided** — not re-litigated here) · [ADR-006 amendment](../../decisions/006-autonomy-ladder-portfolio-spine.md) (governance primitives, adopted as design inputs) · [ADR-013](../../decisions/013-decline-tiered-routing.md) (the 2-actor escalation that measured +0 — the trap this design must not rebuild) · [ADR-014](../../decisions/014-region-field-design.md) (the named region error cluster this pipeline targets)

---

## 1. Problem statement, and the honest hypothesis

L4 is the last unbuilt level: **multiple agents coordinate, with handoff** — and the ladder's
honesty test (§4) is specific: a **critic that can bounce a label backward** for
reclassification. A linear pipeline with extra steps is L3 with ceremony, not L4.

The repo's history sets a hard bar for this design. Every prior "add an actor/mechanism"
experiment measured at or below zero: tiered routing (a second model as escalation target)
moved +0 rows at ~2× cost (ADR-013); three retrieval shapes went harmful / harmful
off-distribution / inert (ADR-012 / ADR-018 / ADR-019). A multi-agent pipeline that
re-classifies everything with more calls and vibes will land the same way, and it should.

**The hypothesis that gives L4 a real target:** the v3.0.0 gold run has exactly one named,
rubric-checkable error cluster — **all seven region misses are `global` rows pulled to a
specific region** because the model infers a theater from the US *actor* when the snippet
states no place. "Does the snippet state a place?" is a checkable claim about the text, not a
judgment call. That is critic-shaped: a reviewer that verifies the *evidence* for a label
against the rubric, and bounces the label back when the evidence isn't in the text. If the
critic can fix (some of) those seven rows without breaking category/domain, L4 pays. If it
can't, that is the fourth entry in the negative-result series and the writeup says so.

This also relocates the Goodhart story to its L4 home: the critic is the actor that catches
the classifier gaming plausibility ("US ship → americas") over evidence.

## 2. The three agents (all hand-rolled per §7; workhorse model per SYS-002)

| Agent | Reads | Produces | The point |
|---|---|---|---|
| **Triage** | snippet | `evidence`: the verbatim span(s) supporting each axis call, or an explicit `none stated` per axis, + an `ambiguity` flag naming contentious axes | Pins every later claim to quoted text. The critic then argues about *spans*, not vibes. |
| **Classify** | snippet (the SHIPPED `classify()` — unchanged, same call as production) | `{category, operational_domain, region}` | The system under test. L4 wraps it; it never sees triage output (see §9 Q1). |
| **Critic** | snippet + triage evidence + the label | `accept` or `challenge(axis, rubric_rule, quoted_evidence)` | The backward edge. A challenge must cite a specific rubric rule AND the evidence gap — "no place stated in the snippet, region must be global" — or it is invalid and ignored (fail-closed to accept). |

**The backward edge, concretely:** a valid challenge bounces the row back for
reclassification — a second `classify()` call whose prompt is augmented with the critic's
challenge ("a reviewer notes: the snippet states no location; re-check region against the
no-guessing rule"). The re-classified label is final. **Bounce cap: 1 per row** (§9 Q2) —
the circuit breaker from the governance primitives; a critic that challenges the re-classified
label too has hit its confidence limit, and the row is logged `contested` with the re-classified
label kept (fail-closed: never loop, never escalate to a bigger model — that was ADR-013's
dead end).

**Confidence × risk graduation (governance primitive):** the critic's charter is narrow by
design — it may only challenge on **rubric-checkable evidence claims** (place stated / not
stated; contract verb present / absent), never on "I'd have picked differently." This is what
separates it from re-running the classifier twice and keeping the disagreement.

## 3. What this is deliberately NOT

- **Not tiered routing resurrected.** No premium-model escalation anywhere; all three agents
  run the workhorse. The added actor is a *different role*, not a bigger brain.
- **Not a reclassify-everything pipeline.** The critic accepts by default; the expected
  challenge rate on gold is ~13% (7/54) if it fires only where the hypothesis says. A
  challenge rate far above that is itself a red flag the report must surface.
- **Not a change to the shipped classifier.** `classify()`, the API, and the contract artifact
  are untouched. L4 is a measurement pipeline + demo, exactly like every experiment before it.
- **Not agentic-frameworks tourism.** §7 decided hand-rolled Messages API; the orchestration
  is a plain Python driver, and the audit log is the same append-only JSONL family as both
  L3 loops.

## 4. Measurement (the deliverable, per house rules)

- **Primary: paired exact McNemar on the gold 54, all three axes**, L4 pipeline vs the stored
  v3 single-call run (fair anchor: same prompt/model). Region is where the hypothesis lives;
  category/domain are the do-no-harm axes.
- **Named-cluster accounting:** of the 7 known `global` misses, how many did the critic
  challenge, and how many did the bounce fix? This is the headline number — it is small-n and
  the report says so, but it is *named-row* evidence, the strongest kind this repo has.
- **Cost axis:** calls per row (1.0 baseline vs ~2 + challenge-rate × 1 for L4) and the
  measured challenge rate. The ADR-013 lesson: report the multiplier next to every accuracy
  delta.
- **Scale read (secondary):** the n=300 scale set has no region judge-labels yet, so
  the scale pass reports **category/domain do-no-harm + challenge rate** only, stated as such.
- **Audit log:** append-only JSONL per run — every triage note, label, challenge (with cited
  rule + evidence), bounce, and final label. The replay viewer's third data source.

## 5. Deliverables

1. `src/l4_pipeline.py` — triage/critic prompts + tools, the driver with the backward edge,
   injected backend (live + dry-run), resume-safe per-row scoring, audit JSONL.
2. `evals/l4_eval.txt` + per-row predictions CSV — the measured comparison.
3. Offline tests: challenge validation (rubric-citation required, fail-closed on invalid),
   bounce cap enforced, shipped-classifier untouched (import-level assertion), audit-log
   round-trip, dry-run end-to-end.
4. **ADR-020** recording the design + (amended) the verdict, either direction.
5. README + ladder-spec updates per the de-scope sweep discipline; portfolio cascade waits
   for the verdict (result, not promise).

## 6. Definition of done

1. Dry-run pipeline runs offline end-to-end with a canned critic; CI-covered.
2. Live gold run recorded (San drives); named-cluster accounting in the report.
3. McNemar + cost multiplier reported for all measured axes; challenge rate reported.
4. ADR-020 verdict amended; sweep executed.

## 7. Honest-reporting rules (inherited, non-negotiable)

Bake-off spec §8 applies verbatim: every figure carries its n; a delta is not a finding
without the paired test; report the direction that hurts; name what is uncovered (at the time
this ran, region had no scale-set answer key and the named cluster was 7 rows — v3.2.0's
scaled region eval has since sized it at 17 pulled rows out of 70, [ADR-022](../../decisions/022-scaled-region-eval-verdict.md)).

## 8. Cost estimate (up front, per house rules)

Gold: 54 × (triage + critic) + ~7-10 bounces ≈ **~120 extra workhorse calls** on top of the
free stored baseline. Scale do-no-harm pass: 300 × 2 + bounces ≈ **~630**. Total ≈ **750
calls**, same order as ADR-019's runs. No premium-tier calls anywhere.

## 9. Design forks — RESOLVED (San, 2026-07-25)

1. **`classify()` stays blind to triage's evidence.** The pipeline measures the *critic's*
   marginal value cleanly, and the shipped call stays byte-identical to production. The
   alternative (evidence-augmented classify) tests a different, bigger claim and muddies
   attribution.
2. **Bounce cap = 1.** The known failure mode is a single rubric miss; a re-classify that
   ignores the challenge is surfaced honestly as `contested` in the log, not argued down by
   repetition.
3. **The critic covers all three axes**, with the rubric-checkable-claims charter doing the
   narrowing — a region-only critic would bake the hypothesis into the harness and make the
   do-no-harm claim on category/domain vacuous (an actor that can't touch an axis can't
   break it, but also can't be credited for restraint).
