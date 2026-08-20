# The Ralph outer loop

A Ralph-style loop around the classifier prompt: a fresh agent runs the frozen
`PROMPT_optimize.md` every iteration, and an outer script grades the edit on a
metric the agent cannot see. The design and its limits are in
[`decisions/archive/026-ralph-loop-honest-ruler.md`](../decisions/archive/026-ralph-loop-honest-ruler.md).

**The loop merges nothing.** Under agent-ops ADR-016 a loop does not inherit
the standing merge authorization. It commits to its own branch and stops.

## The five things to state before starting a loop

ADR-016 asks for these in one sentence each. Here they are for this loop.

| Rail | This loop |
|---|---|
| `max_iterations` | `-MaxIterations`, default 3 |
| Budget cap | `-BudgetUsd`, default 2.00, summed from each agent result; `-MaxMinutes`, default 60, as the backstop |
| Worktree | its own, created with `git worktree add` — the script refuses the main tree |
| Branch | `-Branch`, default `loop/prompt-optimize`; it refuses `main` |
| Blast radius | `blast-radius.txt`: `src/classify.py` and `loop/state/` |

## Run it

Set up an isolated worktree first. A loop that shares a working tree with a
live session stages that session's uncommitted work.

```powershell
git -C C:\Users\sanle\code\defense-news-classifier worktree add ..\dnc-loop -b loop/prompt-optimize
cd ..\dnc-loop
```

Then run the loop. Start with the smoke test, which spends no API budget on
scoring:

```powershell
pwsh loop/loop.ps1 -MaxIterations 2 -DryRunMetrics
```

A real run scores against the live eval set and costs roughly 354 classify
calls per iteration:

```powershell
pwsh loop/loop.ps1 -MaxIterations 5 -BudgetUsd 5.00 -MaxMinutes 90
```

Read the result:

```powershell
git -C ..\dnc-loop log --oneline loop/prompt-optimize
Get-Content evals/loop/run_<UTC>.jsonl | ConvertFrom-Json | Format-Table iteration, verdict
```

## Grade one prompt by hand

The ruler runs on its own. The ledger path must be outside the worktree,
because it carries the hidden scores.

```powershell
$env:LOOP_LEDGER = "$env:TEMP\dnc-loop\manual.jsonl"
uv run python scripts/loop_metrics.py --mode baseline --dry-run
uv run python scripts/loop_metrics.py --mode check --dry-run
```

Exit codes: `0` accepted, `3` the hidden validation split regressed, `4` the
frozen region rubric changed, `1` an error.

## Verify the rails without spending budget

A stub agent stands in for `claude` so the two halting rails can be exercised
deterministically. Both runs cost nothing.

```powershell
# Rail 4: the stub damages the region rubric the same way every iteration,
# so the loop halts on the third identical failure, short of the cap.
pwsh loop/loop.ps1 -MaxIterations 5 -DryRunMetrics -NoPush `
    -AgentCommand loop/fixtures/stuck-agent.ps1
```

## What is in `loop/state/`

Everything here is agent-visible on purpose. Nothing here carries a B or C
score. The directory is untracked scratch for one run, like the run logs.

| File | Written by | Purpose |
|---|---|---|
| `report_A.md` | the ruler | Split-A failures. The only report the prompt tells the agent to read. |
| `verdict.md` | the ruler | Accepted or rejected, and which gate fired. Never a number. |
| `log.md` | the agent | One entry per iteration. The loop's only memory across restarts. |
| `status.md` | the agent | Carries `LOOP-COMPLETE:` when the agent decides it is done. |
| `stuck.json` | the outer script | Written when three consecutive iterations fail identically. The run halts. |
| `ledger_at_halt.jsonl` | the outer script | The hidden-score ledger, copied out when a run halts before its last iteration. |

An accepted iteration is committed. A rejected one is not: its edit is
reverted and its record stays in the ledger.

## `loop.sh`

Not written. This machine is Windows and a second copy of the rails is a second
place for them to drift. Port it when a POSIX box needs to run the loop, and
port the rails, not only the invocation.
