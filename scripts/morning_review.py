"""Morning review: the mechanical scorer for one Ralph outer-loop run.

The outer loop (``loop/loop.ps1``, decisions/archive/026-ralph-loop-honest-ruler.md)
runs unattended and writes one JSONL record per iteration to
``evals/loop/run_<UTC>.jsonl``. Before a human reads the agent's own summary
(``loop/state/log.md``), this script reads the run log plus the loop
worktree's git state and classifies the run into one of four verdicts:

- **SHIPPED** -- the run ended on a real stopping signal (the agent declared
  done, or the loop's own stuck-halt fired), the best accepted iteration beat
  the baseline on the hidden B split past the measured noise floor, and the
  held-out C split neither fell past tolerance nor sat suspiciously flat
  despite the B gain (the Goodhart check -- ADR-026's amendment found exactly
  that pattern to be a shared annotation defect, not a real win).
- **PARTIAL** -- B improved, but either the run ended on a resource cap
  (iterations, budget, or time) rather than a real stopping signal, C fell
  past tolerance, or C stayed flat while B moved (unconfirmed, not
  disqualified: this is a diagnostic flag, never a gate).
- **STUCK** -- no accepted iteration ever beat the baseline B score by more
  than noise.
- **DRIFTED** -- the run log is malformed, the worktree touched a file outside
  ``loop/blast-radius.txt`` (checked against the pre-run declaration, not
  whatever the run's own commits left it saying), or a stopping signal is
  claimed without the ledger evidence that would substantiate it.

The four checks are evaluated in that priority order and each returns
immediately, so the *output* is always exactly one verdict -- see
:func:`classify` for why that is a precedence partition, not a claim that
the underlying conditions never overlap.

The log may also carry ``"reconcile"`` and ``"reconcile_unavailable"``
records (ADR-027 amendment, 2026-08-22): a ground-truth git/gh snapshot
``loop.ps1`` appends after each iteration and once at run end, or a note
that the snapshot could not be taken. See :data:`INFORMATIONAL_KINDS`.
These are read as evidence for a human, never as input to a verdict --
they carry no score and are excluded from every check below. Usage::

    uv run python scripts/morning_review.py evals/loop/run_20260820T011747Z.jsonl
    uv run python scripts/morning_review.py <run.jsonl> --worktree ../dnc-loop --json

Exit code encodes the verdict: 0 SHIPPED, 1 PARTIAL, 2 STUCK, 3 DRIFTED.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SHIPPED = "SHIPPED"
PARTIAL = "PARTIAL"
STUCK = "STUCK"
DRIFTED = "DRIFTED"

EXIT_CODES = {SHIPPED: 0, PARTIAL: 1, STUCK: 2, DRIFTED: 3}

# The noise floor for a macro-F1 delta, and the Goodhart tolerance derived
# from it.
#
# Reused, not invented: the repo's own stability report (evals/stability.txt)
# measures a 3-run noise floor for THIS metric family -- category_macro_f1
# std 0.0012 -- and the report itself treats 2x that as the line between "moved"
# and "noise" (0.0024 here; not category_accuracy's 0.0019/0.0038, a different
# metric the earlier draft of this constant mistakenly cited). Two things reuse
# this floor:
#   - A B "improvement" must clear it, or a noise-level wiggle would read as
#     a real gain.
#   - A C move smaller than it is indistinguishable from noise in either
#     direction -- which matters for the Goodhart alarm below, not only for
#     "C fell."
NOISE_FLOOR = 0.0024
DEFAULT_C_TOLERANCE = NOISE_FLOOR

SIGIL = "LOOP-COMPLETE:"

# Record kinds the loop appends for reconciliation (loop.ps1's Invoke-Reconcile,
# ADR-027 amendment 2026-08-22): a ground-truth snapshot from the sibling
# agent-ops clone's scripts/reconcile.py, or a note that the snapshot could
# not be taken. Neither carries a/b/c scores or a verdict, and neither is an
# "iteration" the B-ratchet or the contiguity check should see -- they are
# recognized here so they do not trip the "unrecognized kind" DRIFTED check,
# and skipped everywhere else. This is evidence for a human reading the run,
# never a gate: a missing or failed reconcile never changes a verdict.
INFORMATIONAL_KINDS = {"reconcile", "reconcile_unavailable"}


@dataclass
class Iteration:
    """One ledger record, reduced to what the rubric needs.

    Attributes:
        kind: ``"baseline"`` or ``"iteration"``.
        iteration: The iteration number (0 for the baseline).
        verdict: ``"baseline"``, ``"accept"``, or ``"reject"``.
        reject_gate: The gate that fired, if rejected; else ``None``.
        a: Split A's macro-F1.
        b: Split B's (hidden) macro-F1.
        c: Split C's (hidden) macro-F1.
        tokens: Tokens spent scoring this record.
    """

    kind: str
    iteration: int
    verdict: str
    reject_gate: str | None
    a: float
    b: float
    c: float
    tokens: int


@dataclass
class ScopeCheck:
    """The result of diffing the loop worktree against its blast radius.

    Attributes:
        checked: Whether a worktree was available to check at all.
        violation: Whether a file outside the blast radius was touched.
        detail: A short, human-readable explanation.
    """

    checked: bool
    violation: bool
    detail: str


def _malformed_reasons(records: list[dict]) -> list[str]:
    """Find structural defects in a parsed ledger.

    Checks the properties this scorer's rubric depends on: exactly one
    baseline record, first in the file; a contiguous 1..N iteration sequence
    with no gaps or duplicates; and the fields every downstream computation
    reads (``kind``, ``iteration``, ``verdict``, and each of ``a``/``b``/``c``
    carrying a numeric ``macro_f1``).

    Args:
        records: The parsed JSON records, in file order.

    Returns:
        A list of defect descriptions. Empty means the log is well-formed.
    """
    reasons: list[str] = []
    if not records:
        return ["empty log: no records"]

    valid_kinds = {"baseline", "iteration"} | INFORMATIONAL_KINDS
    valid_verdicts = {"baseline", "accept", "reject"}

    # A record with a kind neither "baseline" nor "iteration" is otherwise
    # invisible to the contiguity check below, yet _best_by_b matches on
    # verdict alone -- an unrecognized kind must be caught here, or a bogus
    # extra record (verdict="accept", an inflated b) could win best-by-B
    # without ever being counted as an iteration. The two INFORMATIONAL_KINDS
    # are recognized here but carry no verdict/a/b/c of their own -- they are
    # excluded from every check below that reads those fields.
    for record in records:
        kind = record.get("kind")
        if kind not in valid_kinds:
            reasons.append(f"record has an unrecognized 'kind': {kind!r}")
        verdict = record.get("verdict")
        if verdict is not None and verdict not in valid_verdicts:
            reasons.append(f"record has an unrecognized 'verdict': {verdict!r}")

    baselines = [r for r in records if r.get("kind") == "baseline"]
    if len(baselines) != 1:
        reasons.append(f"expected exactly one baseline record, found {len(baselines)}")
    elif records[0].get("kind") != "baseline":
        reasons.append("the baseline record is not first in the log")
    elif baselines[0].get("iteration") != 0:
        reasons.append(
            f"the baseline record's iteration is "
            f"{baselines[0].get('iteration')!r}, not 0"
        )

    seen: list[int] = []
    for record in records:
        if record.get("kind") != "iteration":
            continue
        num = record.get("iteration")
        if not isinstance(num, int):
            reasons.append(f"iteration record missing an integer 'iteration': {record}")
            continue
        seen.append(num)
    expected = list(range(1, len(seen) + 1))
    if seen != expected:
        reasons.append(f"non-contiguous or duplicate iteration numbers: got {seen}")

    for record in records:
        kind = record.get("kind")
        label = f"{kind or '?'} {record.get('iteration', '?')}"
        if kind in INFORMATIONAL_KINDS:
            # No verdict, no a/b/c: only "iteration" is expected, so the
            # B-ratchet and evidence table can still label the record.
            if "iteration" not in record:
                reasons.append(f"{label}: missing 'iteration'")
            continue
        for key in ("kind", "iteration", "verdict"):
            if key not in record:
                reasons.append(f"{label}: missing '{key}'")
        for split in ("a", "b", "c"):
            value = record.get(split)
            score = value.get("macro_f1") if isinstance(value, dict) else None
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                reasons.append(f"{label}: missing numeric '{split}.macro_f1'")
            elif not 0.0 <= score <= 1.0:
                reasons.append(f"{label}: '{split}.macro_f1' {score} is outside [0, 1]")
        if record.get("verdict") == "reject" and "reject_gate" not in record:
            reasons.append(f"{label}: rejected with no 'reject_gate'")

    return reasons


def load_run_log(path: Path) -> tuple[list[Iteration], list[str]]:
    """Parse a run log into typed iterations, alongside any defects found.

    A record that fails to parse as JSON, or fails the structural checks in
    :func:`_malformed_reasons`, does not raise: it is folded into the defect
    list so the caller can route the whole run to DRIFTED with a full
    explanation, rather than crashing on the first bad line.

    Args:
        path: Path to the JSONL run log.

    Returns:
        A tuple of (parsed iterations in file order, defect descriptions).
        Iterations is best-effort and may be incomplete when defects exist.
    """
    if not path.exists():
        return [], [f"run log not found: {path}"]

    records: list[dict] = []
    reasons: list[str] = []
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            reasons.append(f"line {lineno}: invalid JSON ({exc.msg})")

    reasons.extend(_malformed_reasons(records))

    iterations: list[Iteration] = []
    for record in records:
        if record.get("kind") in INFORMATIONAL_KINDS:
            # Carries no verdict or a/b/c score; not a defect, just not an
            # Iteration this rubric scores against.
            continue
        try:
            iterations.append(
                Iteration(
                    kind=record["kind"],
                    iteration=record["iteration"],
                    verdict=record["verdict"],
                    reject_gate=record.get("reject_gate"),
                    a=float(record["a"]["macro_f1"]),
                    b=float(record["b"]["macro_f1"]),
                    c=float(record["c"]["macro_f1"]),
                    tokens=int(record.get("tokens", 0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # already recorded as a defect above

    return iterations, reasons


def read_stop_signal(worktree: Path | None) -> tuple[str, list[str]]:
    """Read the loop's own claimed stopping signal from its state directory.

    ``loop/state/status.md`` carries the ``LOOP-COMPLETE:`` sigil when the
    agent declared itself done (the rubric's "threshold"). ``loop/state/
    stuck.json`` exists when the outer script's own halt fired on three
    identical failures (the rubric's "plateau"). Neither is written by this
    scorer; both are read as evidence to cross-check, never trusted alone --
    see :func:`_check_done_signal_evidence`.

    Args:
        worktree: The loop's git worktree root, or ``None`` if not given.

    Returns:
        A tuple of (``"threshold"``, ``"plateau"``, or
        ``"budget_or_iteration_cap"``, a list of problems found reading the
        signal, e.g. both files present at once).
    """
    if worktree is None:
        return "budget_or_iteration_cap", []

    status = worktree / "loop" / "state" / "status.md"
    stuck = worktree / "loop" / "state" / "stuck.json"
    has_threshold = status.exists() and SIGIL in status.read_text(encoding="utf-8")
    has_plateau = stuck.exists()

    if has_threshold and has_plateau:
        return "budget_or_iteration_cap", [
            "both status.md (LOOP-COMPLETE) and stuck.json exist -- "
            "a run cannot have completed and stalled at once"
        ]
    if has_threshold:
        return "threshold", []
    if has_plateau:
        return "plateau", []
    return "budget_or_iteration_cap", []


def _check_done_signal_evidence(
    done_signal: str, iterations: list[Iteration], worktree: Path | None
) -> list[str]:
    """Cross-check a claimed ``"plateau"`` signal against the ledger itself.

    A stuck halt is only real if the ledger's own tail shows what the halt
    claims: three consecutive rejected iterations sharing one gate. A claim
    that does not match the evidence is treated as drift, not trusted.

    Args:
        done_signal: The signal from :func:`read_stop_signal`.
        iterations: The parsed run log (iteration records only, in order).
        worktree: The loop's git worktree root, or ``None``.

    Returns:
        A list of problems; empty means the claim is substantiated (or there
        is no claim to check).
    """
    if done_signal != "plateau" or worktree is None:
        return []

    stuck_path = worktree / "loop" / "state" / "stuck.json"
    try:
        claim = json.loads(stuck_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"stuck.json exists but could not be read: {exc}"]

    tail = [it for it in iterations if it.kind == "iteration"][-3:]
    if len(tail) < 3:
        return ["stuck.json claims a halt, but the log has fewer than 3 iterations"]
    gates = {it.reject_gate for it in tail}
    verdicts = {it.verdict for it in tail}
    if verdicts != {"reject"} or len(gates) != 1:
        return [
            "stuck.json claims three identical failures, but the log's last "
            f"3 iterations do not match: verdicts={sorted(verdicts)}, "
            f"gates={sorted(g for g in gates if g)}"
        ]
    claimed_iteration = claim.get("iteration")
    if claimed_iteration is not None and claimed_iteration != tail[-1].iteration:
        return [
            f"stuck.json claims iteration {claimed_iteration}, "
            f"but the log's last record is iteration {tail[-1].iteration}"
        ]
    return []


def _run_git(worktree: Path, *args: str) -> str:
    """Run one git command against a worktree and return its stdout.

    Args:
        worktree: The ``-C`` target.
        *args: The git subcommand and its arguments.

    Returns:
        Stdout, stripped. Empty string on any git failure -- callers treat a
        failed git call as "nothing to report", not as a crash, since a
        missing worktree is a normal (if unverifiable) state for this
        scorer, not a bug.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree), *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def _parse_blast_radius(text: str) -> list[str]:
    """Parse ``loop/blast-radius.txt`` content the same way ``loop.ps1`` does.

    Args:
        text: The file's content.

    Returns:
        The declared entries, comments and blank lines dropped.
    """
    lines = []
    for line in text.splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            lines.append(entry)
    return lines


def _in_blast_radius(changed_path: str, entries: list[str]) -> bool:
    """Mirror ``loop.ps1``'s ``Test-InBlastRadius``.

    A directory entry (one ending in ``/``) matches by prefix; anything else
    matches exactly.

    Args:
        changed_path: A repo-relative path from ``git status``/``git diff``.
        entries: The parsed blast-radius entries.

    Returns:
        Whether the path is declared in bounds.
    """
    for entry in entries:
        if entry.endswith("/"):
            if changed_path.startswith(entry):
                return True
        elif changed_path == entry:
            return True
    return False


def check_scope(worktree: Path | None, base_ref: str) -> ScopeCheck:
    """Diff the loop worktree against its declared blast radius.

    Checks both the committed history since ``base_ref`` (what the loop's own
    rail-8 revert should already have kept clean -- this is an independent
    second measurement, not a re-trust of the ledger) and the current working
    tree (uncommitted leftovers a halted run can leave behind).

    The declaration itself is read from ``base_ref`` -- the pre-run commit --
    never from the worktree's current state. Reading it from HEAD would let a
    run that edited ``loop/blast-radius.txt`` (to add back whatever it
    touched) certify itself: the boundary must be fixed before the run, not
    derived from what the run did.

    Args:
        worktree: The loop's git worktree root, or ``None`` to skip the
            check (it is reported as unchecked, never as clean).
        base_ref: The ref the loop branched from, usually ``"main"``.

    Returns:
        The scope-check result.
    """
    if worktree is None or not _run_git(worktree, "rev-parse", "--git-dir"):
        return ScopeCheck(checked=False, violation=False, detail="no worktree given")

    merge_base = _run_git(worktree, "merge-base", base_ref, "HEAD")
    if not merge_base:
        return ScopeCheck(
            checked=False,
            violation=False,
            detail=f"could not resolve base ref {base_ref!r}",
        )

    blast_text = _run_git(worktree, "show", f"{merge_base}:loop/blast-radius.txt")
    blast = _parse_blast_radius(blast_text)
    if not blast:
        return ScopeCheck(
            checked=False,
            violation=False,
            detail=f"loop/blast-radius.txt not found at {base_ref} ({merge_base[:8]})",
        )

    committed = _run_git(worktree, "diff", f"{merge_base}..HEAD", "--name-only")
    outside: list[str] = [
        p for p in committed.splitlines() if p and not _in_blast_radius(p, blast)
    ]

    porcelain = _run_git(worktree, "status", "--porcelain")
    for line in porcelain.splitlines():
        changed_path = line[3:].strip().strip('"')
        if changed_path and not _in_blast_radius(changed_path, blast):
            outside.append(changed_path)

    if outside:
        return ScopeCheck(
            checked=True,
            violation=True,
            detail=f"files outside the blast radius: {', '.join(sorted(set(outside)))}",
        )
    return ScopeCheck(checked=True, violation=False, detail="blast radius respected")


def _best_by_b(iterations: list[Iteration]) -> Iteration:
    """The accepted iteration with the highest B, baseline included.

    Mirrors ``scripts/loop_metrics.py``'s own ``best_b``: a rejected
    iteration's B never counts, so a rejected iteration can never become the
    bar this scorer measures "improvement" against either.

    Args:
        iterations: The full parsed log, baseline included.

    Returns:
        The winning record. Ties go to the later iteration, matching the
        branch's actual final committed state.
    """
    candidates = [it for it in iterations if it.verdict in ("baseline", "accept")]
    return max(candidates, key=lambda it: (it.b, it.iteration))


@dataclass
class Review:
    """The finished morning-review result.

    Attributes:
        verdict: One of SHIPPED, PARTIAL, STUCK, DRIFTED.
        reasons: Human-readable reasons for the verdict, most specific first.
        done_signal: How the run says it ended.
        b_baseline: Baseline B macro-F1.
        b_best: Best accepted B macro-F1 (baseline if nothing was accepted).
        b_best_iteration: Which iteration produced ``b_best``.
        b_improved: Whether an accepted iteration beat the baseline B.
        c_baseline: Baseline C macro-F1.
        c_at_best: C macro-F1 at the best-by-B iteration.
        c_delta: ``c_at_best - c_baseline``.
        c_tolerance: The tolerance ``c_delta`` was checked against.
        goodhart_ok: Whether C neither fell past tolerance nor sat flat
            despite a B gain (the shared-defect pattern).
        total_tokens: Tokens spent across every scored record.
        scope: The blast-radius check result.
        malformed: Structural defects found in the log, if any.
        table: One row per record, for the evidence table.
    """

    verdict: str
    reasons: list[str]
    done_signal: str
    b_baseline: float
    b_best: float
    b_best_iteration: int
    b_improved: bool
    c_baseline: float
    c_at_best: float
    c_delta: float
    c_tolerance: float
    goodhart_ok: bool
    total_tokens: int
    scope: ScopeCheck
    malformed: list[str] = field(default_factory=list)
    table: list[dict] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """The process exit code this verdict maps to."""
        return EXIT_CODES[self.verdict]

    def to_json(self) -> dict[str, Any]:
        """Render the full result as a JSON-serializable dict."""
        return {
            "verdict": self.verdict,
            "exit_code": self.exit_code,
            "reasons": self.reasons,
            "done_signal": self.done_signal,
            "b": {
                "baseline": self.b_baseline,
                "best": self.b_best,
                "best_iteration": self.b_best_iteration,
                "improved": self.b_improved,
            },
            "c": {
                "baseline": self.c_baseline,
                "at_best": self.c_at_best,
                "delta": round(self.c_delta, 6),
                "tolerance": self.c_tolerance,
                "goodhart_ok": self.goodhart_ok,
            },
            "tokens_total": self.total_tokens,
            "scope": {
                "checked": self.scope.checked,
                "violation": self.scope.violation,
                "detail": self.scope.detail,
            },
            "malformed": self.malformed,
            "iterations": self.table,
        }


def _evidence_table(iterations: list[Iteration]) -> list[dict]:
    """Build the per-iteration A/B/C evidence table, deltas vs baseline.

    Args:
        iterations: The parsed log, in file order.

    Returns:
        One dict per record, in file order.
    """
    if not iterations:
        return []
    base = iterations[0]
    rows = []
    for it in iterations:
        rows.append(
            {
                "iteration": it.iteration,
                "verdict": it.verdict,
                "reject_gate": it.reject_gate,
                "a": it.a,
                "delta_a": round(it.a - base.a, 4),
                "b": it.b,
                "delta_b": round(it.b - base.b, 4),
                "c": it.c,
                "delta_c": round(it.c - base.c, 4),
                "tokens": it.tokens,
            }
        )
    return rows


def classify(
    iterations: list[Iteration],
    malformed: list[str],
    done_signal: str,
    signal_problems: list[str],
    scope: ScopeCheck,
    c_tolerance: float,
    worktree: Path | None = None,
) -> Review:
    """Apply the four-way rubric to a parsed run.

    The checks below are evaluated in this strict priority order and each
    one returns immediately, so the *output* is always exactly one verdict --
    this is a precedence partition, not a claim that the four classes'
    underlying conditions never overlap (a scope violation and a stalled B
    can both be true of the same run; DRIFTED is simply checked first):

    1. A malformed log, or a claimed stopping signal the ledger does not
       substantiate -> DRIFTED.
    2. A file touched outside the declared blast radius -> DRIFTED.
    3. No accepted iteration improved B past the noise floor -> STUCK.
    4. B improved: SHIPPED only if the run ended on a real signal (threshold
       or plateau), C did not fall past tolerance, AND C did not stay flat
       despite the B gain (ADR-026's amendment: "a large A/B gain with a flat
       C is a defect signature, not a success" -- exactly what its one live
       run produced). Anything short of all three is PARTIAL, never DRIFTED:
       this is a diagnostic, not a gate, matching ADR-026's own "C should get
       an alarm, not a vote."

    Args:
        iterations: The parsed run log.
        malformed: Structural defects already found in the log.
        done_signal: The claimed stopping signal.
        signal_problems: Problems already found reading that signal.
        scope: The blast-radius check.
        c_tolerance: How far C may fall before it is treated as a real drop.
        worktree: The loop's git worktree root, or ``None``. Used only to
            cross-check a claimed ``"plateau"`` signal against the ledger.

    Returns:
        The finished review.
    """
    table = _evidence_table(iterations)
    total_tokens = sum(it.tokens for it in iterations)

    if malformed:
        return Review(
            verdict=DRIFTED,
            reasons=list(malformed),
            done_signal=done_signal,
            b_baseline=0.0,
            b_best=0.0,
            b_best_iteration=0,
            b_improved=False,
            c_baseline=0.0,
            c_at_best=0.0,
            c_delta=0.0,
            c_tolerance=c_tolerance,
            goodhart_ok=False,
            total_tokens=total_tokens,
            scope=scope,
            malformed=malformed,
            table=table,
        )

    baseline = next((it for it in iterations if it.kind == "baseline"), None)
    assert baseline is not None  # malformed check above guarantees this

    signal_evidence = _check_done_signal_evidence(done_signal, iterations, worktree)
    signal_problems = signal_problems + signal_evidence
    best = _best_by_b(iterations)
    b_gain = best.b - baseline.b
    # "Improved" must clear the measured noise floor (evals/stability.txt),
    # not just be positive -- a 0.0005 wiggle is not a gain, it is the same
    # run-to-run noise the stability report exists to name.
    b_improved = best.iteration != 0 and b_gain > NOISE_FLOOR
    c_delta = best.c - baseline.c
    c_fell_past_tolerance = c_delta < -c_tolerance
    # The defect signature ADR-026's amendment found by hand: B clears the
    # noise floor while C sits inside it (up, down, or dead flat -- the
    # run that prompted this ADR moved C by exactly +0.000). C is not a
    # gate here, only a flag: this never blocks a commit, it only keeps a
    # run from reading as SHIPPED on the strength of a split that never
    # actually moved.
    c_flat_despite_b_gain = b_improved and abs(c_delta) <= NOISE_FLOOR
    goodhart_ok = not c_fell_past_tolerance and not c_flat_despite_b_gain

    if signal_problems:
        return Review(
            verdict=DRIFTED,
            reasons=signal_problems,
            done_signal=done_signal,
            b_baseline=baseline.b,
            b_best=best.b,
            b_best_iteration=best.iteration,
            b_improved=b_improved,
            c_baseline=baseline.c,
            c_at_best=best.c,
            c_delta=c_delta,
            c_tolerance=c_tolerance,
            goodhart_ok=goodhart_ok,
            total_tokens=total_tokens,
            scope=scope,
            table=table,
        )

    if scope.checked and scope.violation:
        return Review(
            verdict=DRIFTED,
            reasons=[scope.detail],
            done_signal=done_signal,
            b_baseline=baseline.b,
            b_best=best.b,
            b_best_iteration=best.iteration,
            b_improved=b_improved,
            c_baseline=baseline.c,
            c_at_best=best.c,
            c_delta=c_delta,
            c_tolerance=c_tolerance,
            goodhart_ok=goodhart_ok,
            total_tokens=total_tokens,
            scope=scope,
            table=table,
        )

    if not b_improved:
        reason = (
            "every iteration was rejected"
            if all(it.verdict != "accept" for it in iterations)
            else "no accepted iteration improved B over the baseline"
        )
        return Review(
            verdict=STUCK,
            reasons=[reason],
            done_signal=done_signal,
            b_baseline=baseline.b,
            b_best=best.b,
            b_best_iteration=best.iteration,
            b_improved=b_improved,
            c_baseline=baseline.c,
            c_at_best=best.c,
            c_delta=c_delta,
            c_tolerance=c_tolerance,
            goodhart_ok=goodhart_ok,
            total_tokens=total_tokens,
            scope=scope,
            table=table,
        )

    reasons = []
    if done_signal not in ("threshold", "plateau"):
        reasons.append(
            f"B improved (+{b_gain:.3f}) but the run ended on "
            f"'{done_signal}', not a clean stopping signal"
        )
    if c_fell_past_tolerance:
        reasons.append(
            f"C fell {-c_delta:.3f} past the {c_tolerance:.3f} tolerance "
            "(the loop improved a split it cannot see)"
        )
    if c_flat_despite_b_gain:
        reasons.append(
            f"B gained +{b_gain:.3f} while C moved only {c_delta:+.3f} -- "
            f"within the {NOISE_FLOOR:.4f} noise floor. ADR-026's amendment "
            "found exactly this pattern to be a shared annotation defect, "
            "not a generalizing improvement; treat as unconfirmed"
        )
    verdict = SHIPPED if not reasons else PARTIAL
    if verdict == SHIPPED:
        reasons = [
            f"B improved +{b_gain:.3f} over baseline, C held "
            f"({c_delta:+.3f}, outside the noise floor and within "
            f"{c_tolerance:.3f} tolerance), done_signal='{done_signal}'"
        ]

    return Review(
        verdict=verdict,
        reasons=reasons,
        done_signal=done_signal,
        b_baseline=baseline.b,
        b_best=best.b,
        b_best_iteration=best.iteration,
        b_improved=b_improved,
        c_baseline=baseline.c,
        c_at_best=best.c,
        c_delta=c_delta,
        c_tolerance=c_tolerance,
        goodhart_ok=goodhart_ok,
        total_tokens=total_tokens,
        scope=scope,
        table=table,
    )


def review_run(
    run_log: Path,
    worktree: Path | None,
    base_ref: str = "main",
    c_tolerance: float = DEFAULT_C_TOLERANCE,
) -> Review:
    """Read a run log plus worktree state and classify the run.

    Args:
        run_log: Path to the ``evals/loop/run_<UTC>.jsonl`` file.
        worktree: The loop's git worktree root, or ``None`` to skip the
            scope check and the stop-signal read.
        base_ref: The ref the loop branched from.
        c_tolerance: The Goodhart tolerance for split C.

    Returns:
        The finished review.
    """
    iterations, malformed = load_run_log(run_log)
    done_signal, signal_problems = read_stop_signal(worktree)
    scope = check_scope(worktree, base_ref)
    return classify(
        iterations,
        malformed,
        done_signal,
        signal_problems,
        scope,
        c_tolerance,
        worktree,
    )


def _print_human(review: Review) -> None:
    """Print the one-line verdict and the evidence table.

    Args:
        review: The finished review.
    """
    print(f"{review.verdict}: {'; '.join(review.reasons)}")
    if review.table:
        header = f"{'iter':>4} {'verdict':<9} {'gate':<14} {'A':>6} {'B':>6} {'C':>6} {'tokens':>9}"
        print(header)
        for row in review.table:
            gate = row["reject_gate"] or "-"
            print(
                f"{row['iteration']:>4} {row['verdict']:<9} {gate:<14} "
                f"{row['a']:>6.3f} {row['b']:>6.3f} {row['c']:>6.3f} "
                f"{row['tokens']:>9}"
            )
    print(f"done_signal: {review.done_signal}")
    print(
        f"best-by-B: iteration {review.b_best_iteration} "
        f"(B {review.b_best:.3f}, {review.b_best - review.b_baseline:+.3f} vs baseline)"
    )
    print(
        f"C at best: {review.c_at_best:.3f} ({review.c_delta:+.4f}, "
        f"tolerance {review.c_tolerance:.4f}) -> "
        f"{'OK' if review.goodhart_ok else 'FAILED'}"
    )
    scope_state = (
        "not checked"
        if not review.scope.checked
        else (
            "VIOLATION: " + review.scope.detail if review.scope.violation else "clean"
        )
    )
    print(f"scope: {scope_state}")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the review, and return the exit code.

    Args:
        argv: Argument vector, or ``None`` to read ``sys.argv``.

    Returns:
        The exit code for the verdict reached.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_log", type=Path, help="path to the run's JSONL log")
    parser.add_argument(
        "--worktree",
        type=Path,
        default=None,
        help="the loop's git worktree root (default: derived from run_log's "
        "location under <worktree>/evals/loop/)",
    )
    parser.add_argument(
        "--base-ref",
        default="main",
        help="the ref the loop branched from (default: main)",
    )
    parser.add_argument(
        "--c-tolerance",
        type=float,
        default=DEFAULT_C_TOLERANCE,
        help=f"Goodhart tolerance for split C (default: {DEFAULT_C_TOLERANCE})",
    )
    parser.add_argument("--json", action="store_true", help="print JSON, not prose")
    args = parser.parse_args(argv)

    worktree = args.worktree
    if worktree is None:
        inferred = args.run_log.resolve().parent.parent.parent
        if (inferred / "loop").exists():
            worktree = inferred

    review = review_run(args.run_log, worktree, args.base_ref, args.c_tolerance)

    if args.json:
        print(json.dumps(review.to_json(), indent=2))
    else:
        _print_human(review)

    return review.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
