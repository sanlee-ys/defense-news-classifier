# Roadmap — The Autonomy Ladder (portfolio spine)

**Version:** 0.1 (Living roadmap)
**Status:** Accepted direction
**Author:** San Lee
**Last updated:** 2026-07-11
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
| **L2 — Augmented** | BM25 retrieval grounds the label in a corpus | Human runs it; the model reaches for a tool | **Shipped** (v2.0.0), then **retired** ([ADR-012](../../decisions/012-retire-bm25-grounding.md)) |
| **L3 — Autonomous loop** | Wrapped in a loop that iterates to an explicit done-signal | The system decides when it is done | **Partly shipped** — rung 1 ([ADR-005](../../decisions/005-agentic-prompt-optimization-loop.md)) rode the `v2.1.0` tag; rung 2 ([ML bake-off](ml-baseline-bakeoff.md)) spec'd, unbuilt |
| **L4 — Multi-agent** | Decomposed: triage → classify → critic that can hand work *backward* | Multiple agents coordinate | **To spec** — build-vs-adopt decided, see [§7](#7-l4-build-vs-adopt-decision-2026-07-11) |

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

**Governance primitives are adopted on paper for L3/L4.**
- Four established control patterns — a **circuit breaker** (L4 self-halt / Goodhart guard), a
  **gate taxonomy** (L3's propose → evaluate → decide → audit vocabulary), a **fail-closed default**,
  and a **confidence × risk graduation rule**, plus an append-only **audit log** — are adopted as
  design inputs so the L3/L4 build doesn't re-derive them. Full rationale and prior art in the
  [ADR-006 amendment](../../decisions/006-autonomy-ladder-portfolio-spine.md#amendment--2026-07-17-governance-primitives-for-l3l4).
- *Scope:* design input only. The concrete implementation is designed when L3/L4 are picked up
  (§6), not now.

## 6. Sequencing & scope guard

- L1 and L2 are shipped. No further work owed on the spine there beyond the L2 writeup framing.
  L2's grounding was subsequently **retired** ([ADR-012](../../decisions/012-retire-bm25-grounding.md))
  after a fair same-prompt re-measure — 0 domain calls fixed, 4 broken across 162 grounded
  classifications. The rung stands: the axis is *who drives*, and L2's question (can the model
  reach for a tool?) was answered yes. The tool just did not earn its place. The climbed-then-
  retired arc is the honest L2 story and the writeup should tell it that way.
- **L3 is in progress**, delivered as the loop spec's rung 1 then rung 2. Rung 1 was sequenced
  after v2.1.0 for the reason in the loop spec (v2.1.0 shrinks the held-out noise floor the
  loop's honest number depends on) and **shipped on the `v2.1.0` tag**. **Rung 2 is next** —
  the agent-driven ML loop, whose substrate is the [ML baseline bake-off](ml-baseline-bakeoff.md)
  (spec'd, unbuilt). L3 is not complete until rung 2 lands.
- **L4 is a new level stacked on two loop rungs that are not built yet.** Per one-concern-per-session,
  L4 gets its own spec + branch **after** L3's rungs land. "Cover all four" is the destination,
  not a single build. When L4 is picked up, it earns its own feature spec and an ADR. The one L4
  decision already settled — *build the multi-agent orchestration by hand vs. adopt a managed-agent
  framework* — is recorded in [§7](#7-l4-build-vs-adopt-decision-2026-07-11) so the eventual spec
  inherits it rather than re-litigating it.

## 7. L4 build-vs-adopt decision (2026-07-11)

L4 is still "to spec" — no triage/classify/critic prompts or control flow are designed yet. But one
question that would otherwise get re-argued *during* that spec is already answerable from Anthropic's
Claude Managed Agents documentation, so it is settled here up front: **do we hand-roll L4's
multi-agent orchestration against the Messages API (the way L3's `optimize.py` is hand-rolled), or
adopt a managed-agent framework to get orchestration + persistence "for free"?**

**Decision: hand-roll L4, same as L3.** Build the triage → classify → critic coordination directly
against the Messages API, with no managed-agent framework. Rationale below.

**Why — Managed Agents solves neither of L4's two open design questions natively:**

- **The backward edge (multi-agent orchestration).** L4's whole honesty test (§4) is a critic that
  can bounce a label *backward* to triage for reclassification — a peer-to-peer edge, not a linear
  pipeline. Managed Agents' `multi-agent` primitive is **hub-and-spoke only**: a coordinator
  delegates to spokes, and depth > 1 is ignored (a spoke cannot call another spoke directly). A true
  backward handoff is not a first-class pattern. You'd simulate it via the coordinator's own prompt
  logic deciding whether to re-invoke an earlier spoke's thread — which is the *same* design problem
  hand-rolled anywhere, just relocated into a coordinator system prompt instead of our own
  orchestration code. Adopting the framework doesn't answer the hard question; it moves where we
  write the answer.

- **The persistence model (memory).** Managed Agents' memory stores do give genuine cross-run
  persistence, but they are a **mutable document store** — create/update/delete by path, versioned —
  not an append-only ledger. That is the wrong shape for "replay every run in order, forever," and
  better suited to "curated running state the pipeline reads and updates each invocation." L4's
  persistence model is precisely one of the things its spec still has to decide; the framework's
  built-in store presupposes an answer we haven't chosen.

**Tradeoff accepted — what we give up by hand-rolling, and why it's worth it:**

- **No pricing is published anywhere** across the Managed Agents docs, and the product is still
  **beta**. Adopting it means taking a beta dependency with unknown cost against a solo, single-repo
  project whose whole guiding principle (§5, and the classifier's own versioning roadmap) is
  "measure the cost before you spend it." You can't measure what isn't priced.
- The **self-hosted path** — likely the more natural fit for a solo project wanting cost and data
  control — is not a shortcut either: it requires standing up and operating your own worker process,
  rotating keys, and hardening a sandbox image. That is real infra to own, traded for orchestration
  we'd still have to shape by hand anyway.
- Against all that, hand-rolling costs us the framework's managed sandbox and turnkey multi-agent
  plumbing. For L4 that plumbing is hub-and-spoke — the one topology L4 explicitly is *not* — so the
  thing we forgo is largely a thing we couldn't use.

**Scope guard:** this is a decision about *approach*, recorded so the eventual L4 spec doesn't
re-open it. It is **not** an implementation. The triage/classify/critic agents, their prompts, and
their control flow remain unbuilt and unscoped — L4 still earns its own feature spec + ADR when
L3's rungs land (§6).

## 8. Showcase & cascade

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
