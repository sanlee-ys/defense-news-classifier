"""Tests for src/region_clause_ab.py (the `global`-boundary clause A/B harness).

Offline only, and deliberately so: this module exists to make a 300-call experiment
decidable, and every part of it except the owner-driven `--run` pass must be verifiable
without a key. The two live-path tests drive conftest's fake clients.

The tests that matter most are the guard tests. The scoring code is arithmetic and would
fail loudly if it were wrong; the guards defend against the failure mode that produces a
*well-formed report of nothing* -- two arms sharing a prompt, a moved model, a holed
answer key. Those are the ways this experiment could hand back a confident wrong answer.
"""

import json

import pandas as pd
import pytest

import gold_eval
import paired_compare
import provenance
import region_clause_ab as ab

CATS = ["operations", "technology", "procurement", "policy", "industry"]
DOMS = ["air", "land", "sea", "cyber", "multi", "space"]


def _baseline(n: int = 20, pulls: int = 5, over_calls: int = 2) -> pd.DataFrame:
    """A baseline arm reproducing the ADR-022 shape at a testable size.

    Rows ``0..pulls-1``      : judge=global, workhorse=americas  (the named cluster)
    Rows ``pulls..+over-1``  : judge=europe, workhorse=global     (the converse)
    The rest                 : both arms agree on every axis.
    """
    rows = []
    for i in range(n):
        if i < pulls:
            judge, pred = "global", "americas"
        elif i < pulls + over_calls:
            judge, pred = "europe", "global"
        else:
            judge = pred = "indo-pacific"
        rows.append(
            {
                "id": f"s{i:03d}",
                "pred_category": CATS[i % len(CATS)],
                "pred_operational_domain": DOMS[i % len(DOMS)],
                "pred_region": pred,
                "judge_category": CATS[i % len(CATS)],
                "judge_operational_domain": DOMS[i % len(DOMS)],
                "judge_region": judge,
            }
        )
    return pd.DataFrame(rows)


def _candidate(baseline: pd.DataFrame, fixed: int = 0, new_over: int = 0):
    """The candidate arm: `fixed` named pulls corrected, `new_over` fresh over-calls.

    New over-calls are taken from the tail (rows where both arms agreed), which is
    exactly the shape of the risk -- a clause buying its fixes by dragging correct
    specific-region rows to ``global``.
    """
    candidate = baseline[
        ["id", "pred_category", "pred_operational_domain", "pred_region"]
    ].copy()
    named = list(
        baseline[
            (baseline["judge_region"] == "global")
            & (baseline["pred_region"] != "global")
        ]["id"]
    )
    for row_id in named[:fixed]:
        candidate.loc[candidate["id"] == row_id, "pred_region"] = "global"
    agreeing = list(baseline[baseline["pred_region"] == baseline["judge_region"]]["id"])
    for row_id in agreeing[:new_over]:
        candidate.loc[candidate["id"] == row_id, "pred_region"] = "global"
    return candidate


def _scale_set(baseline: pd.DataFrame, duplicates: dict | None = None):
    """A scale set matching `baseline`'s ids; `duplicates` maps id -> id-to-copy-text."""
    rows = [{"id": i, "text": f"snippet for {i}"} for i in baseline["id"]]
    for target, source in (duplicates or {}).items():
        src = next(r["text"] for r in rows if r["id"] == source)
        for row in rows:
            if row["id"] == target:
                row["text"] = src
    return pd.DataFrame(rows)


def _sidecars(tmp_path, monkeypatch, baseline_prompt="old", candidate_prompt=None):
    """Write both arms' provenance sidecars and point the module at them.

    The candidate defaults to the LIVE prompt so `assert_candidate_matches_the_live_prompt`
    passes; pass an explicit string to exercise the failure paths.
    """
    base = tmp_path / "baseline.provenance.json"
    cand = tmp_path / "candidate.provenance.json"
    provenance.write(
        provenance.fingerprint(
            baseline_prompt, gold_eval.WORKHORSE_MODEL, gold_eval.JUDGE_MODEL
        ),
        "evals/baseline.csv",
        path=str(base),
    )
    provenance.write(
        provenance.fingerprint(
            candidate_prompt if candidate_prompt is not None else ab.SYSTEM_PROMPT,
            gold_eval.WORKHORSE_MODEL,
            gold_eval.JUDGE_MODEL,
        ),
        "evals/candidate.csv",
        path=str(cand),
    )
    monkeypatch.setattr(ab, "BASELINE_PROVENANCE_PATH", str(base))
    monkeypatch.setattr(ab, "CANDIDATE_PROVENANCE_PATH", str(cand))
    return base, cand


