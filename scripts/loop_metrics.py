"""The honest ruler for the Ralph outer loop (decisions/026).

The outer loop (``loop/loop.ps1``) re-invokes a fresh agent on a frozen
prompt. The agent edits the classifier system prompt. This script is the
only thing that grades that edit, and it splits the grade three ways:

- **A (optimize)** -- the agent reads these failures. Written to
  ``loop/state/report_A.md``, which is the ONLY report the frozen prompt
  tells the agent to read.
- **B (validation)** -- the backpressure. The iteration is accepted only if
  B does not regress against the running best. The agent never sees B.
- **C (test)** -- the honest final number. Recorded, never used for any
  decision, never shown.

The split is ``src/optimize.py``'s split, built by the same
``make_split(seed=...)``, so this ruler and the rung-1 loop measure the same
rows.

**Where the hidden numbers live.** B and C are written to a *ledger* outside
the git worktree (``--ledger``, or ``$LOOP_LEDGER``). During a run they are
not files the agent can read, because they are not in the tree it is working
in. ``loop.ps1`` copies the finished ledger into ``evals/loop/`` after the
last iteration. This is a weaker guarantee than ``src/optimize.py``'s
call-graph guard -- see decisions/026 "What this does not guarantee".

Usage:
    # Establish the starting scores (zero API calls with --dry-run):
    uv run python scripts/loop_metrics.py --mode baseline --dry-run

    # Grade one iteration; exit 0 accepts, exit 3 rejects:
    uv run python scripts/loop_metrics.py --mode check --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from classify import SYSTEM_PROMPT, make_client  # noqa: E402
from gold_eval import GOLD_PATH, load_gold  # noqa: E402
from optimize import (  # noqa: E402
    DATA_PATH,
    DEFAULT_SEED,
    DEFAULT_SPLIT_RATIO,
    AnthropicBackend,
    DryRunBackend,
    build_feedback,
    make_split,
    region_guardrail,
    region_rubric_violations,
    score_split,
)

STATE_DIR = REPO_ROOT / "loop" / "state"
REPORT_A = STATE_DIR / "report_A.md"
VERDICT = STATE_DIR / "verdict.md"

# Exit codes. The outer script branches on these, so they are a contract.
EXIT_ACCEPT = 0
EXIT_ERROR = 1
EXIT_REJECT_B = 3
EXIT_REJECT_REGION = 4

# B must not fall at all. A tolerance here would be a slow leak: each
# iteration would be allowed to give back a little, and ten iterations of
# "a little" is the regression the backpressure exists to stop.
B_TOLERANCE = 0.0


def ledger_path(explicit: str | None) -> Path:
    """Resolve the ledger path from the flag, then the environment.

    Args:
        explicit: The ``--ledger`` value, or ``None``.

    Returns:
        The path to append ledger records to.

    Raises:
        SystemExit: If neither the flag nor ``$LOOP_LEDGER`` is set. There
            is no default inside the repository on purpose: a default in the
            worktree would put the hidden B and C numbers in front of the
            agent, which is the one thing this design must not do.
    """
    value = explicit or os.environ.get("LOOP_LEDGER")
    if not value:
        raise SystemExit(
            "no ledger path: pass --ledger or set $LOOP_LEDGER. It must point "
            "OUTSIDE the git worktree -- it carries the hidden B and C scores."
        )
    path = Path(value).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_ledger(path: Path, record: dict) -> None:
    """Append one JSON record to the ledger.

    Args:
        path: The ledger file.
        record: A JSON-serializable record.
    """
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def read_ledger(path: Path) -> list[dict]:
    """Read every record from the ledger.

    Args:
        path: The ledger file.

    Returns:
        The records in order, or an empty list if the file does not exist.
    """
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def best_b(records: list[dict]) -> float | None:
    """The highest B macro-F1 any accepted record reached.

    A rejected iteration's B score is deliberately excluded. Letting a
    rejected score raise the bar would make the ratchet climb on work the
    loop threw away.

    Args:
        records: Ledger records.

    Returns:
        The best B macro-F1 so far, or ``None`` if nothing scored yet.
    """
    scores = [
        r["b"]["macro_f1"]
        for r in records
        if r.get("b") and r.get("verdict") in (None, "baseline", "accept")
    ]
    return max(scores) if scores else None


def baseline_prompt(records: list[dict]) -> str | None:
    """The classifier prompt recorded at baseline.

    Args:
        records: Ledger records.

    Returns:
        The baseline prompt text, or ``None`` if no baseline was written.
    """
    for record in records:
        if record.get("kind") == "baseline":
            return record.get("prompt")
    return None


def write_report_a(prompt: str, merged_a: pd.DataFrame, iteration: int) -> str:
    """Write the agent-visible set-A report and return its feedback text.

    This is the whole of what the agent is given about how it is doing. It
    carries A only. B and C never enter this function, so they cannot reach
    the file through it.

    Args:
        prompt: The prompt that produced these predictions.
        merged_a: Split A's ground truth merged with its predictions.
        iteration: The iteration number this report describes.

    Returns:
        The feedback text written into the report.
    """
    feedback, _, _ = build_feedback(merged_a)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_A.write_text(
        "\n".join(
            [
                "# Set A report (the only scores you may read)",
                "",
                f"- iteration: {iteration}",
                f"- generated: {datetime.now(UTC).isoformat()}",
                f"- prompt characters: {len(prompt)}",
                "",
                "Split B and split C are scored too. Their numbers are held "
                "outside this worktree on purpose. Do not look for them, and "
                "do not add code that reads them.",
                "",
                "## Set A failures",
                "",
                "```",
                feedback,
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return feedback


def write_verdict(iteration: int, verdict: str, reason: str) -> None:
    """Write the agent-visible verdict for one iteration.

    The reason names the gate that fired. It never carries a B or C number,
    because a rejection that reports the hidden score turns the hidden score
    into a signal the agent can hill-climb.

    Args:
        iteration: The iteration number.
        verdict: ``accept`` or ``reject``.
        reason: A short, number-free explanation.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    VERDICT.write_text(
        "\n".join(
            [
                "# Last iteration verdict",
                "",
                f"- iteration: {iteration}",
                f"- verdict: {verdict}",
                f"- reason: {reason}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build_backend(dry_run: bool, model: str | None):
    """Build the scoring backend.

    Args:
        dry_run: If true, use the zero-API deterministic mock.
        model: Model id for a live run; ignored when ``dry_run`` is set.

    Returns:
        An object implementing ``src/optimize.py``'s ``OptimizerBackend``.
    """
    if dry_run:
        return DryRunBackend()
    client = make_client()
    return AnthropicBackend(client, model=model) if model else AnthropicBackend(client)


def score_all(prompt: str, backend, split) -> dict:
    """Score a prompt on A, B, and C and return a ledger-shaped record body.

    Args:
        prompt: The classifier system prompt to grade.
        backend: The scoring backend.
        split: The A/B/C split.

    Returns:
        A dict with the three splits' scores, the region guardrail, the
        token spend, and split A's merged predictions under ``merged_a``.
    """
    a = score_split(prompt, backend, split.a)
    b = score_split(prompt, backend, split.b)
    c = score_split(prompt, backend, split.c)
    return {
        "a": a.as_dict(),
        "b": b.as_dict(),
        "c": c.as_dict(),
        "region_guardrail": region_guardrail(c.merged),
        "tokens": a.tokens + b.tokens + c.tokens,
        "merged_a": a.merged,
    }


def run(args: argparse.Namespace) -> int:
    """Run one baseline or one check and return the process exit code.

    Args:
        args: Parsed command-line arguments.

    Returns:
        One of the ``EXIT_*`` codes.
    """
    ledger = ledger_path(args.ledger)
    records = read_ledger(ledger)

    df_synth = pd.read_csv(REPO_ROOT / DATA_PATH)
    df_gold = load_gold(str(REPO_ROOT / GOLD_PATH)).rename(
        columns={"domain": "operational_domain"}
    )
    split = make_split(df_synth, df_gold, ratio=args.split_ratio, seed=args.seed)
    backend = build_backend(args.dry_run, args.model)

    prompt = SYSTEM_PROMPT
    iteration = len([r for r in records if r.get("kind") == "iteration"]) + (
        0 if args.mode == "baseline" else 1
    )

    scored = score_all(prompt, backend, split)
    merged_a = scored.pop("merged_a")
    write_report_a(prompt, merged_a, iteration)

    record = {
        "kind": "baseline" if args.mode == "baseline" else "iteration",
        "iteration": iteration,
        "timestamp": datetime.now(UTC).isoformat(),
        "dry_run": bool(args.dry_run),
        "split_hashes": split.hashes,
        **scored,
    }

    if args.mode == "baseline":
        record["prompt"] = prompt
        record["verdict"] = "baseline"
        append_ledger(ledger, record)
        write_verdict(iteration, "accept", "baseline recorded")
        print(f"baseline: A macro-F1 {scored['a']['macro_f1']:.3f}")
        print(f"ledger: {ledger}")
        return EXIT_ACCEPT

    # --- the two acceptance gates ------------------------------------------
    start = baseline_prompt(records)
    if start is None:
        raise SystemExit("no baseline in the ledger: run --mode baseline first.")

    violations = region_rubric_violations(start, prompt)
    if violations:
        record["verdict"] = "reject"
        record["reject_gate"] = "region_rubric"
        record["violations"] = violations
        append_ledger(ledger, record)
        write_verdict(
            iteration,
            "reject",
            "the frozen region rubric changed; it must survive byte for byte "
            "(ADR-024 adopted that clause; this loop may not touch it)",
        )
        print("REJECT: region rubric damaged.")
        for problem in violations:
            print(f"  - {problem}")
        return EXIT_REJECT_REGION

    bar = best_b(records)
    passed = bar is None or record["b"]["macro_f1"] >= bar - B_TOLERANCE
    record["verdict"] = "accept" if passed else "reject"
    if not passed:
        record["reject_gate"] = "b_regression"
    append_ledger(ledger, record)

    if passed:
        write_verdict(iteration, "accept", "the hidden validation gate passed")
        print(f"ACCEPT: A macro-F1 {scored['a']['macro_f1']:.3f}")
        return EXIT_ACCEPT

    write_verdict(
        iteration,
        "reject",
        "the hidden validation split regressed; the edit helped set A and "
        "hurt data you cannot see",
    )
    print(f"REJECT: hidden validation gate. A macro-F1 {scored['a']['macro_f1']:.3f}")
    return EXIT_REJECT_B


def main() -> int:
    """Parse arguments and run.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mode", choices=["baseline", "check"], required=True)
    parser.add_argument(
        "--ledger",
        default=None,
        help="hidden-score ledger path; MUST be outside the worktree",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="zero-API deterministic mock scoring (no key needed)",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--split-ratio", type=float, default=DEFAULT_SPLIT_RATIO)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
