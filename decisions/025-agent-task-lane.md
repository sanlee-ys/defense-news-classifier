# ADR-025: An agent task lane — proposing, on demand, never merging

**Status:** Accepted
**Date:** 2026-08-11
**Deciders:** San Lee

---

## Context

[ADR-016](016-claude-code-action-pr-review.md) gave this repo an agent that can **review** a
PR — advisory, comment-only, on-demand. There was no lane where an agent can **propose** one:
implement a scoped task and put the result up as a PR for the same human + deterministic-gate
review every other PR gets. The pieces exist elsewhere: the review lane already proved the
action, the auth, the model pin and the cost knobs; and agent-ops
[`conventions/agent-in-ci.md`](https://github.com/sanlee-ys/agent-ops/blob/main/conventions/agent-in-ci.md)
defines the assembly rule any agentic pipeline step must satisfy — (1) sandboxed, scoped
credentials; (2) proposal-only output, never a push to a protected branch; (3) a
deterministic verifier after the agent; (4) the redline guards travel with the job.

The question this ADR settles is the same one ADR-016 settled for review: **what authority
does the proposing agent get**, and how is each of the four assembly rules made pointable in
the YAML rather than intended.

## Decision

**Add `.github/workflows/agent-task.yml`: a `workflow_dispatch`-only lane where the agent
implements the dispatched `task` input, pushes a `claude/agent-task-*` branch, and opens a
draft PR. It never merges and cannot push `main`.**

| Choice | Value | Why |
|---|---|---|
| Trigger | `workflow_dispatch` only, required `task` input | The owner launches deliberately; the lane costs nothing idle — the same economics ADR-016 Amendment 1 arrived at, adopted here from day one. No comment phrase, no schedule, no issue trigger. |
| Actor guard | `github.actor == 'sanlee-ys'` at the job `if` | Dispatch is already owner-gated by repo permissions, but a check that could not run is not a pass ([`agent-trigger-authorization.md`](https://github.com/sanlee-ys/agent-ops/blob/main/conventions/agent-trigger-authorization.md)); the assertion keeps holding if a collaborator or dispatching integration ever appears. |
| Permissions | `contents: write`, `pull-requests: write`, `id-token: write`, nothing else | rule 1. `contents: write` pushes the proposal branch; **branch protection on `main` is what makes it proposal-only** — the token can push `claude/agent-task-*`, it cannot push `main`. `pull-requests: write` opens the draft. `id-token: write` is the action's OIDC exchange, same as the review lane. |
| Output shape | Draft PR from `claude/agent-task-<run_id>` (or `-<branch_suffix>`) | rule 2. The PR body carries the task verbatim, the gate output, and an explicit "Not done" section — a proposal a human and the gates judge. |
| Verifier | **Not in this workflow.** `tests.yml` + `evals.yml` + CodeQL run on the proposal PR like any PR | rule 3, satisfied one level up. Agent green is not build green; the PR's own checks are the gate. |
| Guards | Fetched from agent-ops canon (`security/credential-guard.py`, `hooks/git-staging-guard.py`, `hooks/published-history-guard.py`) into `$HOME/.claude/hooks/` and wired as `PreToolUse` hooks **before** the action step; **a fetch failure fails the job** | rule 4. Running unguarded is a posture change relative to every provisioned machine, approved by nobody — so there is no "run anyway" fallback. |
| Model / cost | `claude-sonnet-5` pinned (SYS-002), `--max-turns 50` | Implementation needs more turns than review (four gates, push, PR), still bounded. |
| Auth | `anthropic_api_key: secrets.ANTHROPIC_API_KEY` | Mirrors `claude-review.yml`; one key, one revocation point. |
| `pull_request_target` | Not used, prohibition restated in the header | Moot for dispatch, retained so a future auto-triggered variant does not reintroduce it. |

## Consequences

- **A green run means "a draft PR may exist," nothing more.** An agentic step exits 0
  whether the work landed, was denied, or was never attempted (the review lane measured
  exactly this). The check to trust is the PR and its checks, not the workflow tick.
- **`contents: write` enters the repo's workflow set for the first time**, and its safety
  is delegated to branch protection on `main`. If that protection is ever loosened, this
  scope silently becomes push-to-main and this lane must be re-decided — recorded in the
  workflow header so the coupling is visible where it bites.
- **Guard fetches pin `main`, not a SHA.** The guards are maintained canon and provisioned
  machines deploy from `main`; a SHA pin would be the stale-copy drift agent-ops
  `security/posture.md` limit 6 records. The trade is that an agent-ops `main` outage or a
  moved file fails this job — loudly, which is the designed failure.
- **The prompt is a maintained surface** (gate commands, branch naming, CLAUDE.md
  references), same as the review lane's.
- **Spend is per-dispatch and human-initiated**, so it scales with intent rather than
  events. No idle cost.

## Downstream surfaces

| Surface | State |
|---|---|
| `.github/workflows/agent-task.yml` | **New.** The lane itself. Like the review lane, the action refuses to run when the workflow file differs from `main`'s copy — changes here get human review and post-merge dispatch verification. |
| `ANTHROPIC_API_KEY` repo secret | Reused (set 2026-07-11 for `evals.yml`; also used by ADR-016's lane). Not re-provisioned. |
| Branch protection on `main` | **Load-bearing for this ADR.** It is the mechanism that makes `contents: write` proposal-only. |
| `tests.yml`, `evals.yml`, CodeQL | Unchanged; they are this lane's deterministic verifier by running on the proposal PR. |
| `.github/workflows/claude-review.yml` / [ADR-016](016-claude-code-action-pr-review.md) | Unchanged. Separate lane, separate (smaller) permission envelope; the review lane keeps `contents: read`. |
| agent-ops `conventions/agent-in-ci.md` | The assembly rule this lane implements; the four pointable lines are the `permissions` block, the branch/PR instructions in the prompt, the PR's own CI, and the guard-install step. |
| `README.md` CI section | Not updated — this lane changes nothing about what CI enforces. |

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Auto-trigger on labeled issues or issue comments | Recurring cost the review lane already walked back (ADR-016 Amendment 1), and a wider trigger-authorization surface: issue text is external input reaching a capable agent, and every check in `agent-trigger-authorization.md` would need re-deriving for it. Dispatch keeps the trigger a deliberate human act. |
| A deterministic verifier step inside this workflow | Duplicates what `tests.yml`/`evals.yml`/CodeQL already run on the proposal PR — a second copy that drifts from the first. The PR is the artifact; the PR's checks are the gate. |
| Extend the review lane's workflow instead of a new one | Different permission envelope. The review lane is comment-triggered and must stay `contents: read`; folding proposing into it would leak `contents: write` into a lane a comment event fires — precisely the widening ADR-016's "no `contents: write`" note exists to prevent. |
| Let the agent merge its own PR when gates pass | The verifier, not the agent, holds the merge (agent-in-ci.md rule 2 / delegation policy). Gates being green does not make the change *wanted*. |
| No lane — implement tasks only in interactive sessions | The status quo, and still the default for most work. The lane exists for scoped, well-specified tasks where the review-by-PR shape is sufficient oversight and a session is not otherwise open. |