def _roundtrip(frame: pd.DataFrame, path):
    """Write then re-read through the production loader.

    Tests that hand a frame straight to a guard cannot catch a defect that only exists
    after a CSV round trip -- which is exactly how the blank-cell check was dead on the
    production path (bare read_csv turns "" into NaN).
    """
    frame.to_csv(path, index=False)
    return paired_compare.read_predictions(str(path))


# ---------------------------------------------------------------------------
# The claim the whole 300-call saving rests on: the judge never sees the
# workhorse's answer, so its labels are invariant to the workhorse's prompt.
# ---------------------------------------------------------------------------


def test_judge_is_classified_from_the_snippet_alone(monkeypatch, tmp_path):
    """The judge call must receive the raw text, never the workhorse's prediction.

    If this ever stopped holding, reusing the stored judge column as a frozen answer
    key would be invalid and the candidate arm would owe 300 more calls. It is asserted
    here rather than assumed because it is the load-bearing premise of the design.
    """
    seen = []

    def _fake(_client, text, model, **_kwargs):
        seen.append((model, text))
        return {
            "category": "operations",
            "operational_domain": "air",
            "region": "global",
        }

    monkeypatch.setattr(gold_eval, "classify_retry", _fake)
    monkeypatch.setattr(gold_eval, "SLEEP_BETWEEN_CALLS", 0)
    frame = pd.DataFrame([{"id": "s001", "text": "a snippet"}])
    gold_eval.run_predictions(None, frame, set(), preds_path=str(tmp_path / "p.csv"))

    assert len(seen) == 2
    models = {model for model, _ in seen}
    assert models == {gold_eval.WORKHORSE_MODEL, gold_eval.JUDGE_MODEL}
    # Both calls carry the identical snippet and nothing else.
    assert {text for _, text in seen} == {"a snippet"}


def test_judge_is_snippet_only_on_the_BATCH_path_too(tmp_path, batch_client):
    """The protocol uses --batch, so the batch path is the one that must be pinned.

    The synchronous assertion above covers a path the run protocol does not take. Both
    are asserted, because "the tested path is not the used path" is exactly how a
    load-bearing premise quietly stops holding.
    """
    payload = {
        "category": "operations",
        "operational_domain": "air",
        "region": "global",
    }
    frame = pd.DataFrame([{"id": "s001", "text": "the only text there is"}])
    client = batch_client(
        {"s001__workhorse": payload, "s001__judge": payload},
    )
    gold_eval.run_predictions_batch(
        client, frame, set(), poll_interval=0, preds_path=str(tmp_path / "p.csv")
    )

    requests = client.messages.batches.created_requests
    assert len(requests) == 2  # one workhorse, one judge
    models = {r["params"]["model"] for r in requests}
    assert models == {gold_eval.WORKHORSE_MODEL, gold_eval.JUDGE_MODEL}
    # Every request's user content is the raw snippet: no prediction rides along.
    for request in requests:
        content = request["params"]["messages"][0]["content"]
        assert content == "the only text there is"


# ---------------------------------------------------------------------------
# Guards.
# ---------------------------------------------------------------------------


def test_arms_differ_accepts_a_clean_prompt_contrast():
    ab.assert_arms_differ(
        provenance.fingerprint("old", "sonnet", "opus"),
        provenance.fingerprint("new", "sonnet", "opus"),
    )


def test_arms_differ_refuses_two_arms_sharing_one_prompt():
    same = provenance.fingerprint("identical", "sonnet", "opus")
    with pytest.raises(ValueError, match="SAME prompt"):
        ab.assert_arms_differ(same, dict(same))


def test_arms_differ_refuses_a_confounded_model_swap():
    with pytest.raises(ValueError, match="workhorse_model"):
        ab.assert_arms_differ(
            provenance.fingerprint("old", "sonnet", "opus"),
            provenance.fingerprint("new", "sonnet-next", "opus"),
        )


def test_arms_differ_refuses_a_judge_swap():
    with pytest.raises(ValueError, match="judge_model"):
        ab.assert_arms_differ(
            provenance.fingerprint("old", "sonnet", "opus"),
            provenance.fingerprint("new", "sonnet", "opus-next"),
        )


def test_answer_key_guard_accepts_the_committed_shape():
    base = _baseline()
    ab.assert_answer_key_is_complete(base, _scale_set(base))


def test_answer_key_guard_rejects_a_missing_judge_column():
    base = _baseline()
    frame = base.drop(columns=["judge_region"])
    with pytest.raises(ValueError, match="judge_region"):
        ab.assert_answer_key_is_complete(frame, _scale_set(base))


