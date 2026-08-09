# Roadmap — The Autonomy Ladder (portfolio spine)

**Version:** 0.1 (Living roadmap)
**Status:** Accepted direction
**Author:** San Lee
**Last updated:** 2026-08-09
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
| **L3 — Autonomous loop** | Wrapped in a loop that iterates to an explicit done-signal | The system decides when it is done | **Built** — rung 1 ([ADR-005](../../decisions/005-agentic-prompt-optimization-loop.md)) rode the `v2.1.0` tag; rung 2 ([ADR-018](../../decisions/018-agent-driven-ml-loop.md), `src/ml_loop.py`) built 2026-07-25 on the [ML bake-off](ml-baseline-bakeoff.md) substrate, and its first live run **measured negative transfer**: the best-by-B iteration scored B 0.699 (+6.0) while held-out C fell to 0.545 (−8.6), caught by the split design rather than by luck |
| **L4 — Multi-agent** | Decomposed: triage → classify → critic that can hand work *backward* | Multiple agents coordinate | **Built + measured** ([ADR-020](../../decisions/020-l4-multi-agent-pipeline.md), 2026-07-25): the backward edge works — 6/7 of the named region cluster fixed — but the all-axes critic over-challenged (57% rate) and did net harm at 4× cost, so the pipeline is **declined as configured**; the shipped single call stays production. Both halves are the L4 story. |

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

**L4 is a work graph, and that claim needs its qualifiers.** In the sense the term *graph
engineering* acquired in 2026 (typed nodes, edges carrying state between them, and a harness that
routes and observes the whole thing), L4 is one, and per
[SYS-022](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-022-org-graph-and-the-mechanization-split.md)
Amendment 1 it is the only built-and-measured work graph anywhere in this system. That record's
discipline is that the unqualified claim is not available, so here is the split for
`src/l4_pipeline.py`. **Mechanized:** routing, but *statically*, since the node order is fixed in
`process_row` and never chosen at runtime; observability, genuinely, via an append-only per-run
audit JSONL recording every triage note, label, challenge, bounce, and verdict; and node policy
in code rather than in prompt hope, since `challenge_violations` discards any challenge that
names no axis, cites no rubric rule, or states no evidence gap, failing closed to accept, and the
bounce cap is structural because there is exactly one re-classify call site. **Never had:**
dynamic node spawning (the three nodes are fixed in the driver), and cross-process state
consistency (the whole graph runs in one process, so there is no edge that can silently drop
state between machines).

**What the measurement exposed is the honest half.** All three of those governance primitives
guard against a bad *critic*. Nothing validates upstream state: `classify()` takes no evidence
argument at all, so the classifier is blind to triage by construction. That was a deliberate
fork, resolved 2026-07-25 ([l4-multi-agent](l4-multi-agent.md) §9.1) so the run would measure the
critic's marginal value rather than a different classifier, and the consequence is that the
guards sit at the boundary that was easy to reason about rather than at the one carrying the
risk. Silent context loss at a handoff is the graph layer's characteristic failure, and L4 has no
instrument pointed at it. None of that is a fifth level. It describes L4 against a different axis
(how state moves between actors) than the ladder's own, and a rung cannot be built out of a
re-description.

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
  retired arc is the honest L2 story and the writeup should tell it that way. **Addendum
  (2026-07-25):** the L2 question is now fully closed as a three-shape measured series —
  neighbor docs harmful ([ADR-012](../../decisions/012-retire-bm25-grounding.md)), mined
  keyword features harmful off-distribution ([ADR-018](../../decisions/018-agent-driven-ml-loop.md)
  amendment), labeled few-shot exemplars inert ([ADR-019](../../decisions/019-knn-exemplar-fewshot.md),
  null at n=300 paired). The writeup gets to say "every retrieval shape was tried and
  measured," which is a stronger L2 close than one retirement.
