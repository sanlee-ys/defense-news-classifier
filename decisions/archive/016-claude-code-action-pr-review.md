# ADR-016: Agentic PR review as an advisory lane, not a gate

**Status:** Accepted; amended once — the automatic `pull_request: [opened]` pass dropped,
leaving the lane on-demand via `@claude` only (2026-07-26, *Amendment 1*)
**Date:** 2026-07-24
**Deciders:** San Lee

---

## Context

This repo already runs two CI lanes, both **deterministic gates**: `tests.yml` (lint, types,
contract/metrics artifact freshness, ADR lint, coverage floor) and `evals.yml` (an offline
capability gate on every PR, plus a paid live gate on dispatch/schedule per
[ADR-007](../007-evals-as-ci-gate.md)). Between them they answer "did this change break something
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
| Trigger | ~~`pull_request: [opened]` +~~ `issue_comment: [created]` | *(Amended 2026-07-26 — the automatic pass is gone; see Amendment 1.)* `synchronize` re-reviews on every push: a charge per push and a stream of near-duplicate comments on unfinished work. One automatic pass, then `@claude` on demand — the comment trigger is what makes that phrase fire at all. |
| Comment-trigger abuse | `author_association == 'OWNER'` | `issue_comment` runs in the base repo **with secrets** even for outside commenters — unlike fork `pull_request`, GitHub does not withhold them. Without this guard any stranger could spend the repo's API key by typing `@claude`. |
| Fork PRs | Skipped via `head.repo.full_name == github.repository` | GitHub withholds secrets from fork runs, so the job would fail on a missing key — a red X a contributor cannot fix and did not cause. |
| `pull_request_target` | **Not used** | Runs untrusted fork code in the base repo's context *with* secrets. Same reasoning already recorded in `evals.yml`'s header. |
| Model | `claude-sonnet-5`, pinned | [SYS-002](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-002-model-tier-standard.md): exact IDs, no date suffixes. Review is not a task an eval has shown needs the escalation tier. |
| Cost bound | `--max-turns 20` | Caps the agentic loop so a pathological diff cannot run an unbounded bill. Measured here: ~$0.14 on small doc-only diffs; kb-agent's larger prompt runs ~$0.37. |
| Tool grant | `--allowedTools` naming `Read,Grep,Glob` + the comment tools | Required, and it fails **silently** without them — see Consequences. |

The prompt is aimed at this repo's actual failure modes rather than generic code review: metric
drift without an artifact regen, hand-typed eval numbers, unpinned model IDs, ADRs missing
downstream surfaces, non-public-domain text ([ADR-015](../015-public-domain-data-sourcing.md)).

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
- **Dependabot PRs are not reviewed. ~~And the run still says "success".~~** The action refuses
  bot-authored PRs by default — *"Workflow initiated by non-human actor: dependabot (type: Bot).
  Add bot to allowed_bots list or use `*` to allow all bots."* **Accepted, not fixed:** a
  dependency bump is a lockfile and version pins, `tests.yml` and `evals.yml` are the real gate on
  it, and reviewing every bump would cost $0.14–0.41 each for close to no signal. Recorded because
  the alternative is a reader assuming every PR gets reviewed when a recurring class of them never
  does — the lane's coverage is smaller than its presence suggests. An `allowed_bots` input exists
  if that judgement ever changes.

  **Correction, 2026-07-25 (same-day).** The strikethrough above was wrong, and the paragraph that
  followed it — claiming this incidentally validated the advisory design — was wrong for the same
  reason. Both said `continue-on-error: true` meant "the job reports success and the PR stays
  green." It does not. `continue-on-error` was on the **job**, which greens the *workflow run*; the
  *check run* — the thing the PR displays and `gh pr checks` reads — still concluded `failure`.
  Measured on this repo's PR #123, run `30141009937`:

  | Surface | Conclusion |
  |---|---|
  | Workflow run | `success` |
  | Check run `review` | **`failure`** |

  So rather than proving the advisory design worked, this was the first case of it **not** working:
  every Dependabot PR wore a red X, which is the precise habit-forming failure the design exists to
  prevent. Found by the weekly repo sweep hours after this note was merged.

  **Fixed here, two changes.** `continue-on-error` moved to the action step (job-level kept as a
  backstop for failures with no step to attach to); and bot-authored PRs are now skipped at the
  `if`, so the accepted "not reviewed" outcome is a clean skip rather than a runner that boots,
  authenticates, and fails. The `@claude` owner-comment path is deliberately left ungated — asking
  for a review on a bump is a human decision and still works.

  **How this got written wrong:** the claim was checked against `gh run view`, which reports the
  run conclusion, and never against `gh pr checks`, which reports the check run. One command
  agreed with the belief and was treated as confirmation. `SYS-021` Amendment 1 generalises it —
  including that the run-level green made the defect invisible to `gh run list --branch main`, the
  surface a session pre-flight reads.
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
| [ADR-007](../007-evals-as-ci-gate.md) | Unchanged. That ADR governs the *gates*; this one adds a lane that deliberately is not one. |
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