def test_answer_key_guard_rejects_a_hand_made_subset(tmp_path):
    """The defect this replaced: a 5-row hand-assembled key used to pass."""
    base = _baseline(n=20)
    subset = base.head(5)
    with pytest.raises(ValueError, match="not the committed scale set"):
        ab.assert_answer_key_is_complete(subset, _scale_set(base))


def test_answer_key_guard_rejects_duplicate_ids():
    base = _baseline(n=20)
    doubled = pd.concat([base, base.head(1)], ignore_index=True)
    with pytest.raises(ValueError, match="repeats"):
        ab.assert_answer_key_is_complete(doubled, _scale_set(doubled))


def test_answer_key_guard_rejects_holes_after_a_csv_round_trip(tmp_path):
    """A blank cell must still be blank after the production loader sees it.

    Round-tripped on purpose: a bare read_csv turns "" into NaN, and the old blank
    check compared "nan" against "", so it could never fire in production.
    """
    base = _baseline()
    base.loc[0, "judge_region"] = ""
    loaded = _roundtrip(base, tmp_path / "baseline.csv")
    with pytest.raises(ValueError, match="blank"):
        ab.assert_answer_key_is_complete(loaded, _scale_set(base))


def test_bare_read_csv_would_have_hidden_the_hole(tmp_path):
    """Pins the mechanism, so a future refactor back to read_csv fails here."""
    base = _baseline()
    base.loc[0, "judge_region"] = ""
    base.to_csv(tmp_path / "b.csv", index=False)
    naive = pd.read_csv(tmp_path / "b.csv")
    assert str(naive.loc[0, "judge_region"]) == "nan"  # the defect, made visible
    assert (
        paired_compare.read_predictions(str(tmp_path / "b.csv")).loc[0, "judge_region"]
        == ""
    )


def test_candidate_completeness_guard_rejects_a_partial_arm():
    base = _baseline(n=20)
    partial = _candidate(base).head(15)
    with pytest.raises(ValueError, match="not complete"):
        ab.assert_candidate_is_complete(base, partial)


def test_candidate_completeness_guard_rejects_appended_duplicates():
    base = _baseline(n=20)
    cand = _candidate(base)
    doubled = pd.concat([cand, cand.head(1)], ignore_index=True)
    with pytest.raises(ValueError, match="repeats"):
        ab.assert_candidate_is_complete(base, doubled)


def test_candidate_completeness_guard_accepts_a_full_arm():
    base = _baseline(n=20)
    ab.assert_candidate_is_complete(base, _candidate(base))


def test_live_prompt_guard_accepts_the_working_tree():
    ab.assert_candidate_matches_the_live_prompt(
        provenance.fingerprint(
            ab.SYSTEM_PROMPT, gold_eval.WORKHORSE_MODEL, gold_eval.JUDGE_MODEL
        )
    )


def test_live_prompt_guard_rejects_a_third_prompt():
    """assert_arms_differ only proves the arms differ from EACH OTHER."""
    third = provenance.fingerprint(
        "some other prompt", gold_eval.WORKHORSE_MODEL, gold_eval.JUDGE_MODEL
    )
    ab.assert_arms_differ(
        provenance.fingerprint(
            "baseline", gold_eval.WORKHORSE_MODEL, gold_eval.JUDGE_MODEL
        ),
        third,
    )
    with pytest.raises(ValueError, match="not produced by the prompt/models on disk"):
        ab.assert_candidate_matches_the_live_prompt(third)


def test_resume_guard_allows_a_fresh_run():
    ab.assert_resume_is_honest(set(), provenance.fingerprint("p", "w", "j"))


def test_resume_guard_allows_a_matching_prompt(tmp_path, monkeypatch):
    path = tmp_path / "sidecar.json"
    live = provenance.fingerprint("p", "w", "j")
    provenance.write(live, "evals/x.csv", path=str(path))
    monkeypatch.setattr(ab, "CANDIDATE_PROVENANCE_PATH", str(path))
    ab.assert_resume_is_honest({"s001"}, live)


def test_resume_guard_refuses_to_blend_two_prompts(tmp_path, monkeypatch):
    path = tmp_path / "sidecar.json"
    provenance.write(
        provenance.fingerprint("old", "w", "j"), "evals/x.csv", path=str(path)
    )
    monkeypatch.setattr(ab, "CANDIDATE_PROVENANCE_PATH", str(path))
    with pytest.raises(ValueError, match="different prompt or model"):
        ab.assert_resume_is_honest({"s001"}, provenance.fingerprint("new", "w", "j"))


