# ADR-027: A mechanical morning review scores a loop run before a human reads it

**Status:** Accepted
**Date:** 2026-08-22
**Deciders:** San Lee

**Related:** [ADR-026](archive/026-ralph-loop-honest-ruler.md) (the outer loop and its
hidden A/B/C split, which this scorer reads and does not change) · agent-ops
[ADR-016](https://github.com/sanlee-ys/agent-ops/blob/main/decisions/ADR-016-loops-do-not-inherit-merge-authorization.md)
(a loop does not inherit the standing merge authorization, so its output always waits
for a human)

---

## Context

The Ralph outer loop (`loop/loop.ps1`, ADR-026) runs unattended and merges nothing: its
output is a branch of commits plus a run log for a human to review. The loop's first
live run happened 2026-08-19/20 (`evals/loop/run_20260820T011747Z.jsonl`, on the
never-merged `loop/prompt-optimize` branch) and ADR-026's amendment already recorded
what a human found: every mechanical rail held, B rose 0.748 to 0.879, C held flat at
0.936 -- and the result was still wrong, because the gain came from an annotation
defect shared by A and B. **That review took a person reading five iterations' diffs
and a ledger by hand.** Nothing in the loop itself would have told the next unattended
run "the numbers look fine, read it anyway" versus "something in the run itself is
already broken."

Field reports on unattended agent loops put first-run success at 30-40%. A run that
fails does not usually announce it: the agent's own `loop/state/log.md` reads as
confident in every one of these runs, accepted or rejected. Reading that summary first
anchors the reviewer before they have seen a single number.

## Decision

**A mechanical scorer runs before any human reads the agent's own summary, and it
answers exactly one question: does this run's *mechanical* evidence support treating it
as a clean win, a partial one, a stall, or untrustworthy.** It is not a semantic review
-- it cannot tell a genuine prompt improvement from one that encodes a labeling defect,
which is exactly the failure ADR-026's amendment found by hand. It is the gate that runs
first, so a human's attention goes to a smaller, correctly-triaged set of runs.

`scripts/morning_review.py` reads a run's JSONL log
(`evals/loop/run_<UTC>.jsonl`) plus the loop worktree's git state and returns one of
four verdicts, in this priority order, so a run can only ever satisfy one class:

1. **DRIFTED** -- the log is structurally malformed (a missing baseline, a
   non-contiguous iteration sequence, an unparseable line); or the worktree touched a
   file outside `loop/blast-radius.txt` (re-checked independently of the loop's own
   rail-8 revert, not trusted from it); or a claimed stopping signal does not match the
   ledger's own evidence (`loop/state/stuck.json` claiming three identical failures the
   log's tail does not show, or both a stuck halt and a `LOOP-COMPLETE:` sigil claimed
   at once).
2. **STUCK** -- no accepted iteration ever beat the baseline B score (every iteration
   rejected, or none moved the bar).
3. **SHIPPED** -- B improved over baseline, the run ended on a real stopping signal
   (the agent's own `LOOP-COMPLETE:`, or the loop's stuck-halt firing *after* real
   improvement already landed), and C did not fall more than the tolerance below.
4. **PARTIAL** -- B improved, but either the run only ended because it hit
   `-MaxIterations`/`-BudgetUsd`/`-MaxMinutes` rather than a real signal, or C fell past
   tolerance while B rose (the Goodhart pattern ADR-026's amendment already named:
   `A and B moved 0.13 while C moved 0.000`).

Exit code encodes the verdict for a wrapper to gate on: 0 SHIPPED, 1 PARTIAL, 2 STUCK, 3
DRIFTED.

### Design call: the C tolerance is the repo's own noise floor, not a new number

The Goodhart check (SHIPPED/PARTIAL step 4) needs a line between "C moved" and "C
wobbled." Rather than invent one, `DEFAULT_C_TOLERANCE = 0.004` reuses the figure this
repo already measured for exactly this question: `evals/stability.txt`'s 3-run
stability pass puts `category_accuracy`'s run-to-run standard deviation at 0.0019 (0.19
points), and the repo already treats 2x that (~0.4 points, 0.004 on the 0-1 scale) as
the line between a real move and noise (CLAUDE.md's known-issue note cites the same
figure). A C drop smaller than that is not evidence the loop touched a split it cannot
see; a drop past it is. The flag is `--c-tolerance`, overridable if a future run's own
noise floor is measured differently.

### Design call: "threshold or plateau" maps onto two concrete files, not a new signal

The rubric names two ways a run can end cleanly. This loop already writes exactly one
file for each, so the scorer reads those rather than inventing a third mechanism:
`loop/state/status.md` carrying the `LOOP-COMPLETE:` sigil is "threshold" (the agent
declared itself done); `loop/state/stuck.json` (written only when three consecutive
iterations fail identically) is "plateau." Neither file is written by this scorer --
both are read as evidence to cross-check against the ledger, never trusted alone, which
is why an unsubstantiated claim routes to DRIFTED rather than SHIPPED. Every other stop
condition (`-MaxIterations`, `-BudgetUsd`, `-MaxMinutes`) collapses to
`budget_or_iteration_cap`: the scorer cannot and does not try to tell those three apart
from the ledger alone, because the rubric treats them identically (PARTIAL, not
SHIPPED) -- a run that stopped because its resources ran out earned nothing by
stopping there.

