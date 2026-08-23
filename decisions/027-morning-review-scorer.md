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
(`evals/loop/run_<UTC>.jsonl`) plus the loop worktree's git state and evaluates four
checks in this strict priority order, each returning immediately -- a precedence
partition, not a claim that the underlying conditions never overlap (a scope violation
on a run that also never improved B satisfies both DRIFTED's and STUCK's condition; the
first check to match is simply the one that returns):

1. **DRIFTED** -- the log is structurally malformed (a missing or misplaced baseline, a
   non-contiguous iteration sequence, an unrecognized `kind` or `verdict`, a `macro_f1`
   outside `[0, 1]`, an unparseable line); or the worktree touched a file outside the
   blast radius **as declared at the run's own base commit** (never at HEAD -- reading
   the declaration from HEAD would let a run that edits
   `loop/blast-radius.txt` to cover its own tracks certify itself); or a claimed
   stopping signal does not match the ledger's own evidence (`loop/state/stuck.json`
   claiming three identical failures the log's tail does not show, or both a stuck halt
   and a `LOOP-COMPLETE:` sigil claimed at once).
2. **STUCK** -- no accepted iteration ever improved B past the measured noise floor
   (every iteration rejected, or the only "gain" is smaller than run-to-run noise).
3. **SHIPPED** -- B improved past the noise floor, the run ended on a real stopping
   signal (the agent's own `LOOP-COMPLETE:`, or the loop's stuck-halt firing *after*
   real improvement already landed), C did not fall past tolerance, **and C did not sit
   flat inside the noise floor despite the B gain** -- the exact pattern ADR-026's
   amendment found by hand (B +0.131, C +0.000) and named a defect signature, not a
   success.