# ---------------------------------------------------------------------------
# The named cluster, both directions.
# ---------------------------------------------------------------------------


def test_named_pulls_are_derived_from_the_baseline_not_hardcoded():
    assert ab.named_pull_ids(_baseline(pulls=5)) == [
        "s000",
        "s001",
        "s002",
        "s003",
        "s004",
    ]
    assert ab.named_pull_ids(_baseline(pulls=0)) == []


def test_cluster_delta_counts_fixes_on_the_named_rows_only():
    base = _baseline(n=20, pulls=5, over_calls=2)
    delta = ab.cluster_delta(base, _candidate(base, fixed=3))
    assert delta["named_pulls"] == 5
    assert delta["named_fixed"] == 3
    assert delta["named_fixed_ids"] == ["s000", "s001", "s002"]
    assert delta["named_unfixed_ids"] == ["s003", "s004"]


def test_cluster_delta_reports_the_converse_over_calls_separately():
    base = _baseline(n=20, pulls=5, over_calls=2)
    delta = ab.cluster_delta(base, _candidate(base, fixed=5, new_over=4))
    # The two pre-existing over-calls survive; four correct rows were dragged over.
    assert delta["over_global_baseline"] == 2
    assert delta["over_global_candidate"] == 6
    assert delta["newly_over_global"] == 4


def test_cluster_delta_nets_a_clause_that_breaks_as_much_as_it_fixes():
    """The whole reason both directions are reported: this nets to zero."""
    base = _baseline(n=20, pulls=5, over_calls=2)
    delta = ab.cluster_delta(base, _candidate(base, fixed=4, new_over=4))
    assert delta["named_fixed"] == 4
    assert delta["newly_over_global"] == 4
    assert delta["region_net_rows"] == 0


def test_cluster_delta_nets_positive_for_a_clause_that_only_fixes():
    base = _baseline(n=20, pulls=5, over_calls=2)
    delta = ab.cluster_delta(base, _candidate(base, fixed=5))
    assert delta["region_net_rows"] == 5
    assert delta["region_correct_candidate"] - delta["region_correct_baseline"] == 5


def test_B_counts_only_rows_the_baseline_had_RIGHT():
    """The defect this fixes: `newly over-called global` is not B.

    A row whose baseline answer was already wrong on some other region costs nothing
    when it moves to `global` -- it was a miss either way -- but it inflates the
    over-call delta. B, as the decision rule prices it, is regressions only.
    """
    base = _baseline(n=20, pulls=5, over_calls=2)
    # Make one row wrong on ANOTHER specific region (judge=indo-pacific, said africa).
    already_wrong = base[base["pred_region"] == base["judge_region"]]["id"].iloc[0]
    base.loc[base["id"] == already_wrong, "pred_region"] = "africa"
    cand = _candidate(base, fixed=5)
    # Moving that already-wrong row to `global` costs nothing -- it was a miss either way.
    cand.loc[cand["id"] == already_wrong, "pred_region"] = "global"
    # ...but dragging a genuinely-correct row over IS a regression: that is B.
    correct_row = base[base["pred_region"] == base["judge_region"]]["id"].iloc[0]
    cand.loc[cand["id"] == correct_row, "pred_region"] = "global"

    delta = ab.cluster_delta(base, cand)
    assert delta["B"] == 1
    assert delta["B_ids"] == [str(correct_row)]
    # The weaker quantity counts the already-wrong row too, which is why it is not B.
    assert delta["newly_over_global"] == 2
    assert delta["newly_over_global"] > delta["B"]


def test_regressions_on_any_label_is_a_superset_of_B():
    base = _baseline(n=20, pulls=5, over_calls=2)
    cand = _candidate(base, fixed=5)
    correct_rows = list(base[base["pred_region"] == base["judge_region"]]["id"])
    cand.loc[cand["id"] == correct_rows[0], "pred_region"] = "global"
    cand.loc[cand["id"] == correct_rows[1], "pred_region"] = "africa"  # not global
    delta = ab.cluster_delta(base, cand)
    assert delta["B"] == 1
    assert delta["regressions_any_label"] == 2


# ---------------------------------------------------------------------------
# Deduplication of exact-duplicate snippets.
# ---------------------------------------------------------------------------


def test_duplicate_snippets_are_found_and_the_first_is_kept():
    base = _baseline(n=6)
    scale = _scale_set(base, duplicates={"s003": "s001", "s005": "s001"})
    assert ab.duplicate_snippet_ids(scale) == ["s003", "s005"]


