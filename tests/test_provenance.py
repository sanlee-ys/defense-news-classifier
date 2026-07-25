"""The predictions snapshot must stay pinned to the prompt that produced it.

`evals/gold_predictions_v3.csv` is a frozen record of a paid live run, and
`scripts/gen_metrics_artifact.py` publishes it under whatever version
`pyproject.toml` currently says. Nothing used to connect the two, so editing
`classify.SYSTEM_PROMPT` and bumping the version — without paying for a gold re-run
— would publish the OLD prompt's predictions as the NEW version's numbers, with
`--check` green the whole way.

These cover the pure decision logic. The live pairing itself is asserted in
tests/test_metrics_artifact.py, where a real prompt edit turns CI red.
"""

from __future__ import annotations

import json

import pytest

import provenance

WORKHORSE = "claude-sonnet-5"
JUDGE = "claude-opus-4-8"


def _fp(prompt="a prompt", workhorse=WORKHORSE, judge=JUDGE):
    return provenance.fingerprint(prompt, workhorse, judge)


def _record(recorded=None, waiver=None):
    record = {"predictions": "evals/x.csv", "recorded": recorded or _fp()}
    if waiver is not None:
        record["waiver"] = waiver
    return record


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_is_deterministic():
    """Two callers hashing the same run must agree, or the guard is noise."""
    assert _fp() == _fp()


def test_fingerprint_is_a_full_sha256_of_the_prompt_bytes():
    """Pinned to the documented algorithm so the recorded value stays reproducible."""
    import hashlib

    expected = hashlib.sha256(b"a prompt").hexdigest()
    assert _fp()["prompt_sha256"] == expected
    assert len(expected) == 64


def test_a_one_character_prompt_edit_changes_the_digest():
    """The whole point: an edited prompt must not fingerprint as the old one."""
    assert _fp("a prompt")["prompt_sha256"] != _fp("a prompt.")["prompt_sha256"]


def test_models_are_part_of_the_identity():
    """A model swap invalidates a snapshot as thoroughly as a prompt edit."""
    assert _fp(workhorse="claude-sonnet-6") != _fp()
    assert _fp(judge="claude-opus-5") != _fp()


# ---------------------------------------------------------------------------
# divergences
# ---------------------------------------------------------------------------


def test_no_divergences_when_the_run_matches_the_code():
    assert provenance.divergences(_fp(), _fp()) == []


def test_divergence_names_the_field_and_shows_both_sides():
    """A guard that only says 'mismatch' makes the reader go digging."""
    [line] = provenance.divergences(_fp(), _fp(workhorse="claude-sonnet-6"))
    assert "workhorse_model" in line
    assert WORKHORSE in line and "claude-sonnet-6" in line


def test_every_changed_field_is_reported_not_just_the_first():
    """Fixing one field only to be told about the next is a bad failure loop."""
    drift = provenance.divergences(_fp(), _fp("other", "m1", "m2"))
    assert len(drift) == 3


# ---------------------------------------------------------------------------
# check — the publish/refuse decision
# ---------------------------------------------------------------------------


def test_matching_fingerprints_publish_silently():
    ok, message = provenance.check(_record(), _fp())
    assert ok and message == ""


def test_a_changed_prompt_blocks_publication():
    ok, message = provenance.check(_record(), _fp("edited prompt"))
    assert not ok
    assert "STALE SNAPSHOT" in message


def test_the_failure_names_both_remedies():
    """'Re-run the eval, or explain why the snapshot stands' — both must be findable."""
    _, message = provenance.check(_record(), _fp("edited prompt"))
    assert "src/gold_eval.py" in message
    assert "waiver" in message


def test_a_waiver_accepting_this_exact_fingerprint_publishes():
    live = _fp("edited prompt")
    record = _record(waiver={"accepts": live, "reason": "comment-only reword"})
    ok, message = provenance.check(record, live)
    assert ok
    assert "WAIVED" in message and "comment-only reword" in message


def test_a_waiver_without_a_reason_is_not_a_waiver():
    """An unexplained waiver is the silent laundering this guard exists to stop."""
    live = _fp("edited prompt")
    ok, _ = provenance.check(_record(waiver={"accepts": live}), live)
    assert not ok


def test_a_whitespace_only_reason_is_not_a_reason():
    live = _fp("edited prompt")
    record = _record(waiver={"accepts": live, "reason": "   "})
    ok, _ = provenance.check(record, live)
    assert not ok


def test_a_waiver_expires_when_the_prompt_moves_again():
    """It must name a specific fingerprint, so it can never be a standing skip."""
    record = _record(waiver={"accepts": _fp("first edit"), "reason": "reviewed"})
    ok, _ = provenance.check(record, _fp("second edit"))
    assert not ok


def test_an_empty_waiver_block_cannot_wave_anything_through():
    ok, _ = provenance.check(_record(waiver={}), _fp("edited prompt"))
    assert not ok


# ---------------------------------------------------------------------------
# load / write round trip
# ---------------------------------------------------------------------------


def test_write_then_load_round_trips(tmp_path):
    path = str(tmp_path / "p.json")
    fp = _fp()
    provenance.write(fp, "evals/x.csv", path=path)
    record = provenance.load(path)
    assert record["recorded"] == fp
    assert record["predictions"] == "evals/x.csv"


def test_the_written_file_says_it_is_generated(tmp_path):
    """A hand-edit is how this drifts; say so in the file itself."""
    path = str(tmp_path / "p.json")
    provenance.write(_fp(), "evals/x.csv", path=path)
    assert (
        "do not hand-edit"
        in json.loads(open(path, encoding="utf-8").read())["$comment"]
    )


def test_a_missing_record_raises_rather_than_defaulting_to_ok(tmp_path):
    """An unknown pairing must never read as a verified one."""
    with pytest.raises(FileNotFoundError) as excinfo:
        provenance.load(str(tmp_path / "absent.json"))
    assert "gold_eval.py" in str(excinfo.value)