4. **PARTIAL** -- B improved, but any of: the run only ended because it hit
   `-MaxIterations`/`-BudgetUsd`/`-MaxMinutes` rather than a real signal; C fell past
   tolerance; or C stayed flat while B moved (unconfirmed, not disqualifying -- a
   diagnostic flag, never a gate, matching ADR-026's own proposed "alarm, not a vote").

Exit code encodes the verdict for a wrapper to gate on: 0 SHIPPED, 1 PARTIAL, 2 STUCK, 3
DRIFTED.

### Design call: the noise floor is the repo's own measured figure, applied to both sides

A macro-F1 delta needs a line between "moved" and "wobbled" for two different
questions: is a B "improvement" real, and is a C move (in either direction, including
none) distinguishable from noise? Rather than invent a threshold, `NOISE_FLOOR = 0.0024`
reuses the figure `evals/stability.txt` already measured for this exact metric family:
a 3-run stability pass puts `category_macro_f1`'s run-to-run standard deviation at
0.0012, and 2x that is the line the report itself draws between a real move and
sampling noise. (An earlier draft of this constant cited `category_accuracy`'s
std -- 0.0019, 2x ≈ 0.0038 -- a different metric on the same report; caught in review
and corrected, since C and B are scored as macro-F1, not accuracy.) `DEFAULT_C_TOLERANCE`
is the same constant: a C drop smaller than the noise floor is not evidence of anything,
a drop past it is. Both are overridable via `--c-tolerance` if a future run's own noise
floor is measured differently.

### Design call: a flat C is an alarm, not a fall -- reusing ADR-026's own reading

The tolerance above only catches C *falling*. It was pointed out in review that this
missed ADR-026's actual, sharper finding: "a large A/B gain with a flat C is a defect
signature, not a success" -- its one live run moved B by 0.131 and C by exactly 0.000,
and a flat C reads as *healthy* under a fall-only tolerance. The fix adds a second,
independent condition: when B clears the noise floor and `|c_delta|` sits inside it
(C moved by an amount indistinguishable from nothing), that is flagged explicitly and
the run cannot read as SHIPPED -- it is PARTIAL, with the reason spelled out. This is
still a diagnostic, not a gate (ADR-026's "C should get an alarm, not a vote," restated
in the Alternatives below): it changes what a human is told, never a commit the loop
already made, and it does not fire when C **also** improves past the noise floor
alongside B -- only when C sits still while B does not.

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
- The four verdicts are always exactly one per run, by evaluation order (checked in a
  fixed priority, one return per branch) -- this is asserted in
  `tests/test_morning_review.py`, not merely intended. This is a precedence
  guarantee on the *output*, not a claim that the four checks' conditions partition the
  input space -- see the priority list above.
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
- `loop/blast-radius.txt` -- read for the scope check **at the run's base commit**,
  parsed the same way `loop.ps1`'s `Test-InBlastRadius` does. A change to that parsing
  (e.g. glob support) must move both places or they will disagree about what is in
  bounds.
- `evals/stability.txt` -- the source of `NOISE_FLOOR` / `DEFAULT_C_TOLERANCE`
  (`category_macro_f1`'s std, specifically -- not `category_accuracy`'s, a different row
  in the same report). A re-measured noise floor should update the constant and this
  ADR's cited figure together.
- `tests/test_morning_review.py` -- pins the exit-code contract, the priority ordering,
  the flat-C alarm, the base-commit blast-radius read, the noise-floor gate on "B
  improved," and the four verdicts plus several malformed-log cases, all against
  synthetic ledgers and a throwaway git fixture (no API spend, no dependency on a real
  loop run existing on disk).
- `INFORMATIONAL_KINDS` in `scripts/morning_review.py` (2026-08-22 amendment below) --
  the set of record `kind`s the parser recognizes but never scores. Adding a third kind
  of side-channel record to the ledger means adding it here too, or it trips DRIFTED.
- the sibling `agent-ops` clone's `scripts/reconcile.py` -- the 2026-08-22 amendment's
  snapshot source. A change to that script's JSON output shape changes what the
  `"reconcile"` record's `snapshot` field carries; this repo does not parse inside it,
  so drift there does not break the scorer, only a human reading it.

## Review

A read-only cross-model review (`codex exec`) of the diff against `main`, focused on
whether SHIPPED correctly reuses ADR-026's B-gate/C-honesty semantics, whether a run can
game the verdict, and whether the four classes are mutually exclusive, found four `P1`
issues and two `P2` issues, all confirmed against this repo's own files and fixed before
merge: the flat-C alarm was missing (SHIPPED could fire on the exact ADR-026 defect
pattern); the noise-floor constant was computed from the wrong row of
`evals/stability.txt`; the blast-radius declaration was read from HEAD rather than the
run's base commit (self-authorizing); a rogue record `kind` was invisible to the
contiguity check yet visible to the B-ratchet; and the "mutually exclusive" language
overstated what a priority-ordered check guarantees. All five are reflected above and
pinned by a named test in `tests/test_morning_review.py`.

## Amendment 2026-08-22: the loop appends a mechanical reconcile record every cycle

**Context.** An agent's self-report is a claim, not a record (agent-ops
`conventions/reconcile-claims.md`). The sibling agent-ops clone carries
`scripts/reconcile.py`, a stdlib-only, read-only script. It prints a ground-truth JSON
snapshot of a repo: open pull requests, pull requests merged in a window, remote
branches from `git ls-remote`, the current branch, uncommitted paths, and the last
commit. This repo has hit the failure class that script guards against: fabricated or
orphaned work, found late. The loop runs unattended for several iterations. Nothing in
it checked its own git state against the systems of record.

**Decision.** `loop/loop.ps1` runs `reconcile.py` against the loop worktree after each
iteration, and once more at run end. Each run appends one ledger record:

- `{"kind": "reconcile", "iteration": N, "phase": "post_iteration" | "run_end",
  "timestamp": ..., "snapshot": {...}}` on success. `snapshot` is `reconcile.py`'s own
  JSON output, unchanged.
- `{"kind": "reconcile_unavailable", "iteration": N, "phase": ..., "timestamp": ...,
  "reason": "..."}` when the snapshot could not be taken.