def test_no_duplicates_means_nothing_is_dropped():
    base = _baseline(n=6)
    assert ab.duplicate_snippet_ids(_scale_set(base)) == []


def test_duplicates_leave_the_pairing_and_shrink_the_effective_n(tmp_path, monkeypatch):
    base = _baseline(n=20, pulls=5, over_calls=2)
    scale = _scale_set(base, duplicates={"s019": "s018"})
    base_path = tmp_path / "scale_predictions_v3.csv"
    cand_path = tmp_path / "candidate.csv"
    scale_path = tmp_path / "scale_set.csv"
    base.to_csv(base_path, index=False)
    _candidate(base, fixed=4).to_csv(cand_path, index=False)
    scale.to_csv(scale_path, index=False)

    monkeypatch.setattr(ab, "BASELINE_PREDS_PATH", str(base_path))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(cand_path))
    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale_path))
    monkeypatch.setattr(ab, "REPORT_PATH", str(tmp_path / "out.txt"))
    _sidecars(tmp_path, monkeypatch)

    text = ab.report()
    assert "excluded as exact duplicates: 1" in text
    assert "s019" in text
    assert "Snippets scored   : 19" in text


# ---------------------------------------------------------------------------
# The paired comparison runs through paired_compare, not a private copy.
# ---------------------------------------------------------------------------


def test_axis_comparison_grades_against_the_frozen_judge_column(tmp_path):
    base = _baseline(n=20, pulls=5, over_calls=2)
    base_path = tmp_path / "baseline.csv"
    cand_path = tmp_path / "candidate.csv"
    base.to_csv(base_path, index=False)
    _candidate(base, fixed=5).to_csv(cand_path, index=False)

    result, lift = ab.axis_comparison(
        paired_compare.read_predictions(str(base_path)),
        paired_compare.read_predictions(str(cand_path)),
        "region",
        "judge_region",
    )
    assert result.total_groups == 20
    assert lift.eligible_pairs == 20
    # Baseline: 13 of 20 right (5 pulls + 2 over-calls wrong). Candidate fixes the 5.
    assert lift.baseline_pass_rate == pytest.approx(13 / 20)
    assert lift.candidate_pass_rate == pytest.approx(18 / 20)
    assert lift.candidate_wins == 5
    assert lift.baseline_wins == 0


def test_axis_comparison_uses_the_shared_pairing_module(tmp_path):
    """Not a private reimplementation: the same call must reproduce the numbers."""
    base = _baseline(n=20, pulls=5, over_calls=2)
    base_path = tmp_path / "baseline.csv"
    cand_path = tmp_path / "candidate.csv"
    base.to_csv(base_path, index=False)
    _candidate(base, fixed=3).to_csv(cand_path, index=False)

    _, lift = ab.axis_comparison(
        paired_compare.read_predictions(str(base_path)),
        paired_compare.read_predictions(str(cand_path)),
        "region",
        "judge_region",
    )
    _, direct, _ = paired_compare.compare_prediction_files(
        str(base_path),
        str(cand_path),
        str(base_path),
        "region",
        truth_column="judge_region",
    )
    assert lift.candidate_pass_rate == direct.candidate_pass_rate
    assert lift.p_value == direct.p_value


def test_guardrail_axes_are_compared_too():
    """ADR-020's lesson encoded: region alone would have called L4 a success."""
    assert [axis for axis, _col in ab.AXES] == [
        "region",
        "category",
        "operational_domain",
    ]


# ---------------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------------


def _report_text(tmp_path, fixed=5, new_over=0):
    base = _baseline(n=20, pulls=5, over_calls=2)
    base_path = tmp_path / "baseline.csv"
    cand_path = tmp_path / "candidate.csv"
    base.to_csv(base_path, index=False)
    cand = _candidate(base, fixed=fixed, new_over=new_over)
    cand.to_csv(cand_path, index=False)
    base_df = paired_compare.read_predictions(str(base_path))
    cand_df = paired_compare.read_predictions(str(cand_path))
    comparisons = [
        (axis, *ab.axis_comparison(base_df, cand_df, axis, col))
        for axis, col in ab.AXES
    ]
    return ab.build_report(
        base_df,
        cand_df,
        comparisons,
        provenance.fingerprint("old", "claude-sonnet-5", "claude-opus-4-8"),
        provenance.fingerprint("new", "claude-sonnet-5", "claude-opus-4-8"),
        [],
        ab.judge_digest(base_df),
    )


def test_report_states_the_judge_was_not_re_run(tmp_path):
    text = _report_text(tmp_path)
    assert "judge was NOT re-run" in text
    assert "FROZEN" in text