---

## Amendment 1 — 2026-07-26: the automatic pass, dropped once it was worth paying for

This ADR's *Consequences* bounded the cost at "single-digit dollars a month" and its
*Alternatives* rejected `synchronize` for "charges per push." Both were reasoning about the
**wrong axis**. The lane never scaled with pushes, exactly as designed. It scaled with
**PRs**, and this repo's PR volume across the v3.1.0 ladder work was not the volume this
bullet was sized against.

**The automatic `pull_request: [opened]` trigger is removed.** The lane now fires only when
the owner comments `@claude` on a PR. Everything else is untouched: advisory status, the
`--allowedTools` grant, `--max-turns 20`, the pinned model, the prompt, `use_sticky_comment`.

**Why this is not a reversal of the ADR.** The decision this record settled was *what
authority the reviewer gets* — advisory, comments only, never a gate. That is unchanged. The
trigger was always a cost knob, and this ADR said so in the same breath it set it: one
automatic pass was itself the compromise that replaced `synchronize`. This turns the knob one
notch further along the axis it was already on.

**What actually changed is that the lane started working.** At adoption it was cheap partly
because it was shallow — the first live run spent $0.14 and posted nothing, because
`--allowedTools` was missing and every attempt to comment became a permission denial. Each
fix since (the grant, `Read`/`Grep`/`Glob`, the prompt scoping) made the review both more
useful and more expensive per run. **A recurring charge is only worth questioning once it
buys something**, so the bill arriving is evidence the fixes landed, not evidence they were a
mistake.

**The trade, stated honestly.** The automatic pass is the one that catches what you did not
think to ask about — that is its whole value, and it is what is being given up. On-demand
review has a failure mode the automatic pass does not: **you have to remember**, and the PRs
you forget to ask about are correlated with the ones you are least likely to scrutinise
yourself. This is accepted, not solved. The deterministic gates (`tests.yml`, `evals.yml`)
are unaffected and remain the enforcing layer; the advisory lane was never what stopped a bad
merge.

**Two guards became unreachable** and their reasoning is preserved in the workflow rather than
deleted, because "we removed a security guard" and "the event it guarded no longer exists"
look identical in a diff a year later:
- the same-repo fork check (fork runs get no secrets → auth failure → an unfixable red X for
  a contributor), and
- `user.type != 'Bot'` (the action refuses bot-authored PRs and exits 1, so Dependabot bumps
  used to allocate a runner, authenticate, and fail).

Dependabot bumps still go unreviewed, which this ADR already accepted — now because nothing
fires rather than because a guard skips. An OWNER commenting `@claude` on a bump still works.

**The OWNER gate is now load-bearing rather than defence in depth.** It was one of three
guards on a mixed trigger surface; it is now the only thing between a stranger's `@claude`
comment and this repo's API key. SYS-021 req. 4 is still satisfied — and by a smaller surface,
since the fail-closed event is gone and only the fail-open one remains, guarded.

**One narrowing worth naming.** A comment-triggered run checks out the **default branch**, not
the PR merge ref, so `Read`/`Grep`/`Glob` see `main` rather than the PR's tree. The prompt
already leads with `gh pr diff`, which remains authoritative for what changed, so the review
still works — but reading a *changed* file now shows its pre-PR content. Checking out
`refs/pull/N/merge` explicitly would restore the old tree and is the documented follow-up if
review depth visibly suffers; it is not done here because that ref can be absent on closed or
long-merged PRs, and trading a silent narrowing for a loud checkout failure is a bad deal on a
change whose purpose is to stop this lane spending money unattended.

**Downstream surfaces for this amendment:**
- `.github/workflows/claude-review.yml` — the `on:` block loses `pull_request`; the job `if:`
  collapses to the single OWNER-gated comment clause, with the two removed guards recorded in
  place. The prompt, grant, ceiling, model pin and concurrency key are **unchanged**.
- The *Decision* table's **Trigger** row above — struck through and annotated rather than
  rewritten, so the compromise it records stays readable.
- The **Fork PRs** row and the `pull_request_target` row — now describe an event this lane no
  longer receives. Left standing: both are standing prohibitions, and the reasoning is what
  stops a future PR-triggered lane reintroducing them.
- `decisions/README.md` — the ADR-016 row notes the lane is on-demand.
- **Verification is unchanged and still cannot happen on this PR.** The Claude App refuses to
  run when the workflow differs from the copy on the default branch, so this change is
  verified by merging and then commenting `@claude` on a later PR — judged by **a posted
  review comment**, never by a green check. That was already this lane's only verification
  path; it is now its only trigger as well.

**Unchanged by Amendment 1:** every other choice in the Decision table, the whole of
*Consequences* except the cost bullet's premise, and the advisory-not-a-gate ruling that is
the actual subject of this record.