**The reconcile record is evidence, not a gate.** It matches agent-ops
`conventions/feedback-hooks-are-not-guards.md`: a feedback hook informs a human, a
redline gate blocks an action. This is the first kind. It never changes a verdict in
`classify()`, and it never touches `loop.ps1`'s own accept/reject/halt logic. A human
reading `evals/loop/run_<UTC>.jsonl` gets the loop's self-report and a mechanical
check of it, side by side, for the same run.

**Fail open, loudly.** The sibling clone or the script may be missing, and the script
may exit nonzero. None of these may kill a run. `Invoke-Reconcile` in `loop/loop.ps1`
catches every failure path and writes a `reconcile_unavailable` record with a reason
instead. The function also carries an outer catch as a backstop, so an unexpected
exception cannot escape it either. The run continues either way.

**The scorer stays tolerant of the two new kinds.** `scripts/morning_review.py`
recognizes `"reconcile"` and `"reconcile_unavailable"` as `INFORMATIONAL_KINDS`: the
"unrecognized kind" DRIFTED check does not fire on them, and every check that reads a
verdict or an a/b/c score skips them. They do not count as ledger iterations, and they
do not enter the B-ratchet or the token total. `tests/test_morning_review.py` pins
this: a SHIPPED run and a STUCK run each keep their verdict with reconcile records
interleaved, and an arbitrary unrecognized kind (already covered before this
amendment) still trips DRIFTED.

**Path resolution.** `Invoke-Reconcile` resolves the sibling agent-ops clone the same
way `dotfiles/claude/setup-windows.ps1` resolves it for the credential-guard family:
one directory above this repo's root, then into `agent-ops`. This holds for the loop
worktree too, because `loop/README.md`'s own setup command
(`git worktree add ../dnc-loop -b loop/prompt-optimize`) places the worktree directly
beside `agent-ops` under the code root. Before running anything from that path, the
function also checks the directory is a git working copy whose origin remote looks
like `agent-ops` -- lexical resolution alone would run whatever code sits in a
directory that happens to have that name, wherever a worktree happens to be created.
A directory with no `.git`, or a git repo whose origin does not match, is treated the
same as a missing script: a `reconcile_unavailable` record, never a run.

**Not a redline gate.** This amendment does not touch ADR-016's seven rails or this
ADR's own four-way verdict. A reconcile snapshot cannot halt a run, cannot revert a
commit, and cannot change SHIPPED to PARTIAL. It is read by a human at the same time
as everything else in the ledger.

**Review.** A read-only cross-model review (`codex exec`) of this diff against `main`
found two issues, confirmed against this repo's own files and fixed before merge:

- **A reconcile call had no wall-clock bound of its own.** The internal 30s timeout
  inside `reconcile.py`'s own `git`/`gh` calls does not protect the caller if the
  interpreter launch itself stalls, or if a subprocess `gh` spawns (a browser window
  for an interactive auth prompt, say) survives past its parent's own timeout on
  Windows. A feedback hook that can hang is a hook that can wedge the very run it was
  added to observe, which is exactly what this amendment's "fail open, loudly" framing
  had promised could not happen. Fixed: the call now runs inside a background job
  (`Start-Job`), bounded by a new `-ReconcileTimeoutSeconds` parameter (default 45,
  generous over the few seconds a real snapshot takes). A timed-out job is stopped and
  reported as a `reconcile_unavailable` record, same as any other failure.
- **The sibling-clone path resolution had no identity check.** Confirmed above.

Fixing the first issue surfaced a second, unrelated bug the manual smoke test caught
before either review pass: the background job's scriptblock originally declared its
parameter as `$Args`, which collides with PowerShell's automatic `$args` variable and
silently bound to an empty array instead of the argument list `-ArgumentList` passed.
`python` then ran `reconcile.py` with no `--repo` at all, producing a syntactically
valid but empty snapshot (`{"repos": []}`) -- a record that would have looked like
success while carrying nothing. Renamed to `$PythonArgs`; the smoke test's Case 2
(the real-repo success path) is what caught it, by asserting `snapshot.repos` is
non-empty rather than only that the record's `kind` is `"reconcile"`.
