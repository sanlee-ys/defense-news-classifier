"""Offline tests for the L4 multi-agent pipeline (no API key, no network).

What gets pinned: the fail-closed challenge gate, the bounce cap (exactly one
re-classify, ever), every terminal status reachable, the shipped classifier
untouched, the audit trail complete, and resume behavior.
"""

import json

import pandas as pd
import pytest

import l4_pipeline
from classify import SYSTEM_PROMPT
from l4_pipeline import (
    DryRunBackend,
    challenge_violations,
    process_row,
    reviewer_note,
    run_pipeline,
)

ACCEPT_TEXT = "A ship deployed to the Pacific for exercises."
FIX_TEXT = "A U.S. Navy ship departed for a routine deployment."  # no place token
CONTESTED_TEXT = "A stubborn U.S. Navy ship departed on deployment."
FAIL_CLOSED_TEXT = "A vague U.S. Navy ship departed on deployment."


def test_valid_challenge_passes_the_gate():
    review = {
        "verdict": "challenge",
        "axis": "region",
        "rubric_rule": "Do not guess a region when no place is named.",
        "evidence_gap": "The snippet states no location at all.",
    }
    assert challenge_violations(review) == []
    note = reviewer_note(review)
    assert "region" in note and "no location" in note


@pytest.mark.parametrize(
    "review",
    [
        {"verdict": "challenge"},
        {
            "verdict": "challenge",
            "axis": "region",
            "rubric_rule": "short",
            "evidence_gap": "x",
        },
        {
            "verdict": "challenge",
            "axis": "vibes",
            "rubric_rule": "a rule that is long enough",
            "evidence_gap": "a gap that is long enough",
        },
    ],
)
def test_invalid_challenges_are_caught(review):
    assert challenge_violations(review) != []


def test_accept_needs_no_justification():
    assert challenge_violations({"verdict": "accept"}) == []


def test_accept_path():
    label, events, calls = process_row(DryRunBackend(), ACCEPT_TEXT)
    assert label["l4_status"] == "accepted"
    assert calls == 3
    assert [e["event"] for e in events] == ["triage", "classify", "critic"]


def test_challenge_fixed_path_bounces_exactly_once():
    label, events, calls = process_row(DryRunBackend(), FIX_TEXT)
    assert label["l4_status"] == "fixed"
    assert label["region"] == "global"  # the bounce heeded the note
    assert calls == 5
    names = [e["event"] for e in events]
    assert names == ["triage", "classify", "critic", "reclassify", "critic_second"]
    assert names.count("reclassify") == 1  # the bounce cap, literally


def test_contested_path_keeps_reclassified_label_and_stops():
    label, events, calls = process_row(DryRunBackend(), CONTESTED_TEXT)
    assert label["l4_status"] == "contested"
    names = [e["event"] for e in events]
    assert names.count("reclassify") == 1  # a second challenge never loops
    assert calls == 5


def test_invalid_challenge_fails_closed():
    label, events, calls = process_row(DryRunBackend(), FAIL_CLOSED_TEXT)
    assert label["l4_status"] == "fail_closed"
    assert label["region"] == "americas"  # the original label stands
    assert calls == 3  # no bounce was spent on an unsupported challenge
    assert events[-1]["event"] == "challenge_discarded"
    assert events[-1]["violations"]


def test_shipped_classifier_is_untouched():
    # L4 must never modify the production call's module state; the prompt the
    # backend appends to is the same object classify.py ships.
    import classify

    assert classify.SYSTEM_PROMPT is SYSTEM_PROMPT


def test_dry_run_pipeline_gold_end_to_end(tmp_path, monkeypatch):
    out = str(tmp_path / "gold_preds.csv")
    audit = str(tmp_path / "audit.jsonl")
    monkeypatch.setitem(l4_pipeline.RUN_PATHS, "gold", out)
    result = run_pipeline("gold", DryRunBackend(), audit_path=audit)
    assert result == out
    preds = pd.read_csv(out)
    assert len(preds) == 54
    assert set(preds.columns) == {
        "id",
        "pred_category",
        "pred_operational_domain",
        "pred_region",
        "l4_status",
        "calls",
    }
    assert set(preds["l4_status"]) <= {"accepted", "fixed", "contested", "fail_closed"}
    # Audit trail: one line per row, ids match, events non-empty.
    with open(audit, encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh]
    assert len(records) == 54
    assert set(r["id"] for r in records) == set(preds["id"])
    assert all(r["events"] for r in records)
    # Resume: a second run has nothing to do and appends nothing.
    run_pipeline("gold", DryRunBackend(), audit_path=audit)
    assert len(pd.read_csv(out)) == 54


def test_report_builds_without_runs(tmp_path, monkeypatch):
    monkeypatch.setitem(l4_pipeline.RUN_PATHS, "gold", str(tmp_path / "g.csv"))
    monkeypatch.setitem(l4_pipeline.RUN_PATHS, "scale", str(tmp_path / "s.csv"))
    monkeypatch.setattr(l4_pipeline, "REPORT_PATH", str(tmp_path / "r.txt"))
    report = l4_pipeline.build_report()
    assert "not yet made" in report


def test_critic_prompt_embeds_the_live_region_rubric():
    # The charter must carry the shipped rubric verbatim (never retyped); if
    # the prompt's region block changes, the critic's copy moves with it.
    from optimize import extract_region_block

    block = extract_region_block(SYSTEM_PROMPT)
    assert block and block in l4_pipeline.CRITIC_SYSTEM_PROMPT
