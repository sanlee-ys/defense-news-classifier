import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import morning_review as mr  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture builders: a minimal ledger record, and a run log written to disk.
# ---------------------------------------------------------------------------


def _record(kind, iteration, verdict, a, b, c, tokens=100, reject_gate=None):
    record = {
        "kind": kind,
        "iteration": iteration,
        "timestamp": "2026-08-20T00:00:00+00:00",
        "verdict": verdict,
        "a": {"macro_f1": a},
        "b": {"macro_f1": b},
        "c": {"macro_f1": c},
        "tokens": tokens,
    }
    if reject_gate is not None:
        record["reject_gate"] = reject_gate
    return record


def _write_log(tmp_path, records) -> Path:
    path = tmp_path / "run.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _git(worktree, *args):
    subprocess.run(["git", "-C", str(worktree), *args], check=True, capture_output=True)


def _make_worktree(tmp_path, blast_radius=("src/classify.py", "loop/state/")):
    """Build a throwaway git repo shaped like the loop's own worktree."""
    root = tmp_path / "worktree"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    (root / "src").mkdir()
    (root / "src" / "classify.py").write_text("PROMPT = 'v0'\n", encoding="utf-8")
    (root / "loop").mkdir()
    (root / "loop" / "blast-radius.txt").write_text(
        "\n".join(blast_radius) + "\n", encoding="utf-8"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    # Real loop runs commit on their own branch, diverging from main (README:
    # `git worktree add ../dnc-loop -b loop/prompt-optimize`). Mirror that so
    # a scope diff against `main` sees the run's commits, not an empty range.
    _git(root, "checkout", "-q", "-b", "loop/prompt-optimize")
    return root


def _accept_commit(worktree, path_within, content):
    """Commit a change to one file, as the loop itself would."""
    target = worktree / path_within
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", f"loop(iter): touched {path_within}")


# ---------------------------------------------------------------------------
# SHIPPED
# ---------------------------------------------------------------------------


def test_shipped_requires_a_real_stop_signal_and_b_improvement(tmp_path):
    records = [
        _record("baseline", 0, "baseline", 0.70, 0.70, 0.90),
        _record("iteration", 1, "accept", 0.80, 0.80, 0.90),
    ]
    log = _write_log(tmp_path, records)
    worktree = _make_worktree(tmp_path)
    (worktree / "loop" / "state").mkdir(parents=True, exist_ok=True)
    (worktree / "loop" / "state" / "status.md").write_text(
        "LOOP-COMPLETE: iteration 1\n", encoding="utf-8"
    )
    _accept_commit(worktree, "src/classify.py", "PROMPT = 'v1'\n")

    review = mr.review_run(log, worktree)

    assert review.verdict == mr.SHIPPED
    assert review.exit_code == 0
    assert review.done_signal == "threshold"
    assert review.b_improved
    assert review.goodhart_ok


# ---------------------------------------------------------------------------
# PARTIAL
# ---------------------------------------------------------------------------


def test_partial_when_b_improves_but_the_run_ends_on_a_resource_cap(tmp_path):
    records = [
        _record("baseline", 0, "baseline", 0.70, 0.70, 0.90),
        _record("iteration", 1, "accept", 0.80, 0.80, 0.90),
    ]
    log = _write_log(tmp_path, records)

    review = mr.review_run(log, worktree=None)

    assert review.verdict == mr.PARTIAL
    assert review.exit_code == 1
    assert review.done_signal == "budget_or_iteration_cap"
    assert review.b_improved


def test_partial_when_c_degrades_past_tolerance_despite_a_clean_signal(tmp_path):
    records = [
        _record("baseline", 0, "baseline", 0.70, 0.70, 0.90),
        _record("iteration", 1, "accept", 0.80, 0.80, 0.85),  # C down 0.05
    ]
    log = _write_log(tmp_path, records)
    worktree = _make_worktree(tmp_path)
    (worktree / "loop" / "state").mkdir(parents=True, exist_ok=True)
    (worktree / "loop" / "state" / "status.md").write_text(
        "LOOP-COMPLETE: iteration 1\n", encoding="utf-8"
    )
    _accept_commit(worktree, "src/classify.py", "PROMPT = 'v1'\n")

    review = mr.review_run(log, worktree, c_tolerance=0.004)

    assert review.verdict == mr.PARTIAL
    assert review.b_improved
    assert not review.goodhart_ok


# ---------------------------------------------------------------------------
# STUCK
# ---------------------------------------------------------------------------


def test_stuck_when_every_iteration_is_rejected(tmp_path):
    records = [
        _record("baseline", 0, "baseline", 0.70, 0.70, 0.90),
        _record("iteration", 1, "reject", 0.60, 0.60, 0.90, reject_gate="b_regression"),
        _record("iteration", 2, "reject", 0.65, 0.65, 0.90, reject_gate="b_regression"),
    ]
    log = _write_log(tmp_path, records)

    review = mr.review_run(log, worktree=None)

    assert review.verdict == mr.STUCK
    assert review.exit_code == 2
    assert not review.b_improved


def test_stuck_when_accepted_iterations_never_beat_baseline_b(tmp_path):
    # An accepted iteration can only ever equal or exceed the running bar
    # (that is the ratchet loop_metrics.py enforces), but a synthetic log
    # standing in for a malformed/adversarial ledger should still be read
    # as STUCK if, taken at face value, B never rises above baseline.
    records = [
        _record("baseline", 0, "baseline", 0.70, 0.70, 0.90),
        _record("iteration", 1, "accept", 0.70, 0.70, 0.90),
    ]
    log = _write_log(tmp_path, records)

    review = mr.review_run(log, worktree=None)

    assert review.verdict == mr.STUCK


# ---------------------------------------------------------------------------
# DRIFTED
# ---------------------------------------------------------------------------


def test_drifted_on_a_malformed_log_missing_baseline(tmp_path):
    records = [_record("iteration", 1, "accept", 0.8, 0.8, 0.9)]
    log = _write_log(tmp_path, records)

    review = mr.review_run(log, worktree=None)

    assert review.verdict == mr.DRIFTED
    assert review.exit_code == 3
    assert any("baseline" in r for r in review.malformed)


def test_drifted_on_a_non_contiguous_iteration_sequence(tmp_path):
    records = [
        _record("baseline", 0, "baseline", 0.70, 0.70, 0.90),
        _record("iteration", 1, "accept", 0.80, 0.80, 0.90),
        _record("iteration", 3, "accept", 0.85, 0.85, 0.90),  # skipped 2
    ]
    log = _write_log(tmp_path, records)

    review = mr.review_run(log, worktree=None)

    assert review.verdict == mr.DRIFTED
    assert any("non-contiguous" in r for r in review.malformed)


def test_drifted_on_invalid_json_line(tmp_path):
    log = tmp_path / "run.jsonl"
    log.write_text(
        json.dumps(_record("baseline", 0, "baseline", 0.70, 0.70, 0.90))
        + "\n{not json\n",
        encoding="utf-8",
    )

    review = mr.review_run(log, worktree=None)

    assert review.verdict == mr.DRIFTED
    assert any("invalid JSON" in r for r in review.malformed)


def test_drifted_on_a_scope_violation_outside_the_blast_radius(tmp_path):
    records = [
        _record("baseline", 0, "baseline", 0.70, 0.70, 0.90),
        _record("iteration", 1, "accept", 0.80, 0.80, 0.90),
    ]
    log = _write_log(tmp_path, records)
    worktree = _make_worktree(tmp_path)
    # A file outside loop/blast-radius.txt (src/classify.py, loop/state/).
    _accept_commit(worktree, "src/optimize.py", "TOUCHED = True\n")

    review = mr.review_run(log, worktree)

    assert review.verdict == mr.DRIFTED
    assert review.scope.violation
    assert "src/optimize.py" in review.scope.detail


def test_drifted_when_a_stuck_halt_is_claimed_without_matching_evidence(tmp_path):
    # stuck.json claims a 3-identical-failure halt, but the log's last 3
    # iterations are not three identical rejects -- the claim does not match
    # the ledger, so it is drift, not a trusted plateau.
    records = [
        _record("baseline", 0, "baseline", 0.70, 0.70, 0.90),
        _record("iteration", 1, "reject", 0.60, 0.60, 0.90, reject_gate="b_regression"),
        _record("iteration", 2, "reject", 0.60, 0.60, 0.90, reject_gate="b_regression"),
        _record("iteration", 3, "accept", 0.72, 0.72, 0.90),
    ]
    log = _write_log(tmp_path, records)
    worktree = _make_worktree(tmp_path)
    (worktree / "loop" / "state").mkdir(parents=True, exist_ok=True)
    (worktree / "loop" / "state" / "stuck.json").write_text(
        json.dumps({"iteration": 3, "gate": "b_regression"}), encoding="utf-8"
    )

    review = mr.review_run(log, worktree)

    assert review.verdict == mr.DRIFTED
    assert any("do not match" in r for r in review.reasons)


def test_drifted_when_both_threshold_and_plateau_are_claimed_at_once(tmp_path):
    records = [
        _record("baseline", 0, "baseline", 0.70, 0.70, 0.90),
        _record("iteration", 1, "accept", 0.80, 0.80, 0.90),
    ]
    log = _write_log(tmp_path, records)
    worktree = _make_worktree(tmp_path)
    (worktree / "loop" / "state").mkdir(parents=True, exist_ok=True)
    (worktree / "loop" / "state" / "status.md").write_text(
        "LOOP-COMPLETE: iteration 1\n", encoding="utf-8"
    )
    (worktree / "loop" / "state" / "stuck.json").write_text(
        json.dumps({"iteration": 1, "gate": "b_regression"}), encoding="utf-8"
    )

    review = mr.review_run(log, worktree)

    assert review.verdict == mr.DRIFTED


# ---------------------------------------------------------------------------
# The rubric's own internal contracts.
# ---------------------------------------------------------------------------


def test_exit_codes_are_distinct_and_match_the_documented_contract():
    assert mr.EXIT_CODES == {
        mr.SHIPPED: 0,
        mr.PARTIAL: 1,
        mr.STUCK: 2,
        mr.DRIFTED: 3,
    }


def test_best_by_b_ignores_rejected_iterations_like_loop_metrics_does():
    iterations = [
        mr.Iteration("baseline", 0, "baseline", None, 0.70, 0.70, 0.90, 0),
        mr.Iteration("iteration", 1, "accept", None, 0.75, 0.75, 0.90, 0),
        mr.Iteration("iteration", 2, "reject", "b_regression", 0.99, 0.99, 0.90, 0),
    ]
    assert mr._best_by_b(iterations).b == 0.75


def test_best_by_b_breaks_ties_on_the_later_iteration():
    iterations = [
        mr.Iteration("baseline", 0, "baseline", None, 0.70, 0.70, 0.90, 0),
        mr.Iteration("iteration", 1, "accept", None, 0.70, 0.80, 0.90, 0),
        mr.Iteration("iteration", 2, "accept", None, 0.70, 0.80, 0.90, 0),
    ]
    assert mr._best_by_b(iterations).iteration == 2


def test_scope_check_is_unchecked_not_clean_without_a_worktree():
    scope = mr.check_scope(None, "main")
    assert not scope.checked
    assert not scope.violation


def test_cli_exit_code_round_trips_through_main(tmp_path, capsys):
    records = [
        _record("baseline", 0, "baseline", 0.70, 0.70, 0.90),
        _record("iteration", 1, "reject", 0.60, 0.60, 0.90, reject_gate="b_regression"),
    ]
    log = _write_log(tmp_path, records)

    code = mr.main([str(log), "--json"])

    assert code == mr.EXIT_CODES[mr.STUCK]
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "STUCK"
