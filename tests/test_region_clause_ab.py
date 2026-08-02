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


def _sidecars(tmp_path, monkeypatch, baseline_prompt="old", candidate_prompt="new"):
    """Write both arms' provenance sidecars and point the module at them."""
    base = tmp_path / "baseline.provenance.json"
    cand = tmp_path / "candidate.provenance.json"
    provenance.write(
        provenance.fingerprint(baseline_prompt, "claude-sonnet-5", "claude-opus-4-8"),
        "evals/baseline.csv",
        path=str(base),
    )
    provenance.write(
        provenance.fingerprint(candidate_prompt, "claude-sonnet-5", "claude-opus-4-8"),
        "evals/candidate.csv",
        path=str(cand),
    )
    monkeypatch.setattr(ab, "BASELINE_PROVENANCE_PATH", str(base))
    monkeypatch.setattr(ab, "CANDIDATE_PROVENANCE_PATH", str(cand))
    return base, cand


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
    ab.assert_answer_key_is_frozen(_baseline())


def test_answer_key_guard_rejects_a_missing_judge_column():
    frame = _baseline().drop(columns=["judge_region"])
    with pytest.raises(ValueError, match="judge_region"):
        ab.assert_answer_key_is_frozen(frame)


def test_answer_key_guard_rejects_holes_in_the_key():
    frame = _baseline()
    frame.loc[0, "judge_region"] = ""
    with pytest.raises(ValueError, match="blank"):
        ab.assert_answer_key_is_frozen(frame)


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
        str(base_path), str(cand_path), "region", "judge_region"
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
        str(base_path), str(cand_path), "region", "judge_region"
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
    comparisons = [
        (axis, *ab.axis_comparison(str(base_path), str(cand_path), axis, col))
        for axis, col in ab.AXES
    ]
    return ab.build_report(
        base,
        cand,
        comparisons,
        provenance.fingerprint("old", "claude-sonnet-5", "claude-opus-4-8"),
        provenance.fingerprint("new", "claude-sonnet-5", "claude-opus-4-8"),
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

    monkeypatch.setattr(ab, "BASELINE_PREDS_PATH", str(base_path))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(cand_path))
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
    monkeypatch.setattr(ab, "BASELINE_PREDS_PATH", str(base_path))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(cand_path))
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
    monkeypatch.setattr(ab, "BASELINE_PREDS_PATH", str(base_path))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(cand_path))
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

    def _fake(_client, text, model):
        calls.append((model, text))
        return {"category": "policy", "operational_domain": "multi", "region": "global"}

    monkeypatch.setattr(ab, "classify_retry", _fake)
    monkeypatch.setattr(ab, "SLEEP_BETWEEN_CALLS", 0)
    monkeypatch.setattr(ab, "SCALE_SET_PATH", str(scale))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(tmp_path / "c.csv"))
    monkeypatch.setattr(ab, "CANDIDATE_PROVENANCE_PATH", str(tmp_path / "c.json"))
    monkeypatch.setattr(ab, "make_client", lambda: object())

    ab.run()

    assert len(calls) == 3
    assert {model for model, _ in calls} == {gold_eval.WORKHORSE_MODEL}


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

    def _fake(_client, text, model):
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
    monkeypatch.setattr(ab, "BASELINE_PREDS_PATH", str(base_path))
    monkeypatch.setattr(ab, "CANDIDATE_PREDS_PATH", str(cand_path))
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
# The clause itself lives inside the region block, so the L4 critic and the
# optimizer's freeze guard both pick it up without being retyped.
# ---------------------------------------------------------------------------


def test_the_clause_is_inside_the_frozen_region_block():
    """ADR-020's critic embeds `extract_region_block(SYSTEM_PROMPT)` verbatim.

    A clause added outside that block would be invisible to the critic and to
    `optimize.region_rubric_violations`, quietly re-opening the gap ADR-014's
    downstream sweep missed. Placement is the guarantee, so placement is tested.
    """
    from optimize import extract_region_block

    block = extract_region_block(ab.SYSTEM_PROMPT)
    assert block is not None
    assert "An organization is not a theater." in block
