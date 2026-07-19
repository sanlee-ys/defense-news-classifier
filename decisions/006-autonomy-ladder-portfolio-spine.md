# ADR-006: Make an autonomy ladder the portfolio spine, with the classifier as the single protagonist

**Status:** Accepted
**Date:** 2026-07-04
**Deciders:** San Lee

---

## Context

The portfolio spans several capabilities — a prompt-based classifier, retrieval grounding, an
autonomous optimization loop, and planned multi-agent work. Presented as separate demos, these
read as a checklist rather than a system, and the classifier (the stated centerpiece) risks
sitting *outside* the story the loop work tells.

There are two competing "levels" framings for organizing this:

1. **Model adaptation** — prompt → RAG → fine-tune → pretrain. About *how you build with a model*.
2. **Autonomy** — single call → augmented → autonomous loop → multi-agent. About *how much the
   system drives itself*.

The audience is technical reviewers judging whether the author can design a self-directing
system, not just prompt one.

## Decision

Adopt the **autonomy ladder** as the portfolio spine, with **the classifier as the single
protagonist** climbing all four levels. Each level is the same system handed more autonomy.

| Level | Rung | State |
|-------|------|-------|
| **L1** Single call | prompt + structured label + eval | shipped (v1) |
| **L2** Augmented | BM25 retrieval grounding | shipped (v2.0.0), then **retired** ([ADR-012](012-retire-bm25-grounding.md)) |
| **L3** Autonomous loop | prompt-opt loop → agent-driven ML loop (ADR-005) | spec'd |
| **L4** Multi-agent | triage → classify → critic with backward handoff | to spec |

> **Status correction, 2026-07-18.** The L2 row read "shipped (v2.0.0)" until this
> amendment, months after [ADR-012](012-retire-bm25-grounding.md) retired BM25 grounding
> on 2026-07-17 — a fair same-prompt re-measure found it fixed a domain call zero times
> and broke four across 162 grounded classifications. The rung was climbed and then
> climbed back down.
>
> **That does not vacate L2, and the ladder is not renumbered.** The axis is *who
> drives*, not *which techniques survive*: L2 asked whether the model could reach for a
> tool, and it can — the tool simply did not earn its place once the ungrounded baseline
> improved. A ladder that quietly deletes a rung whose experiment failed would be
> measuring narrative tidiness rather than autonomy. The retirement is the interesting
> part of L2, not an embarrassment to hide, and the retrieval code stays in the repo
> dormant and reproducible as the record.

Two design choices define the spine:

**1. RAG is folded into the classifier, not a standalone demo.** Grounding lives inside the
classifier (as it already does in v2.0.0) so there is one throughline from L1 to L4 rather than
a RAG artifact sitting off to the side.

**2. Autonomy is the spine; adaptation techniques are ingredients.** RAG, and any future
fine-tuning, are used *within* a level rather than being levels themselves. The distinguishing
axis between levels is *who drives and how many autonomous actors*, not whether a tool is called.

The living map is [docs/specs/autonomy-ladder.md](../docs/specs/autonomy-ladder.md).

## Consequences

- **The classifier stops being a side demo** and becomes the throughline a reviewer follows end
  to end.
- **Two of four levels are already shipped** (L1, L2). The spine ratifies existing work rather
  than proposing a rebuild; the outstanding spine work is L3 (spec'd) and L4 (to spec).
- **A vocabulary collision is introduced and must be managed:** the loop spec's "rung 1 / rung 2"
  are sub-steps *inside* L3, not ladder levels. The roadmap doc names this explicitly.
- **L2's legibility cost is pushed to the writeup.** Folding RAG in loses the standalone "I did
  RAG" signal; the L2 writeup must name the technique explicitly to recover it.
- **L4 is deferred, not started.** It is a new level on top of two loop rungs that are not built
  yet; per one-concern-per-session it earns its own spec + ADR when picked up, after L3 lands.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Model-adaptation ladder as the spine (prompt → RAG → fine-tune → pretrain) | Frames the work as model plumbing; the differentiator for a systems/TPM audience is self-direction, not adaptation. L4 (pretraining) is also the wrong tool for a solo portfolio. |
| Four independent demos, no single spine | Reads as a checklist; leaves the classifier centerpiece outside the loop/agent story. |
| Standalone RAG demo for L2 | Sits off to the side, breaks the single-protagonist throughline, and duplicates grounding the classifier already has. |
| Build all four levels now | Violates one-concern-per-session; L4 depends on L3 rungs that are unbuilt. "Cover all four" is the destination, sequenced, not one build. |

---

## Amendment — 2026-07-17: governance primitives for L3/L4

The original decision fixed the *spine*; it left L3 (autonomous loop) and L4 (multi-agent)
without a concrete safety-and-control vocabulary. This amendment adopts four established
governance primitives as **design inputs** for those still-unbuilt levels. None of these are
novel — they are standard patterns from fault-tolerant systems and access control — but stating
them here keeps the L3/L4 build from re-deriving the obvious and gives the writeup a defensible
control story. Prior art reviewed: a reference implementation applying these to agent-action
approval ([`chrisipanaque/agent-approval-gates`](https://github.com/chrisipanaque/agent-approval-gates));
the circuit breaker traces to Nygard's *Release It!*, and the proposal → policy → decision → audit
shape is the classic access-control gate.

| Primitive | What it is | Where it lands on the ladder |
|-----------|-----------|------------------------------|
| **Circuit breaker** | Track an actor's recent rejection/failure rate over a rolling window; once it crosses a threshold (with a minimum-sample floor so noise doesn't trip it), halt and escalate. | **L4 self-halt / Goodhart guard.** The direct answer to "a loop that keeps optimizing the wrong thing" — the runaway loop trips its own breaker instead of running unbounded. This is the primitive the L4 spec was missing. |
| **Gate taxonomy** | An action proposal (`action_type`, `risk_level`, `confidence`, `reasoning`, `payload`) is evaluated to one of `BLOCKING` / `ESCALATING` / `VALIDATING` / `ADVISORY`. | **L3 vocabulary.** Turns the abstract "human-in-the-loop" rung into a concrete state machine: propose → evaluate → decide → audit. `ADVISORY` = "logged, no block" is the recommend-never-act mode. |
| **Fail-closed default** | An action with no matching policy defaults to `BLOCKING`, never to allow. | **Ladder-wide safety default.** An agent meeting a novel action it has no rule for must require approval, never self-authorize. Cheap to state, load-bearing under autonomy. |
| **Confidence × risk bypass** | High confidence + low risk auto-approves (drops to advisory); anything else stays gated. | **The graduation rule.** Operationalizes the ladder's core claim that autonomy is *earned per-capability* — the agent runs unattended on actions it is measurably good at and stays gated on the rest. |

A fifth, smaller steal: an **append-only audit log** tagging each transition's actor as human vs
agent. It is both a control primitive and portfolio evidence — an immutable "who approved what"
trail is the kind of artifact that survives a skeptical reviewer, and it mirrors the prog-log
instinct applied to agent decisions.

**Scope note:** this is a design input, not a build order. These primitives are adopted *on paper*
for L3/L4; per one-concern-per-session they get implemented when those levels are picked up, and
the [autonomy-ladder spec](../docs/specs/autonomy-ladder.md) is where the concrete design will
land. Nothing here changes L1/L2, which are shipped.
