# ADR-016: Agentic PR review as an advisory lane, not a gate

**Status:** Accepted
**Date:** 2026-07-24
**Deciders:** San Lee

---

## Context

This repo already runs two CI lanes, both **deterministic gates**: `tests.yml` (lint, types,
contract/metrics artifact freshness, ADR lint, coverage floor) and `evals.yml` (an offline
capability gate on every PR, plus a paid live gate on dispatch/schedule per
[ADR-007](007-evals-as-ci-gate.md)). Between them they answer "did this change break something
we can measure."

They cannot answer "is this change *good*" — whether a metric moved without its artifact being
regenerated, whether a number got hand-typed into the README instead of generated, whether a new
ADR skipped its `## Downstream surfaces` section for a reason the linter cannot see. Those are
judgment calls, and today the only reviewer making them is the same person who wrote the change.

`anthropics/claude-code-action` runs Claude against a PR diff on a GitHub runner and posts review
comments. The question this ADR settles is not *whether* the tool works but **what authority it
gets**: a gate that can block a merge, or an advisor that can only speak.

## Decision

**Adopt `anthropics/claude-code-action` as an advisory review lane. It comments; it never fails
the build, and it never pushes.**

Concretely, in `.github/workflows/claude-review.yml`:

| Choice | Value | Why |
|---|---|---|
| Authority | Advisory — no gating step | A non-deterministic reviewer that can turn CI red trains the habit of ignoring red. The gates stay deterministic. |
| Trigger | `pull_request: [opened]` only | `synchronize` re-reviews on every push: a charge per push and a stream of near-duplicate comments on unfinished work. Re-review on demand via the `@claude` trigger phrase. |
| Fork PRs | Skipped via `head.repo.full_name == github.repository` | GitHub withholds secrets from fork runs, so the job would fail on a missing key — a red X a contributor cannot fix and did not cause. |
| `pull_request_target` | **Not used** | Runs untrusted fork code in the base repo's context *with* secrets. Same reasoning already recorded in `evals.yml`'s header. |
| Model | `claude-sonnet-5`, pinned | [SYS-002](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-002-model-tier-standard.md): exact IDs, no date suffixes. Review is not a task an eval has shown needs the escalation tier. |
| Cost bound | `--max-turns 8` | Caps the agentic loop so a pathological diff cannot run an unbounded bill. |
| Permissions | `contents: read`, `pull-requests: write`, `issues: read` | Comment-only. No `contents: write`. |

The prompt is aimed at this repo's actual failure modes rather than generic code review: metric
drift without an artifact regen, hand-typed eval numbers, unpinned model IDs, ADRs missing
downstream surfaces, non-public-domain text ([ADR-015](015-public-domain-data-sourcing.md)).

## Consequences

- **Cost is real but small and bounded.** One review per PR opened, `--max-turns 8`, Sonnet
  pricing. At this repo's PR volume that is single-digit dollars a month, and the `opened`-only
  trigger means it does not scale with pushes. This is a smaller and more predictable spend than
  `evals.yml`'s live lane, which ADR-007 already accepted.
- **A second reader exists where there was none.** This is a solo repo; every merge to date has
  been self-reviewed. The value is not that the model is a better engineer, it is that it is not
  the person who just wrote the code.
- **Advisory means ignorable, and that is the point.** A comment that is wrong costs one dismissal.
  A gate that is wrong costs a blocked merge and, eventually, a habit of merging past red.
- **The prompt is a maintained surface.** It names specific files and ADRs; when those move, the
  prompt goes stale and starts asking for things that no longer apply. It is listed below.
- **Reviews will sometimes be shallow or wrong.** No eval backs this lane's output quality — it
  ships on judgment, unlike every capability claim this repo makes. If it produces noise, the
  honest response is to tighten the prompt or remove the lane, not to leave it running and unread.

## Downstream surfaces

Surfaces this decision touches, and their state as of 2026-07-24:

| Surface | State |
|---|---|
| `.github/workflows/claude-review.yml` | **New.** The lane itself. |
| `ANTHROPIC_API_KEY` repo secret | Already set (2026-07-11, for `evals.yml`'s live lane). Reused, not re-provisioned. |
| The review prompt inside the workflow | **Maintained surface.** Names `src/classify.py`, `src/gold_eval.py`, `src/eval_gate.py`, `src/classify_rag.py`, `evals/metrics.json`, ADR-010, ADR-015, and the `## Downstream surfaces` rule. Update it when any of those move or retire. |
| [ADR-007](007-evals-as-ci-gate.md) | Unchanged. That ADR governs the *gates*; this one adds a lane that deliberately is not one. |
| [ADR-012](012-retire-bm25-grounding.md) | Referenced by the prompt so the reviewer does not flag the dormant grounding code's `claude-sonnet-4-6` pins (`src/classify_rag.py`'s `RAG_MODEL`, `src/generate.py`'s `MODEL`) as stale. [ADR-010](010-rag-path-model-pin.md), which originally set that pin, is superseded by 012 — the prompt cites the live authority, not the superseded one. If the dormant code is ever deleted, drop that prompt clause. |
| `README.md` CI section | **Not updated here.** The README describes the two gates; this lane is advisory and does not change what CI enforces. Worth a line if the lane proves it earns one. |
| `tests.yml`, `evals.yml` | Unchanged. No interaction — separate workflows, separate concurrency groups. |

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Make it a gate that fails the build | A non-deterministic reviewer with merge authority is the wrong trade. The failure mode is not "bad code merges," it is "developer learns red CI is negotiable" — which corrodes the deterministic gates that actually work. |
| Trigger on `[opened, synchronize]` | Charges per push and comments on work still in flight. The action already supports `@claude` for an on-demand re-review, which covers the real need without the default cost. |
| `pull_request_target` so fork PRs get reviewed too | Runs untrusted code with secrets in the base repo context. `evals.yml` already rejected this for the same reason; this repo is public. |
| Let the action push fixes (`contents: write`) | Turns a reviewer into a committer. Commits on this repo carry eval implications; those should come from a human PR, consistent with `evals.yml` never committing refreshed numbers back. |
| Generic "review this PR for quality" prompt | Produces generic findings. This repo's real risks are metric drift and doc staleness, which a generic reviewer has no reason to look for. |
| Skip it — solo repo, self-review is fine | Self-review is exactly the gap. Every published number here is defended by an artifact check *because* asserting your own work is unreliable; the same logic applies to reviewing it. |