def test_report_prints_both_prompt_hashes_so_the_contrast_is_checkable(tmp_path):
    text = _report_text(tmp_path)
    assert provenance.fingerprint("old", "a", "b")["prompt_sha256"] in text
    assert provenance.fingerprint("new", "a", "b")["prompt_sha256"] in text


def test_report_carries_all_three_axes_and_the_guardrail_rationale(tmp_path):
    text = _report_text(tmp_path)
    for axis in ("region", "category", "operational_domain"):
        assert axis in text
    assert "GUARDRAILS" in text
    assert "ADR-020" in text
    assert "McNemar" in text


def test_report_shows_both_cluster_directions(tmp_path):
    text = _report_text(tmp_path, fixed=5, new_over=3)
    assert "named `global` cluster" in text
    assert "Over-called `global`, baseline" in text
    assert "of which NEW" in text
    assert "Net row change" in text


def test_report_keeps_the_judge_is_not_a_human_caveat(tmp_path):
    text = _report_text(tmp_path)
    assert "0/54" in text
    assert "human-graded" in text


# ---------------------------------------------------------------------------
# End-to-end report(), and the live path -- both driven entirely offline.
# ---------------------------------------------------------------------------


def test_report_writes_the_artifact_and_makes_no_call(tmp_path, monkeypatch):
    base = _baseline(n=20, pulls=5, over_calls=2)
    base_path = tmp_path / "scale_predictions_v3.csv"
    cand_path = tmp_path / "region_clause_candidate.csv"
    out = tmp_path / "region_clause_ab.txt"
    base.to_csv(base_path, index=False)
    _candidate(base, fixed=4).to_csv(cand_path, index=False)
    scale_path = tmp_path / "scale_set.csv"
    _scale_set(base).to_csv(scale_path, index=False)

    monkeypatch.setattr(ab, "BASELINE_PREDS_PATH", str(base_path))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(cand_path))
    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale_path))
    monkeypatch.setattr(ab, "REPORT_PATH", str(out))
    _sidecars(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ab, "make_client", lambda: pytest.fail("report() must never build a client")
    )

    text = ab.report()
    assert out.read_text(encoding="utf-8") == text
    assert "CLAUSE A/B" in text


def test_report_refuses_when_both_arms_share_a_prompt(tmp_path, monkeypatch):
    base = _baseline()
    base_path = tmp_path / "baseline.csv"
    cand_path = tmp_path / "candidate.csv"
    base.to_csv(base_path, index=False)
    _candidate(base, fixed=2).to_csv(cand_path, index=False)
    scale_path = tmp_path / "scale_set.csv"
    _scale_set(base).to_csv(scale_path, index=False)
    monkeypatch.setattr(ab, "BASELINE_PREDS_PATH", str(base_path))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(cand_path))
    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale_path))
    monkeypatch.setattr(ab, "REPORT_PATH", str(tmp_path / "out.txt"))
    _sidecars(tmp_path, monkeypatch, baseline_prompt="same", candidate_prompt="same")
    with pytest.raises(ValueError, match="SAME prompt"):
        ab.report()


def test_report_refuses_when_a_sidecar_is_missing(tmp_path, monkeypatch):
    base = _baseline()
    base_path = tmp_path / "baseline.csv"
    cand_path = tmp_path / "candidate.csv"
    base.to_csv(base_path, index=False)
    _candidate(base).to_csv(cand_path, index=False)
    scale_path = tmp_path / "scale_set.csv"
    _scale_set(base).to_csv(scale_path, index=False)
    monkeypatch.setattr(ab, "BASELINE_PREDS_PATH", str(base_path))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(cand_path))
    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale_path))
    monkeypatch.setattr(ab, "BASELINE_PROVENANCE_PATH", str(tmp_path / "nope.json"))
    with pytest.raises(FileNotFoundError):
        ab.report()


def test_run_writes_workhorse_only_predictions_and_a_sidecar(
    tmp_path, monkeypatch, tool_client
):
    scale = tmp_path / "scale_set.csv"
    scale.write_text("id,text\ns001,a real snippet\n", encoding="utf-8")
    preds_path = tmp_path / "candidate.csv"
    sidecar = tmp_path / "candidate.provenance.json"

    monkeypatch.setattr(gold_eval, "SLEEP_BETWEEN_CALLS", 0)
    monkeypatch.setattr(ab, "SLEEP_BETWEEN_CALLS", 0)
    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(preds_path))
    monkeypatch.setattr(ab, "CANDIDATE_PROVENANCE_PATH", str(sidecar))
    monkeypatch.setattr(
        ab,
        "make_client",
        lambda: tool_client(
            {
                "category": "operations",
                "operational_domain": "sea",
                "region": "global",
            }
        ),
    )

    ab.run()

    written = pd.read_csv(preds_path)
    assert list(written.columns) == ab.CANDIDATE_COLUMNS
    # No judge columns: the whole point is that the judge is not re-run.
    assert not [c for c in written.columns if c.startswith("judge_")]
    assert written.loc[0, "pred_region"] == "global"
    assert (
        json.loads(sidecar.read_text(encoding="utf-8"))["recorded"]["workhorse_model"]
        == gold_eval.WORKHORSE_MODEL
    )


