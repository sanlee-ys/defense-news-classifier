# Design note — L4 control-flow vocabulary

**Status:** Design input. Not a build order. No level of the autonomy ladder owes further build work today.
**Author:** San Lee
**Last updated:** 2026-09-20
**Related:**
[l4-multi-agent spec](l4-multi-agent.md) (the built-and-measured L4 v1) ·
[l4-context-loss-injection spec](l4-context-loss-injection.md) (the open, pre-registered, unrun measurement of L4's unvalidated edges) ·
[autonomy-ladder](autonomy-ladder.md) §6 (the ladder is fully climbed) ·
[ADR-020](../../decisions/archive/020-l4-multi-agent-pipeline.md) (L4 v1's verdict) ·
[ADR-006 amendment](../../decisions/006-autonomy-ladder-portfolio-spine.md#amendment--2026-07-17-governance-primitives-for-l3l4)
(the precedent for recording a design input on paper, ahead of a build)

---

## 1. What this note is, and what it is not

This note records three external control-flow shapes as design input for a possible future L4 iteration. It is not a spec. It orders no build work. It does not touch `src/l4_pipeline.py`, `src/l4_inject.py`, any prompt, or any eval.

The parking-lot idea behind this note (`desk/ideas.md`, parked 2026-07-19) was written before the L4 spec existed. L4 has since gone through a full spec-build-measure cycle ([l4-multi-agent.md](l4-multi-agent.md), [ADR-020](../../decisions/archive/020-l4-multi-agent-pipeline.md), 2026-07-25). The autonomy ladder is now fully climbed: no level owes further build work ([autonomy-ladder.md](autonomy-ladder.md) §6). This note is not design input for an unbuilt L4. It is design input for a **future L4 re-attempt only**, and only if one is picked up.

Two live hooks exist for that re-attempt, and this note serves both:

1. **HANDOFF's job 4** names "a structurally narrowed critic" as an explicit option, not a commitment, that needs its own spec and ADR rather than a patch to ADR-020.
2. **[l4-context-loss-injection.md](l4-context-loss-injection.md)** is a pre-registered, built-but-unrun experiment that measures whether L4's node boundaries (which carry no schema check today) drop information that matters. Its result, once run, is direct evidence for or against one of the three shapes below.

## 2. Why a second look at L4's control flow is even on the table

L4 v1's honesty test passed. The critic's backward edge fixed 6 of the 7 named `global`-cluster rows. But the all-axes critic challenged 57.4% of rows against an expected ~13%, and did net harm on the domain axis (gold 92.6% to 81.5%, scale 91.3% to 86.7%, p=0.016), at roughly 4x the cost of one call. The charter meant to narrow the critic ("rubric-checkable evidence claims only") lived entirely in the prompt. A restraint stated only in a prompt did not hold under measurement.

HANDOFF job 4 names one fix: gate the critic in code so it fires only where triage reports `none stated`, on region alone, rather than trust a prompt instruction across all three axes. That is a control-flow change, not a prompt change. That is why the three sources below are control-flow shapes, not prompting techniques.

## 3. Three design inputs

### 3.1 `openai/swarm` — the handoff primitive

Swarm's core idea is small: an agent function can return a `Handoff` object that names the next agent, and the runtime transfers control to that named recipient. The primitive is explicit control transfer to a named recipient. It is not an implicit retry, and not a hard-coded call site shared by every caller.

L4 v1's backward edge is one hard-coded re-classify call, capped at one bounce, triggered by any valid challenge regardless of which axis the challenge names. Swarm's shape suggests a sharper primitive: a challenge on axis X hands off to a handler named for X, not to the same undifferentiated re-classify call every axis shares today. That is close kin to HANDOFF job 4's own proposal (a region-only critic), stated as a general mechanism instead of one special case.

Swarm is deliberately small and educational, not a production framework. That is the property this note cites, not the code.

### 3.2 `langchain-ai/langgraph` — typed state and checkpoint/resume

LangGraph models a run as a graph of nodes that read and write one typed state object, with a checkpointer that saves that state after every node and can resume a run from any saved point.

L4 v1 already has two of the three pieces, built without the framework: `src/l4_pipeline.py` is resume-safe per row, and its append-only audit JSONL records every triage note, label, challenge, bounce, and final label (the audit-log primitive ADR-006's amendment already adopted). What L4 v1 does not have is a **typed** state contract. The fields that move between triage, classify, and critic are the pipeline driver's own dict shape, not a schema checked at the boundary.

This gap is not hypothetical, and it is not new to this note. [l4-context-loss-injection.md](l4-context-loss-injection.md) §1 states it directly: "There is no schema check, no presence check and no shape assertion at any node boundary." That pre-registered experiment is built and unrun; its H1 asks whether a payload dropped at an unwatched edge ships a wrong answer, and its H2 asks whether most of what these edges carry is not load-bearing at all. If H1 lands, that is direct evidence for a typed-state contract at the node boundaries. If H2 dominates instead, most of the state these edges carry does not matter, and a schema would formalize a contract with little content behind it. This note does not run that experiment or change its content; it names the result as the evidence a future typed-state proposal would have to cite.

The design input here is narrow: a typed state schema at each node boundary, checked the way `contracts/classify-response.schema.json` already checks the classifier's own output. It is a schema decision, not a persistence decision. The persistence piece is already built, and it is already append-only on purpose.

### 3.3 Anthropic, "Building Effective Agents" — the workflow-vs-agent distinction

Anthropic draws one line worth keeping. A workflow uses fixed code paths to run LLM calls and tools. An agent decides its own next step and its own tool use as it runs. The guide names five workflow patterns (prompt chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer) and argues for the simplest pattern that clears the measured bar, before any move toward an agent.

[autonomy-ladder.md](autonomy-ladder.md) §4 already answers this for L4 v1 in its own words: "Mechanized: routing, but statically, since the node order is fixed in `process_row` and never chosen at runtime." L4 v1 is a **workflow** by Anthropic's definition, and specifically the evaluator-optimizer pattern (the critic evaluates, the re-classify call optimizes). It is not an agent. That is not a gap. Anthropic's own guidance favors the simplest pattern that clears the bar, and a fixed three-node workflow is simpler than an agent that routes itself.

The design input is the question this framing forces onto any future attempt: does a narrower critic still fit inside a workflow (the node order stays fixed; the LLM decides content only), or does it need dynamic routing (the LLM decides which node runs next) to work at all? HANDOFF job 4's proposal (gate the critic on triage's `none stated` signal) is answerable inside the workflow frame, as a code-level `if`, with no dynamic routing required. Nothing ADR-020 measured argues for turning L4 into an agent.

## 4. Mapping onto the classifier's existing vocabulary

| Source shape | Classifier's existing piece | What a future iteration would change |
|---|---|---|
| Handoff, named recipient | The single hard-coded re-classify call, bounce cap 1 (the circuit-breaker primitive, ADR-006 amendment) | Named-recipient handoffs per axis, in place of one undifferentiated call every challenge shares today |
| Typed state, checkpoint/resume | The append-only audit JSONL, already resume-safe per row | A typed schema checked at each node boundary; the persistence model itself would not change |
| Workflow vs. agent | The fixed `process_row` node order (autonomy-ladder.md §4, "Mechanized: routing, but statically") | A named vocabulary for stating, up front, that a narrower critic stays a workflow and needs no dynamic routing |

## 5. What a future L4 iteration must NOT import

- **No framework dependency.** `crewai`, `langgraph`, and the swarm successor do not enter `pyproject.toml`. CLAUDE.md's tech stack section holds the LLM client plus `pandas` as the whole dependency list, and L4 v1 was built hand-rolled against the Messages API on that same contract ([autonomy-ladder.md](autonomy-ladder.md) §7). A framework import would replace the mechanism this portfolio exists to demonstrate with a mechanism the framework demonstrates instead. This is the portfolio-spine test named in ADR-006: the classifier is the single protagonist, and importing another orchestration engine hands the protagonist's role to the dependency.
- **No dynamic node spawning.** Section 3.3 above answers this directly: a narrower critic is answerable inside a workflow. Nothing ADR-020 measured argues for an agent that spawns or chooses its own nodes at runtime.
- **No mutable checkpoint store.** LangGraph's checkpointer supports overwrite and branch. The classifier's audit log is append-only on purpose (ADR-006 amendment): an immutable "who approved what" trail is itself portfolio evidence. A future iteration keeps the append-only shape and takes only the typed-state idea from LangGraph, not its storage engine.
- **Do not reopen the hand-roll decision.** [autonomy-ladder.md](autonomy-ladder.md) §7 already weighed Managed Agents against a hand-rolled build and chose to hand-roll, for reasons specific to the backward edge and the persistence model. This note does not reopen that decision. Each of the three sources above was picked because it contributes a vocabulary word, not a runtime.

## 6. Open questions a future L4 spec would have to answer

1. Does a named-recipient handoff, generalized past the single bounce-cap-1 case, change the measured outcome, or does it only change the code's shape? ADR-020's harm came from an over-broad charter (57.4% challenge rate against an expected ~13%), not from the single-call handoff mechanism itself. A future spec has to show the generalized primitive fixes the charter, not just the plumbing.
2. Does a typed state schema at each node boundary change a measured outcome, or is it a documentation improvement only? [l4-context-loss-injection.md](l4-context-loss-injection.md) is the pre-registered instrument that answers this, once it is run. A future spec should read that result first rather than propose a schema on priors alone.
3. Where does the line sit between "a narrower critic, still a workflow" and "a critic that needs dynamic routing to work"? Section 3.3 argues the region-only proposal stays a workflow. A future spec has to state the test that would prove that argument wrong.
4. Does a future L4 re-attempt clear this repo's measure-first bar before it is built at all? Six of ten experiments in this repo's history declined the change they measured ([decisions/README.md](../../decisions/README.md)). The ladder is fully climbed and owes no further build work ([autonomy-ladder.md](autonomy-ladder.md) §6). A future spec has to argue why a re-attempt is worth measuring again, not assume it is.

## 7. Sources

- `openai/swarm` — https://github.com/openai/swarm (verified reachable, 2026-09-20)
- `langchain-ai/langgraph` — https://github.com/langchain-ai/langgraph (verified reachable, 2026-09-20)
- Anthropic, "Building Effective Agents" — https://www.anthropic.com/engineering/building-effective-agents (verified reachable, 2026-09-20)
