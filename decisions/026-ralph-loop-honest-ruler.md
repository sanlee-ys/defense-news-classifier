# ADR-026: Ralph with an honest ruler — the outer loop grades on a metric it cannot see

**Status:** Accepted — 2026-08-11

**Relates to:** [ADR-005](005-agentic-prompt-optimization-loop.md) (the rung-1
loop and its A/B/C split) · [ADR-018](018-agent-driven-ml-loop.md) (rung 2, and
the measured Goodhart catch this design is built on) ·
[ADR-024](024-global-boundary-clause-adopted.md) (the adopted region clause the
loop must not touch) · agent-ops
[ADR-016](https://github.com/sanlee-ys/agent-ops/blob/main/decisions/ADR-016-loops-do-not-inherit-merge-authorization.md)
(a loop does not inherit the standing merge authorization)

## Context

The Ralph pattern is a small idea: put an agent in a loop, feed it the same
prompt every iteration, and let the repository carry the state. It works
because a fresh agent has no accumulated confusion. It fails in a specific
way, and the failure has a name.

**A loop optimizes whatever it can measure.** Ralph's usual signal is the test
suite, and the test suite is fully visible to the agent that is being graded by
it. An agent that can read its own scoreboard can edit the scoreboard. Even
when it does not do that, it hill-climbs on the exact rows it was shown, which
is Goodhart's law arriving on schedule: the measure stops being a measure once
it becomes the target.

**This repository has already caught that happening, with numbers.** The rung-2
ML loop's first live run improved the split the agent could see and degraded
the split it could not: B rose to 0.699 (+6.0) while held-out C fell to 0.545
(−8.6) ([ADR-018](018-agent-driven-ml-loop.md)). Nothing in the agent's
behaviour was dishonest. The design caught it, and only because the deciding
number was not the number the agent was reading.

So the question this decision answers is not "should we run a Ralph loop". It
is: **what does a Ralph loop grade on, given that the thing being graded can
read the grade?**

## Decision

**Build the Ralph outer loop, and split the ruler three ways, with the
acceptance gate on the split the agent never sees.**

The mapping onto the repository's existing A/B/C split
([ADR-005](005-agentic-prompt-optimization-loop.md) §5.2) is exact, because it
is the same split, built by the same `make_split(seed=...)`:

| Split | Role in the outer loop | The agent sees it |
|---|---|---|
| **A** — optimize | The failures the agent reads and edits the prompt against. Written to `loop/state/report_A.md`. | Yes, and only this |
| **B** — validation | **The acceptance gate.** An iteration is committed only if B does not regress against the best accepted B. | No |
| **C** — test | The honest final number. Recorded in the run log, used for no decision at all. | No |

Three mechanisms carry it:

1. **`loop/PROMPT_optimize.md`** — the frozen iteration spec, re-fed verbatim.
   One change per iteration, current state read from `loop/state/`, no
   placeholder implementations, and a `LOOP-COMPLETE:` sigil for the stop.
2. **`scripts/loop_metrics.py`** — the ruler. It reuses `src/optimize.py`'s
   `score_split`, `region_guardrail`, and `region_rubric_violations` rather
   than reimplementing any metric, and it exits 0 to accept, 3 on a B
   regression, 4 on a damaged region rubric.
3. **`loop/loop.ps1`** — the outer script, which owns every cap, every git
   operation, and every decision. The agent owns none of them.

**Two gates, not one.** A B regression rejects the iteration. So does any
change to the frozen `Region rules:` block, checked byte for byte before a
single score is computed. The region clause was adopted on measured evidence at
p=0.0002 ([ADR-024](024-global-boundary-clause-adopted.md)); a loop optimizing
`category` has no standing to rewrite it, and the cheap structural check fires
before the expensive scoring pass.

**The loop merges nothing.** Under agent-ops ADR-016 the standing merge
authorization stops at the loop boundary. This loop pushes commits to its own
branch, opens no pull request, and merges none. All seven ADR-016 rails live in
`loop/loop.ps1`, at the call site, not in the prompt.

## Why the deciding metric is hidden rather than merely held out

The rung-1 loop already holds B out of the *feedback text*. That is enough when
the proposer is a function that receives a string, because there is no code
path by which B could reach it.

The outer loop's proposer is a general coding agent with a filesystem. Holding
B out of the prompt would not hold it out of the agent. So the hiding is
physical: **the ledger carrying B and C is written outside the git worktree**,
to a path the outer script chooses and passes in. During the run those numbers
are not files in the tree the agent is working in. The script copies the
finished ledger into `evals/loop/` after the last iteration, so the evidence is
published and the run is still auditable.

The verdict the agent *does* see is deliberately number-free: "the hidden
validation split regressed". A rejection that quotes the hidden score turns the
hidden score into a gradient, and one bit per iteration is a gradient the loop
would climb.

## What this does not guarantee

Stating this plainly is the point of the artifact, so it is stated here rather
than in a footnote.

`src/optimize.py`'s guard is **structural**: there is no line of code through
which B could reach the proposer. This loop's guard is **not**. A general agent
with shell access could read the ledger if it went looking, and the frozen
prompt asking it not to is a request, not a control — the same argument
ADR-016 makes about putting a cap in a prompt.

What the design actually buys is that the hidden metric is not *convenient*: it
is not in the tree, not in the report, not in the verdict, and not in any file
the prompt names. That is a real reduction in the failure mode and it is not
the same as a proof. The honest description is a **deterrent plus an audit
trail**, and the audit trail is the part that holds: every rejected iteration
is committed with its gate recorded, so an agent that gamed the gate leaves the
evidence in the run log.

The mechanical guarantees that *do* hold are the ones the outer script enforces
without asking the agent: the caps, the stuck halt, the blast radius, and the
fact that the agent runs no git command at all.

## Alternatives considered

**Grade on the visible A metric and trust the agent.** Rejected — this is the
configuration whose failure ADR-018 already measured in this repository.

**Show the agent B so it can steer better.** Rejected. It optimizes faster and
the number stops meaning anything. A validation split that the optimizer reads
is a second training split with a more reassuring name.

**Use C as the gate instead of B.** Rejected, and it is the more tempting
mistake. C is the real gold set, so gating on it would produce the most
convincing possible number and destroy it in the same motion: the moment C
decides anything, it is no longer held out, and the project loses the honest
generalization figure that every outward claim rests on.

**Let the loop merge its own green pull requests.** Rejected by agent-ops
ADR-016, and the reason is specific rather than general caution: iteration 4
merges the defect iteration 3 introduced, iteration 5 reads the merged defect
as the base state, and each merge deletes the evidence that the ground moved.

**Give the loop a tolerance on B, so a small regression still passes.**
Rejected. Each iteration would be permitted to give back a little, and the sum
of "a little" across a run is exactly the regression the gate exists to catch.
`B_TOLERANCE` is 0.0 and a test pins it there.

## Consequences

- The loop's default output is a branch carrying one commit per **accepted**
  iteration, plus a run log. Review cost moves to a human. Under ADR-016 that
  is the intended trade.
- A rejected iteration leaves no commit. Its edit is reverted and its full
  record — scores, gate, timestamp — is in the ledger. `loop/state/verdict.md`
  survives the revert, so the next iteration reads why the last one failed
  without inheriting the edit that failed. The "no ratchet" limitation the
  rung-1 spec records in §10 therefore does not repeat here.
- `loop/state/` is untracked scratch, matching this repository's existing
  policy for run logs. It is also what lets a second run start: a tracked
  state directory left the tree dirty and the next run refused to start.
- The loop cannot improve `region`, by construction. That is a real capability
  cost, accepted so an adopted, measured clause cannot be silently rewritten by
  an optimizer aimed at a different axis.
- `evals/loop/run_<UTC>.jsonl` is a new published artifact. It carries the full
  A/B/C history, so the A-versus-C gap is measurable per run — the same
  overfitting measurement rung 1 publishes.
- **Unmeasured, deliberately.** This ADR ships the harness and a smoke test. It
  makes no claim that the loop improves the classifier prompt. The smoke test
  exercised the mechanics with the zero-API mock backend; no live optimization
  run has been made, and the prompt in `src/classify.py` is unchanged.

## Downstream surfaces

- `scripts/loop_metrics.py` — the ruler; reuses `src/optimize.py`'s metric and
  region functions. A change to `make_split`, `score_split`,
  `region_guardrail`, or `region_rubric_violations` changes this loop's grades.
- `loop/PROMPT_optimize.md` — frozen. Editing it changes what every future
  iteration is told, so it is versioned with the ADR, not tuned mid-run.
- `loop/loop.ps1` and `loop/blast-radius.txt` — the rails. The blast radius must
  be re-declared if the loop is ever pointed at a different file.
- `tests/test_loop_metrics.py` — pins the exit-code contract, the ratchet, the
  zero tolerance, and that the agent-visible report carries no hidden score.
- `loop/fixtures/stuck-agent.ps1` — the deterministic stub that makes the
  stuck-detection rail reproducible without spending budget. It is substituted
  through `-AgentCommand`, which exists for that purpose and no other.
- `.gitignore` — `loop/state/` and `evals/loop/run_*.jsonl`.
- `evals/loop/` — new run-log directory, sibling to `evals/optimize/`.
- `docs/specs/prompt-optimization-loop.md` — unchanged. This is an outer loop
  around that work, not a revision of it; the A/B/C contract is shared, so a
  change to the split ratio or seed there moves this loop's ruler too.
- `src/classify.py` — the only source file the loop may edit. Not edited by
  this decision.
- agent-ops `conventions/loop-safety.md` — the seven rails. This is the first
  harness in the fleet that implements them, which is the gap ADR-016's
  "Unmeasured, deliberately" note names.