def test_run_makes_one_call_per_row_not_two(tmp_path, monkeypatch):
    """The 300-vs-600 claim, asserted rather than described."""
    scale = tmp_path / "scale_set.csv"
    scale.write_text("id,text\ns001,one\ns002,two\ns003,three\n", encoding="utf-8")
    calls = []

    def _fake(_client, text, model, system_prompt=None):
        calls.append((model, text, system_prompt))
        return {"category": "policy", "operational_domain": "multi", "region": "global"}

    monkeypatch.setattr(ab, "classify_retry", _fake)
    monkeypatch.setattr(ab, "SLEEP_BETWEEN_CALLS", 0)
    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(tmp_path / "c.csv"))
    monkeypatch.setattr(ab, "CANDIDATE_PROVENANCE_PATH", str(tmp_path / "c.json"))
    monkeypatch.setattr(ab, "make_client", lambda: object())

    ab.run()

    assert len(calls) == 3
    assert {model for model, _, _ in calls} == {gold_eval.WORKHORSE_MODEL}
    # The default is the shipped prompt: this module produced the ADR-023 arm on a
    # branch that carried the clause in SYSTEM_PROMPT, and that default must not
    # drift now that the parameter exists for the higher-power re-run to use.
    assert {prompt for _, _, prompt in calls} == {ab.SYSTEM_PROMPT}


def test_run_resumes_and_skips_done_ids(tmp_path, monkeypatch):
    scale = tmp_path / "scale_set.csv"
    scale.write_text("id,text\ns001,one\ns002,two\n", encoding="utf-8")
    preds = tmp_path / "c.csv"
    preds.write_text(
        "id,pred_category,pred_operational_domain,pred_region\ns001,policy,multi,global\n",
        encoding="utf-8",
    )
    sidecar = tmp_path / "c.json"
    provenance.write(
        provenance.fingerprint(
            ab.SYSTEM_PROMPT, gold_eval.WORKHORSE_MODEL, gold_eval.JUDGE_MODEL
        ),
        str(preds),
        path=str(sidecar),
    )
    calls = []

    def _fake(_client, text, model, system_prompt=None):
        calls.append(text)
        return {"category": "policy", "operational_domain": "multi", "region": "global"}

    monkeypatch.setattr(ab, "classify_retry", _fake)
    monkeypatch.setattr(ab, "SLEEP_BETWEEN_CALLS", 0)
    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(preds))
    monkeypatch.setattr(ab, "CANDIDATE_PROVENANCE_PATH", str(sidecar))
    monkeypatch.setattr(ab, "make_client", lambda: object())

    ab.run()
    assert calls == ["two"]


def test_run_batch_submits_one_request_per_row(tmp_path, monkeypatch, batch_client):
    scale = tmp_path / "scale_set.csv"
    scale.write_text("id,text\ns001,one\ns002,two\n", encoding="utf-8")
    preds = tmp_path / "c.csv"
    payload = {"category": "policy", "operational_domain": "multi", "region": "global"}
    client = batch_client({"s001": payload, "s002": payload})

    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(preds))
    monkeypatch.setattr(ab, "CANDIDATE_PROVENANCE_PATH", str(tmp_path / "c.json"))
    monkeypatch.setattr(ab, "make_client", lambda: client)

    ab.run(batch=True)

    assert len(client.messages.batches.created_requests) == 2
    written = pd.read_csv(preds)
    assert sorted(written["id"]) == ["s001", "s002"]


def test_run_batch_leaves_a_failed_row_todo(tmp_path, monkeypatch, batch_client):
    scale = tmp_path / "scale_set.csv"
    scale.write_text("id,text\ns001,one\ns002,two\n", encoding="utf-8")
    preds = tmp_path / "c.csv"
    payload = {"category": "policy", "operational_domain": "multi", "region": "global"}
    client = batch_client({"s001": payload, "s002": "errored"})

    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(preds))
    monkeypatch.setattr(ab, "CANDIDATE_PROVENANCE_PATH", str(tmp_path / "c.json"))
    monkeypatch.setattr(ab, "make_client", lambda: client)

    ab.run(batch=True)

    assert list(pd.read_csv(preds)["id"]) == ["s001"]


