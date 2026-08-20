# Agent practice: what an agent may do in this repository

**Status:** Current as of 2026-08-20. This supersedes ADR-005, ADR-016, ADR-018, ADR-025 and
ADR-026 as the statement of the rule. Those five keep their full text under
[`archive/`](archive/) and remain the record of how the rule was arrived at.

**Why one document.** Five ADRs written between 2026-06-27 and 2026-08-11 each settled one
question about agent authority, at five different levels of maturity. Reading all five was
the only way to know the current practice, and two of them stated the same rule in different
words. The rule below is what they add up to. The history section says what changed and why,
because the changes are the interesting part.

---

## The rule

**1. An agent proposes. A human and the deterministic gates dispose.**
No agent merges anything. The review lane comments and cannot fail the build. The task lane
opens a draft pull request and cannot push `main`. The optimization loops push to their own
branch and open nothing. Where the authority is a token scope rather than a convention, say
so at the call site: the task lane holds `contents: write` and it is **branch protection on
`main` that makes it proposal-only**, so loosening that protection re-opens this decision.

**2. Agent green is not build green.**
An agentic step exits 0 whether the work landed, was denied, or was never attempted. The
review lane measured exactly that. Never treat a green agent job as a passing gate. The thing
to trust is the pull request and its own checks.

**3. The deciding metric is never the metric the agent reads.**
Every loop in this repository grades on a split the proposer cannot see, built by one shared
`make_split(seed=...)` in `src/optimize.py`. A is what the agent reads. B decides. C is the
honest number and decides nothing. Holding B out is shared code, not a shared intention:
rung 2 imports `check_done_signal` and `select_best_iteration` from rung 1 unchanged.

**4. Caps, guards and frozen surfaces live at the call site, never in the prompt.**
A cap in a prompt is a request. The outer loop's seven rails are in `loop/loop.ps1`. The task
lane fetches the guard hooks and **fails the job if the fetch fails**, because running
unguarded is a posture change nobody approved. Anything frozen is checked mechanically before
any spend: the region rubric byte for byte, `validate_experiment` before a fit, the critic's
fail-closed challenge filter.

**5. Agent lanes are owner-triggered and idle-free.**
No schedule, no automatic pass on `opened`, no comment phrase open to strangers. The review
lane learned this by amendment after paying for near-duplicate reviews on unfinished work.
The task lane adopted it on day one.

**6. A negative result is a result. An agent's output is judged, not adopted.**
Three of the loops produced changes that were measured and rejected. That is the lane working.

---

## What a hidden metric does not buy

Rule 3 has a limit, and it is worth stating where the rule is stated rather than in a
footnote, because it has now cost a live run.

**The guard is structural only when the proposer is a function.** In `src/optimize.py` there
is no line of code by which B could reach the proposer. The outer loop's proposer is a general
coding agent with a filesystem, so its guard is a **deterrent plus an audit trail**: the
hidden numbers are written outside the worktree, are absent from the report and the verdict,
and are named in no file the prompt mentions. That is a real reduction in the failure mode. It
is not a proof.

**A hidden gate cannot catch an error that both splits share.** A and B are a 70/30 shuffle of
the same pool, so an annotation defect in that pool sits in both. On 2026-08-20 the first live
outer-loop run gained +0.132 macro-F1 on A and +0.131 on hidden B while the real gold set C
did not move at all, because the gain came from 42 mislabeled rows that C does not contain.
Every rail held and the result was still wrong.

**So read a flat C as a signal, not as a disappointment.** A large A and B gain beside a flat
C does not mean "the gain did not generalize". It means "the gain came from rows C does not
have", and the next question is whether the ruler is broken. See the
[ADR-026 amendment](archive/026-ralph-loop-honest-ruler.md) and
[`docs/notes/project-notes.md`](../docs/notes/project-notes.md).

---

## How the rule got here

The progression is the argument for keeping this document current rather than immutable. What
changed each time was the **capability of the proposer**, and the guard had to change with it.

| Date | Record | What it added |
|---|---|---|
| 2026-06-27 | [ADR-005](archive/005-agentic-prompt-optimization-loop.md) | The 3-way split. The proposer is a function receiving a string, so holding B out of the feedback text is a structural guarantee. |
| 2026-07-24 | [ADR-016](archive/016-claude-code-action-pr-review.md) | Advisory, never a gate: a non-deterministic reviewer that turns CI red trains the habit of ignoring red. Amended 2026-07-26 to drop the automatic pass, on cost. |
| 2026-07-25 | [ADR-018](archive/018-agent-driven-ml-loop.md) | The split becomes shared code rather than a shared intention. Adds deterministic validation before any spend. Produced this repo's first measured Goodhart catch: B up 6.0 while held-out C fell 8.6. |
| 2026-08-11 | [ADR-025](archive/025-agent-task-lane.md) | An agent may propose code, not only comment. Authority is delegated to branch protection and stated where it bites. |
| 2026-08-11 | [ADR-026](archive/026-ralph-loop-honest-ruler.md) | The proposer is now a general agent with a filesystem, so hiding becomes physical rather than structural, and the ADR says plainly that this is a deterrent, not a proof. |
| 2026-08-20 | [ADR-026 amendment](archive/026-ralph-loop-honest-ruler.md) | A hidden gate cannot catch an error both splits share. A flat C beside a large A and B gain is a defect signature. |

## Open, and deliberately not decided

**Should C get a non-blocking alarm?** Gating on C is rejected and stays rejected: the moment C
decides anything it stops being held out, and the project loses the honest generalization
figure every outward claim rests on. A warning that changes no gate would have flagged the
2026-08-20 run at iteration 2. Proposed in the ADR-026 amendment, not built.

## Downstream surfaces

- `src/optimize.py` — `make_split`, `score_split`, `check_done_signal`, `select_best_iteration`. A change here moves every loop's ruler at once.
- `loop/loop.ps1`, `loop/blast-radius.txt`, `loop/PROMPT_optimize.md` — the outer loop's rails and frozen spec.
- `scripts/loop_metrics.py` — the ruler's exit-code contract.
- `.github/workflows/claude-review.yml` — the review lane.
- `.github/workflows/agent-task.yml` — the task lane, and the `contents: write` coupling to branch protection.
- `src/ml_loop.py` — rung 2, which imports rung 1's guard.
- `tests/test_loop_metrics.py` — pins the exit codes, the ratchet, the zero tolerance, and that the agent-visible report carries no hidden score.
