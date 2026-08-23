"""Tests for the loop-candidate powered A/B harness."""

import hashlib
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import loop_candidate_eval as lce  # noqa: E402
import paired_compare  # noqa: E402
import region_clause_rerun as rerun  # noqa: E402
from classify import SYSTEM_PROMPT  # noqa: E402

# ---------------------------------------------------------------------------
# Composition and identity. The digest pin is what turns "the clauses, as
# extracted from a diff" into "the classifier the loop measured".
# ---------------------------------------------------------------------------


def test_candidate_prompt_reproduces_the_loop_arm():
    live = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    if live != rerun.ADR023_CANDIDATE_PROMPT_SHA256:
        pytest.skip(
            "the shipped prompt has moved past v3.2.1; the harness's runtime "
            "guards refuse on their own, and this experiment must be re-derived"
        )
    composed = hashlib.sha256(lce.candidate_prompt().encode("utf-8")).hexdigest()
    assert composed == lce.LOOP_CANDIDATE_PROMPT_SHA256
    # The pin must never be satisfied trivially: the candidate is a different
    # classifier than the one that ships.
    assert composed != live


def test_shipped_prompt_does_not_carry_the_clauses():
    # The clauses live only in the composed candidate until an adoption ADR
    # deliberately moves them. If this fails, the experiment is over and the
    # harness's not-shipped guard refuses everything anyway.
    assert lce.PROC_TECH_CLAUSE not in SYSTEM_PROMPT
    assert lce.INDUSTRY_TECH_CLAUSE not in SYSTEM_PROMPT


def test_apply_clauses_refuses_double_application():
    with pytest.raises(ValueError, match="already carries"):
        lce.apply_clauses(lce.candidate_prompt())


def test_apply_clauses_refuses_a_missing_anchor():
    with pytest.raises(ValueError, match="exactly once"):
        lce.apply_clauses("a prompt with no anchors in it")


def test_prompt_carries_the_clauses_guard_rejects_the_shipped_prompt():
    with pytest.raises(ValueError, match="does not carry both clauses"):
        lce.assert_prompt_carries_the_clauses(SYSTEM_PROMPT)


def test_new_artifacts_do_not_collide_with_frozen_gold_records():
    # The gold write guard must accept this experiment's destinations; a
    # refusal here would mean a path constant collided with a frozen record.
    rerun.assert_writable_gold_artifact(lce.GOLD_CANDIDATE_PATH)
    rerun.assert_writable_gold_artifact(lce.GOLD_CANDIDATE_PROVENANCE_PATH)
    rerun.assert_writable_gold_artifact(lce.GOLD_REPORT_PATH)


# ---------------------------------------------------------------------------
# The sentinel runner. Run 2 hit six max_tokens truncations; one uncaught row
# aborted a paid scoring pass (the bug PR #189 fixed in optimize.py). The
# runners here must record ADR-021 sentinels and keep going.
# ---------------------------------------------------------------------------


def test_run_sync_sentinels_truncated_refused_and_invalid_rows(
    tmp_path, monkeypatch, capsys
):
    def flaky_classify_retry(client, text, model, system_prompt=None):
        if text == "cut off":
            raise lce.IncompleteResponseError("stop_reason='max_tokens'")
        if text == "declined":
            raise lce.ClassificationRefusalError("model declined")
        if text == "bad label":
            raise lce.InvalidLabelError("category 'cyber' is not one of [...]")
        return {"category": "policy", "operational_domain": "air", "region": "europe"}

    monkeypatch.setattr(lce, "classify_retry", flaky_classify_retry)
    monkeypatch.setattr(lce.time, "sleep", lambda _s: None)

    df = pd.DataFrame(
        [
            {"id": "s1", "text": "fine"},
            {"id": "s2", "text": "cut off"},
            {"id": "s3", "text": "declined"},
            {"id": "s4", "text": "bad label"},
        ]
    )
    preds = tmp_path / "candidate.csv"
    lce._run_sync(client=object(), todo=df, prompt="P", preds_path=str(preds))

    written = pd.read_csv(preds).set_index("id")
    assert written.loc["s1", "pred_category"] == "policy"
    assert written.loc["s2", "pred_category"] == paired_compare.INCOMPLETE
    assert written.loc["s3", "pred_category"] == paired_compare.REFUSED
    assert written.loc["s4", "pred_category"] == paired_compare.UNCLASSIFIED
    # Every row landed: a harness failure is recorded, never a hole.
    assert len(written) == 4

    out = capsys.readouterr().out
    assert "__incomplete__" in out
    assert "__refused__" in out


def test_sentinel_rows_pair_as_errored_not_as_misses():
    # End to end through paired_compare: a sentinel row must be excluded from
    # the eligible pairs (diagnosed as errored), never scored right-or-wrong.
    baseline = pd.DataFrame(
        [
            {"id": "s1", "judge_category": "policy", "pred_category": "policy"},
            {"id": "s2", "judge_category": "policy", "pred_category": "policy"},
        ]
    ).astype(str)
    candidate = pd.DataFrame(
        [
            {"id": "s1", "pred_category": "policy"},
            {"id": "s2", "pred_category": paired_compare.INCOMPLETE},
        ]
    ).astype(str)
    import region_clause_ab as ab

    result, lift = ab.axis_comparison(baseline, candidate, "category", "judge_category")
    assert lift.eligible_pairs == 1
    counts = paired_compare.diagnostic_counts(result.diagnostics)
    assert sum(v for k, v in counts.items() if "error" in k) == 1
