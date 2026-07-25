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
| Authority | Advisory, enforced by `continue-on-error: true` | A non-deterministic reviewer that can turn CI red trains the habit of ignoring red. The gates stay deterministic. Enforced at the CI level, not by convention — see Consequences. |
| Permissions | `contents: read`, `pull-requests: write`, `issues: read`, `id-token: write` | Comment-only. `id-token: write` is required: the action exchanges a GitHub OIDC token for its App token and fails before reaching the model without it. |
| Trigger | `pull_request: [opened]` + `issue_comment: [created]` | `synchronize` re-reviews on every push: a charge per push and a stream of near-duplicate comments on unfinished work. One automatic pass, then `@claude` on demand — the comment trigger is what makes that phrase fire at all. |
| Comment-trigger abuse | `author_association == 'OWNER'` | `issue_comment` runs in the base repo **with secrets** even for outside commenters — unlike fork `pull_request`, GitHub does not withhold them. Without this guard any stranger could spend the repo's API key by typing `@claude`. |
| Fork PRs | Skipped via `head.repo.full_name == github.repository` | GitHub withholds secrets from fork runs, so the job would fail on a missing key — a red X a contributor cannot fix and did not cause. |
| `pull_request_target` | **Not used** | Runs untrusted fork code in the base repo's context *with* secrets. Same reasoning already recorded in `evals.yml`'s header. |
| Model | `claude-sonnet-5`, pinned | [SYS-002](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-002-model-tier-standard.md): exact IDs, no date suffixes. Review is not a task an eval has shown needs the escalation tier. |
| Cost bound | `--max-turns 20` | Caps the agentic loop so a pathological diff cannot run an unbounded bill. Measured here: ~$0.14 on small doc-only diffs; kb-agent's larger prompt runs ~$0.37. |
| Tool grant | `--allowedTools` naming `Read,Grep,Glob` + the comment tools | Required, and it fails **silently** without them — see Consequences. |

The prompt is aimed at this repo's actual failure modes rather than generic code review: metric
drift without an artifact regen, hand-typed eval numbers, unpinned model IDs, ADRs missing
downstream surfaces, non-public-domain text ([ADR-015](015-public-domain-data-sourcing.md)).

## Consequences

- **Cost is real but small and bounded.** One review per PR opened, `--max-turns 20`, Sonnet
  pricing. Measured across four live runs: **$0.14** on a small doc-only diff, **$0.41** on a
  review that actually reads source. At this repo's PR volume that is single-digit dollars a
  month, and the `opened`-only trigger means it does not scale with pushes. This is a smaller and
  more predictable spend than `evals.yml`'s live lane, which ADR-007 already accepted.

  *This bullet said `--max-turns 8` until 2026-07-25, two bumps after the value changed — and it
  was **the review lane itself that caught it**, on the first run under the widened grant. A
  worked example of the drift SYS-019 is about: a number restated in prose beside a table that
  owns it, with nothing comparing the two. Left as an anecdote rather than wired to a check, since
  a workflow flag is not a published artifact and SYS-019's tier 3 ("list, when neither is
  possible") is the honest tier here.*
- **A second reader exists where there was none.** This is a solo repo; every merge to date has
  been self-reviewed. The value is not that the model is a better engineer, it is that it is not
  the person who just wrote the code.
- **Advisory means ignorable, and that is the point.** A comment that is wrong costs one dismissal.
  A gate that is wrong costs a blocked merge and, eventually, a habit of merging past red.
- **"Advisory" needed enforcing, not just intending.** The first run of this lane failed — a
  missing `id-token: write` scope — and posted a red X on a PR whose real gates were all green.
  That is precisely the failure this ADR set out to avoid, produced by the lane meant to avoid it.
  `continue-on-error: true` on the job is the fix: infrastructure failures here (expired key,
  action outage, rate limit) now surface without turning the PR red. Recorded because the gap
  between "we intend this to be advisory" and "CI treats it as advisory" is invisible until
  something breaks.
- **The prompt is a maintained surface.** It names specific files and ADRs; when those move, the
  prompt goes stale and starts asking for things that no longer apply. It is listed below.
- **Reviews will sometimes be shallow or wrong.** No eval backs this lane's output quality — it
  ships on judgment, unlike every capability claim this repo makes. If it produces noise, the
  honest response is to tighten the prompt or remove the lane, not to leave it running and unread.
- **A green run does not mean a review happened.** The second live run passed in 36 seconds,
  spent $0.14 across 7 turns, and posted nothing. `--allowedTools` had not been set, so the
  action denied every attempt to comment — `permission_denials_count: 6` — and tool denials are
  not job failures. From the checks list it was indistinguishable from a healthy run. The
  workflow now names the comment tools explicitly, and the prompt states that posting *is* the
  deliverable. Worth internalizing beyond this lane: **this repo's other CI jobs fail loudly when
  they do nothing; an agentic job succeeds quietly.** The check to trust is a posted comment, not
  a green tick.
- **This lane shipped with a latent version of kb-agent's failure, and got away with it.**
  Until 2026-07-25 the grant named only the comment and `gh pr` tools — no `Read`/`Grep`/`Glob` —
  while the prompt asks about `src/classify.py`, `evals/metrics.json` and the dormant model pins.
  Both PRs that exercised it happened to be small and doc-only, so it never needed to open a file
  and never hit the wall. [kb-agent's ADR-008](https://github.com/sanlee-ys/kb-agent/blob/main/decisions/ADR-008-claude-code-action-pr-review.md)
  hit it immediately on a prompt that did require reading source: **12 denials, 16 turns, $0.50,
  turn cap reached, nothing posted.** Widened here as a fast-follow before a `src/` PR found it.
  The lesson generalises past the flag: **a lane validated only on its easy case is not validated.**
  Both test PRs here were doc-only, which is exactly the shape that exercises the least.
- **Dependabot PRs are not reviewed, and the run still says "success".** The action refuses
  bot-authored PRs by default — *"Workflow initiated by non-human actor: dependabot (type: Bot).
  Add bot to allowed_bots list or use `*` to allow all bots."* The step exits 1, but
  `continue-on-error: true` means the job reports success and the PR stays green. **Accepted, not
  fixed:** a dependency bump is a lockfile and version pins, `tests.yml` and `evals.yml` are the
  real gate on it, and reviewing every bump would cost $0.14–0.41 each for close to no signal.
  Recorded because the alternative is a reader assuming every PR gets reviewed when a recurring
  class of them never does — the lane's coverage is smaller than its presence suggests. An
  `allowed_bots` input exists if that judgement ever changes.

  Worth noting what this proved incidentally: it is the first time the advisory design was tested
  by something nobody staged. An infrastructure-level failure inside the lane left a PR with all
  its real gates green — which is exactly what `continue-on-error` was added for.
- **The lane cannot review changes to itself, by design.** A PR that edits
  `.github/workflows/claude-review.yml` makes the head-ref copy differ from the default branch's,
  and the action refuses to run: *"The workflow file must exist and have identical content to the
  version on the repository's default branch."* That guard is correct — it stops a PR from
  rewriting the reviewer that is about to review it — but the consequence is that **workflow
  changes are exactly the class of change this lane will never see.** They get human review only.
  Verifying a change to this lane therefore means merging it and then triggering `@claude` from
  the default branch, not opening a PR and watching for a comment that structurally cannot come.

## Downstream surfaces

Surfaces this decision touches, and their state as of 2026-07-24:

| Surface | State |
|---|---|
| `.github/workflows/claude-review.yml` | **New.** The lane itself. Note it cannot review its own changes (see Consequences) — edits here need human review and post-merge `@claude` verification. |
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