# ---------------------------------------------------------------------------
# CLI: the report path must be incapable of spending money.
# ---------------------------------------------------------------------------


def test_cli_requires_a_mode(monkeypatch):
    monkeypatch.setattr("sys.argv", ["region_clause_ab.py"])
    with pytest.raises(SystemExit):
        ab.main()


def test_cli_rejects_batch_without_run(monkeypatch):
    monkeypatch.setattr("sys.argv", ["region_clause_ab.py", "--batch"])
    with pytest.raises(SystemExit):
        ab.main()


def test_cli_report_never_builds_a_client(monkeypatch, tmp_path, capsys):
    base = _baseline(n=20, pulls=5, over_calls=2)
    base_path = tmp_path / "baseline.csv"
    cand_path = tmp_path / "candidate.csv"
    base.to_csv(base_path, index=False)
    _candidate(base, fixed=3).to_csv(cand_path, index=False)
    scale_path = tmp_path / "scale_set.csv"
    _scale_set(base).to_csv(scale_path, index=False)
    monkeypatch.setattr(ab, "BASELINE_PREDS_PATH", str(base_path))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(cand_path))
    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale_path))
    monkeypatch.setattr(ab, "REPORT_PATH", str(tmp_path / "out.txt"))
    _sidecars(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ab, "make_client", lambda: pytest.fail("--report must never build a client")
    )
    monkeypatch.setattr(
        ab,
        "classify_retry",
        lambda *a, **k: pytest.fail("--report must never classify"),
    )
    monkeypatch.setattr("sys.argv", ["region_clause_ab.py", "--report"])

    ab.main()

    assert "CLAUSE A/B" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The verdict, pinned (ADR-023). The clause was measured and REVERTED: the scale
# arm's region lift was real but marginal (p=0.0522 against a pre-registered
# p<0.05), and the pre-registered rule says marginal reverts. These two tests are
# what stop the clause from walking back into SYSTEM_PROMPT without a new
# decision -- which is the only way a pre-registered rule means anything.
# ---------------------------------------------------------------------------


def test_the_clause_is_now_in_the_shipped_prompt():
    """The adoption, pinned -- and this pin is the inverse of the one it replaces.

    ADR-023 measured this clause at p=0.0522 against a pre-registered p<0.05 and
    reverted it, and this test pinned its ABSENCE so it could not drift back in
    without a decision. That was correct on its date. The higher-power re-run
    (n=595, p=0.0002) then cleared all four rules, and ADR-024 adopted it -- so the
    assertion flips rather than being deleted, and the reason it flipped is on the
    record in both ADRs.

    The placement requirement is unchanged and is why the check reads the region
    block rather than the whole prompt: ADR-020's critic embeds
    `extract_region_block(SYSTEM_PROMPT)` verbatim and `optimize.region_rubric_violations`
    freezes that same block, so a clause outside it would be invisible to both.
    """
    from optimize import extract_region_block

    block = extract_region_block(ab.SYSTEM_PROMPT)
    assert block is not None, "the region block must still be extractable"
    assert "A US institution is not an American theater." in block


def test_the_shipped_prompt_still_licenses_the_evidence_forms_the_draft_would_have_killed():
    """The ratified conventions the first draft of the clause collided with.

    An earlier draft disqualified a command's area of operations, a headquarters site,
    and a dateline. That killed the region evidence for ~14 currently-correct rows
    (5th Fleet AO, CENTCOM/EUCOM AOR, "based on Peterson AFB", a PHILIPPINE SEA
    dateline) and flatly contradicted the ratified "Mediterranean counts as europe
    (6th Fleet / EUCOM water)" convention in data/gold/README.md.

    With the clause reverted, what has to hold is that the shipped block still states
    the evidence forms that draft would have removed, and still contains none of the
    over-reaching phrases -- so the same over-reach cannot arrive by another route.
    """
    from optimize import extract_region_block

    # The prompt is a backslash-continued literal, so compare on collapsed whitespace.
    joined = " ".join(extract_region_block(ab.SYSTEM_PROMPT).split())
    assert "a named base, city, sea, or country" in joined
    assert "A concrete identifiable location makes an anchor even at home" in joined
    # And the over-reaching phrases must stay absent.
    assert "the site of its headquarters" not in joined
    assert "story's dateline" not in joined
