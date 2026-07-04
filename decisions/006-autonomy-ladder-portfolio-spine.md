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
| **L2** Augmented | BM25 retrieval grounding | shipped (v2.0.0) |
| **L3** Autonomous loop | prompt-opt loop → agent-driven ML loop (ADR-005) | spec'd |
| **L4** Multi-agent | triage → classify → critic with backward handoff | to spec |

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