- **L3 is complete**, delivered as the loop spec's rung 1 then rung 2. Rung 1 was sequenced
  after v2.1.0 for the reason in the loop spec (v2.1.0 shrinks the held-out noise floor the
  loop's honest number depends on) and **shipped on the `v2.1.0` tag**. **Rung 2 is built and
  run** (2026-07-25, [ADR-018](../../decisions/018-agent-driven-ml-loop.md)) — the agent-driven
  ML loop in `src/ml_loop.py`, wrapping the executed
  [ML baseline bake-off](ml-baseline-bakeoff.md) ([ADR-017](../../decisions/017-classical-baseline-bakeoff.md))
  with the same A/B/C + done-signal honesty architecture as rung 1. Its first live run is the
  rung's real deliverable: the agent improved the split it could see and degraded the held-out
  one (B 0.699, +6.0; C 0.545, −8.6), and the split design caught it. The Goodhart story is now
  demonstrated end-to-end rather than merely designed for.
- **L4 is built and measured** ([l4-multi-agent](l4-multi-agent.md), Accepted;
  [ADR-020](../../decisions/020-l4-multi-agent-pipeline.md), 2026-07-25): triage →
  classify → critic with the backward edge as a rubric-checkable evidence review, aimed at
  the one named error cluster (the 7× `global`-pulled-to-a-region rows) — the honest
  hypothesis that gave the critic a measurable target instead of vibes. Inherits §7's
  hand-roll decision and the governance primitives (bounce cap = circuit breaker,
  fail-closed accept, evidence-claims-only charter = confidence × risk); the §9 forks resolved
  2026-07-25 to classify blind, cap 1, all-axes critic. **The verdict splits:** the hypothesis
  held (the bounce fixed 6 of the 7 cluster rows) but the pipeline is declined as configured —
  the all-axes critic challenged 57.4% of rows against an expected ~13% and did net harm at
  ~4× cost. The all-axes fork is where it broke, which is worth remembering before anyone
  re-opens §9.

**The ladder is now fully climbed.** No level is owed further build work. The remaining spine
work is writeup and publication, not implementation — and three of the four measured levels
came back negative, which is the honest shape of the story rather than a gap in it.

## 7. L4 build-vs-adopt decision (2026-07-11)

> **Status note (2026-07-25):** L4 has since been spec'd, built, and measured
> ([ADR-020](../../decisions/020-l4-multi-agent-pipeline.md)). The hand-roll decision below
> stands and was honored — `src/l4_pipeline.py` is a plain Python driver against the Messages
> API. The section is preserved as written on 2026-07-11, including its "still to spec"
> framing, because it is a dated decision record and its reasoning is what a future
> framework-adoption question should be argued against.

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
  whole ladder is told on one page. **As of 2026-07-25 the page covers all four levels** — the
  ladder visual and the closing narrative carry L1 through L4, and the L3 paragraph links the
  run replay at `/projects/loop-replay.html`, which now steps through both recorded runs. The
  outstanding gap on that page is not a level: it is the classical-baseline bake-off
  ([ADR-017](../../decisions/017-classical-baseline-bakeoff.md)), which answers "why an LLM at
  all" and is still unpublished there.
- ~~**portfolio `/lab`** — front-end craft only, not the demo's home.~~ **Superseded
  2026-07-23.** The portfolio retired `/lab` as a section and stopped confining interactive
  work to it (portfolio `ADR-004`), on the grounds that the split was discounting its own best
  evidence: the replay viewer was the only interactive proof of L3 and sat under a heading that
  told readers to expect rough edges. The viewer now lives at `/projects/loop-replay.html`,
  beside the claim it supports. Nothing about the ladder's rungs changed — only where the
  evidence is displayed.
- **learning-notes** — concept-first notes (loop engineering, Goodhart in eval-driven
  optimization, multi-agent handoff), not a project changelog.
- Aggregated surfaces (portal, portfolio nav, learning-notes index/map) are wired by a **single
  integrator**, once, after the content lands.
