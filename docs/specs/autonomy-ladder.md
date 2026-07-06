# Roadmap — The Autonomy Ladder (portfolio spine)

**Version:** 0.1 (Living roadmap)
**Status:** Accepted direction
**Author:** San Lee
**Last updated:** 2026-07-04
**Decision record:** [ADR-006](../../decisions/006-autonomy-ladder-portfolio-spine.md)
**Related:** [prompt-optimization-loop spec](prompt-optimization-loop.md) (implements Level 3) · [master PRD](../PRD.md)

---

## 1. What this is

The portfolio's spine is an **autonomy ladder**: one protagonist — this classifier —
climbing four levels of self-direction. Each level is the *same system* handed more
autonomy, not a separate demo. A reviewer should be able to follow a single throughline
from Level 1 to Level 4 rather than piece together four disconnected artifacts.

This roadmap is the map. The per-level specs and ADRs are the territory.

## 2. The ladder

| Level | What the classifier gains | Who drives | State |
|-------|---------------------------|-----------|-------|
| **L1 — Single call** | Prompt + structured `{category, operational_domain}` + eval | Human runs each item | **Shipped** (v1) |
| **L2 — Augmented** | BM25 retrieval grounds the label in a corpus | Human runs it; the model reaches for a tool | **Shipped** (v2.0.0) |
| **L3 — Autonomous loop** | Wrapped in a loop that iterates to an explicit done-signal | The system decides when it is done | **Spec'd** — see [ADR-005](../../decisions/005-agentic-prompt-optimization-loop.md) |
| **L4 — Multi-agent** | Decomposed: triage → classify → critic that can hand work *backward* | Multiple agents coordinate | **To spec** |

## 3. Vocabulary (avoid the collision)

Two numbering schemes are in play. Keep them distinct:

- **Level** (this doc) = a rung on the autonomy ladder, L1 through L4.
- **rung** (lowercase, in the [loop spec](prompt-optimization-loop.md)) = a sub-step *inside* L3.
  The loop's *rung 1* (prompt-optimization loop) and *rung 2* (agent-driven ML loop) are
  **both single-agent loops**. They live entirely within L3. Neither is L4.

So: L3 is one level of the ladder that happens to be delivered in two loop rungs. L4 is a
different thing — multiple agents.

## 4. What actually separates the levels

Since the classifier "calls something" at both L2 and L4, the boundary is **not** "invokes a
tool." The distinguishing axis is *who drives and how many autonomous actors*:

- **L2** — single-shot, human trigger. It just has a retrieval tool.
- **L3** — the system decides to iterate toward a goal on its own.
- **L4** — multiple agents coordinate, with handoff.

The L4 honesty test: a **critic that can bounce a label backward** for reclassification, not a
linear pipeline with extra steps. That backward edge is also where the Goodhart story lives —
the critic is what catches the classifier gaming its own metric.

## 5. Design decisions baked into the spine

**RAG is folded into the classifier, not a standalone demo.**
- *Why:* the classifier is the centerpiece. A separate RAG toy would sit off to the side and
  say nothing about the spine. Grounding *inside* the classifier keeps one throughline from L1
  to L4. This is already the built reality as of v2.0.0, so the decision ratifies what shipped
  rather than proposing new work.
- *Tradeoff accepted:* folding RAG in loses the standalone "I did RAG" checkbox a skimming
  technical reader might scan for. The fix is a **writeup** fix, not an architecture one — the L2
  writeup names the technique explicitly ("retrieval-augmented grounding via BM25") even though
  it is embedded.

**Autonomy, not model adaptation, is the spine.**
- *Why:* the alternative framing (prompt → RAG → fine-tune → pretrain) is about *how you build
  with a model*. This portfolio's differentiator for a systems/TPM audience is *how much the
  system drives itself*. Adaptation techniques (RAG, and any future fine-tuning) are treated as
  **ingredients used within a level**, not as levels themselves.

## 6. Sequencing & scope guard

- L1 and L2 are shipped. No further work owed on the spine there beyond the L2 writeup framing.
- **L3 is next**, delivered as the loop spec's rung 1 then rung 2. Sequenced after v2.1.0 for
  the reason in the loop spec (v2.1.0 shrinks the held-out noise floor the loop's honest number
  depends on).
- **L4 is a new level stacked on two loop rungs that are not built yet.** Per one-concern-per-session,
  L4 gets its own spec + branch **after** L3's rungs land. "Cover all four" is the destination,
  not a single build. When L4 is picked up, it earns its own feature spec and an ADR.

## 7. Showcase & cascade

The ladder is the organizing story for the outward surfaces. Each level, as it lands, cascades
(one body of work, transformed per surface):

- **This repo** — the level's code, spec, ADR, and eval artifacts (ground truth).
- **architecture repo** — the cross-repo "how we build the autonomy ladder" pattern (SYS layer).
- **portfolio project page** (`/projects/defense-news-classifier.html`) — the outward showcase.
  Each level's recorded demo + a Decision → Why → Tradeoff writeup lands here, so the classifier's
  whole ladder is told on one page. This page already covers L1 (the single call) and L2 (the BM25
  grounding result); L3 and L4 extend the same page as they ship.
- **portfolio `/lab`** — front-end craft only, **not** the demo's home. `/lab` stays a pure
  front-end sandbox (decided 2026-07-04). The replay player's front-end *techniques* (e.g. SVG
  accuracy curves, a step-through UI) may earn a `/lab` learning-log entry as a technique, but the
  demo itself is showcased on the project page above.
- **learning-notes** — concept-first notes (loop engineering, Goodhart in eval-driven
  optimization, multi-agent handoff), not a project changelog.
- Aggregated surfaces (portal, portfolio nav, learning-notes index/map) are wired by a **single
  integrator**, once, after the content lands.