## What this does not guarantee

Stating this plainly matches ADR-026's own honesty about its design, so it is stated
here rather than left implicit.

**This is a mechanical check, not a content review.** The scorer trusts the ledger it
is given. It has no code path to detect that a prompt edit encodes a wrong labeling
convention -- exactly what ADR-026's amendment found in the one live run this repo has
produced. A run scoring SHIPPED means the mechanical rails held and the numbers moved
the right way; it does not mean the prompt edit is correct. Re-running this scorer
against that run's own log (`evals/loop/run_20260820T011747Z.jsonl`, kept in the loop
worktree, gitignored per policy) confirms the mechanical read matches: PARTIAL, because
the run ended on `-MaxIterations` rather than a real stopping signal -- not because of
the annotation defect the human review found. **The morning review and a human content
read are both required; neither substitutes for the other.**

**The scope check re-measures independently, but from the same git history the loop
wrote.** It does not defend against a compromised `loop.ps1` itself (a different threat
than ADR-026 addresses) -- it defends against trusting the loop's self-report of "rail 8
held" instead of checking the committed diff directly.

**THE LOOP HAS RUN LIVE EXACTLY ONCE, on 2026-08-19/20, and that run was never
merged** -- ADR-026's amendment ends "`loop/prompt-optimize` is not merged and will not
be." This ADR adds the scorer; it does not run the loop again, and no live run's
prompt has shipped. A future live run is a fresh measurement under corrected labels
(the 42-row defect ADR-026 named), and this scorer is what triages it first.

## Alternatives considered

**Score inside `loop.ps1` itself, at the end of the run.** Rejected. The outer script
already owns every mechanical decision the loop makes *during* the run (ADR-016's seven
rails); folding a morning-review verdict into the same process blurs "what the loop
decided" with "what a human should look at first," and a scorer that runs after the
process exits can be re-run against an old log without re-running the loop.

**Gate on C directly, the way the rubric might suggest.** Rejected, for the same reason
ADR-026 rejected it for the loop's own acceptance gate: the moment C decides anything it
stops being held out. This scorer's Goodhart check is diagnostic, not a gate -- it
changes the verdict a human sees, never a commit the loop already made.

**A single tolerance for every metric the ledger carries.** Considered and dropped in
favor of scoping the tolerance to C's macro-F1 specifically, because that is the one
number the stability report actually measured; extending it to `region_guardrail` or
`domain_macro_f1` without their own measured noise floors would be inventing precision
the repo does not have.

## Consequences

- A completed run gets a verdict and an exit code before anyone reads
  `loop/state/log.md`. A wrapper can gate on the exit code (0-2 review, 3 investigate)
  without parsing prose.
- The four verdicts are mutually exclusive by construction (checked in a fixed priority
  order, one return per branch) -- this is asserted in
  `tests/test_morning_review.py`, not merely intended.
- The scorer adds no new runtime behavior to the loop and does not read or write
  `LOOP_LEDGER`, `loop/state/report_A.md`, or `loop/state/verdict.md`. It is a read-only
  consumer of files the loop already produces.
- `--worktree` defaults to walking up from the run log's own path
  (`<worktree>/evals/loop/run_*.jsonl`); pointed at a plain JSONL log with no worktree,
  the scorer skips the scope check and the stop-signal read (reported as "not checked,"
  never as "clean") rather than guessing.

## Downstream surfaces

- `evals/loop/run_<UTC>.jsonl` -- the input format. A change to
  `scripts/loop_metrics.py`'s record shape (new keys, renamed splits) changes what this
  scorer parses.
- `loop/state/status.md`, `loop/state/stuck.json` -- read as the done-signal evidence.
  A change to `loop.ps1`'s stuck-detection shape (ADR-026's rail 4) or the `LOOP-COMPLETE:`
  sigil changes what `read_stop_signal` looks for.
- `loop/blast-radius.txt` -- read for the scope check, parsed the same way
  `loop.ps1`'s `Test-InBlastRadius` does. A change to that parsing (e.g. glob support)
  must move both places or they will disagree about what is in bounds.
- `evals/stability.txt` -- the source of `DEFAULT_C_TOLERANCE`. A re-measured noise
  floor should update the constant and this ADR's cited figure together.
- `tests/test_morning_review.py` -- pins the exit-code contract, the mutual-exclusivity
  ordering, and the four verdicts plus a malformed-log case, all against synthetic
  ledgers and a throwaway git fixture (no API spend, no dependency on a real loop run
  existing on disk).
