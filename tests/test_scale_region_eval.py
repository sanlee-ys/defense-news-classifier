"""Tests for src/scale_region_eval.py (the v3.2.0 scaled region eval).

Offline only. The scoring, cluster-counting and report functions run against in-memory
frames; the two live-path tests use conftest's fake clients, so no network call and no
ANTHROPIC_API_KEY are ever needed. That is deliberate: this module's whole point is that
the ONLY thing needing a key is the owner-driven `--run` pass.
"""

import json

import pandas as pd
import pytest

import gold_eval
import provenance
import scale_eval
import scale_region_eval as sre

REGIONS = ["global", "americas", "europe", "indo-pacific", "middle-east", "africa"]
CATS = ["operations", "technology", "procurement", "policy", "industry"]
DOMS = ["air", "land", "sea", "cyber", "multi", "space"]


def _preds(n: int = 60, region_wrong: int = 6, pull_from_global: bool = True):
    """Predictions frame with exactly `region_wrong` workhorse-vs-judge region misses.

    When `pull_from_global` the wrong rows are all judge=global pulled to `americas`,
    reproducing the named v3.0.0 cluster shape so the cluster counter can be asserted.
    """
    rows = []
    for i in range(n):
        jr = REGIONS[i % len(REGIONS)]
        if pull_from_global:
            jr = "global" if i < region_wrong else REGIONS[1 + (i % (len(REGIONS) - 1))]
            pr = "americas" if i < region_wrong else jr
        else:
            pr = REGIONS[(i + 1) % len(REGIONS)] if i < region_wrong else jr
        rows.append(
            {
                "id": f"s{i:03d}",
                "pred_category": CATS[i % len(CATS)],
                "pred_operational_domain": DOMS[i % len(DOMS)],
                "pred_region": pr,
                "judge_category": CATS[i % len(CATS)],
                "judge_operational_domain": DOMS[i % len(DOMS)],
                "judge_region": jr,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Scoring: the numbers must be the v2.1.0 numbers, computed by the same code.
# ---------------------------------------------------------------------------


def test_metrics_covers_all_three_axes_with_region_first():
    m = sre.metrics(_preds())
    assert m["n"] == 60
    assert [axis for axis, _p, _j in sre.AXES][0] == "region"
    for axis in ("region", "category", "operational_domain"):
        a = m[axis]
        assert {
            "accuracy",
            "correct",
            "ci_low",
            "ci_high",
            "macro_f1",
            "per_label",
            "distribution",
        } <= set(a)
        assert a["ci_low"] <= a["accuracy"] <= a["ci_high"]
        assert sum(a["distribution"].values()) == m["n"]


def test_region_accuracy_counts_the_forced_misses():
    m = sre.metrics(_preds(n=60, region_wrong=6))
    assert m["region"]["correct"] == 54
    assert m["region"]["accuracy"] == pytest.approx(0.9)
    # category and domain are constructed to agree everywhere
    assert m["category"]["correct"] == 60
    assert m["operational_domain"]["correct"] == 60


def test_region_scoring_delegates_to_the_shared_v210_helpers():
    """The comparability claim: same helper, same number, not a re-derivation."""
    preds = _preds()
    assert sre.metrics(preds)["region"]["accuracy"] == (
        scale_eval.accuracy_row(preds, "pred_region", "judge_region")["accuracy"]
    )


def test_wilson_ci_matches_hand_computed_values():
    """Pin the interval the report quotes, against the closed form worked by hand.

    87.0% is the n=54 gold region number this eval scales; 261/300 is that same
    accuracy at n=300. The pair is the whole argument for running it -- the interval
    goes from 18 points wide to 8 -- so both endpoints are asserted, not just the width.
    """
    from eval import wilson_interval

    assert wilson_interval(47, 54) == (0.7558, 0.9358)  # 87.0% at n=54: 18pts wide
    assert wilson_interval(261, 300) == (0.8272, 0.9034)  # 87.0% at n=300: 8pts wide

    m = sre.metrics(_preds(n=60, region_wrong=6))
    low, high = wilson_interval(54, 60)
    assert (m["region"]["ci_low"], m["region"]["ci_high"]) == (low, high)


# ---------------------------------------------------------------------------
# The named `global` cluster -- the reason this eval exists.
# ---------------------------------------------------------------------------


def test_global_cluster_counts_the_pull_and_its_destinations():
    c = sre.global_cluster(_preds(n=60, region_wrong=6, pull_from_global=True))
    assert c["judge_global"] == 6
    assert c["pulled"] == 6
    assert c["pulled_to"] == {"americas": 6}
    assert c["region_misses"] == 6
    assert c["pull_share"] == pytest.approx(1.0)
    assert c["over_global"] == 0


def test_global_cluster_counts_the_converse_over_call():
    preds = _preds(n=12, region_wrong=0)
    preds.loc[0, "judge_region"] = "europe"
    preds.loc[0, "pred_region"] = "global"
    c = sre.global_cluster(preds)
    assert c["over_global"] == 1
    assert c["pulled"] == 0
    assert c["region_misses"] == 1


def test_global_cluster_reports_no_pull_share_when_region_is_perfect():
    c = sre.global_cluster(_preds(n=12, region_wrong=0))
    assert c["region_misses"] == 0
    assert c["pull_share"] is None
    assert c["pulled_to"] == {}


def test_cluster_block_says_so_when_the_cluster_does_not_reproduce():
    block = "\n".join(sre._global_cluster_block(_preds(n=12, region_wrong=0)))
    assert "did not" in block


# ---------------------------------------------------------------------------
# Report rendering.
# ---------------------------------------------------------------------------


def test_build_report_leads_with_region_and_carries_wilson_cis():
    report = sre.build_report(_preds())
    assert "SCALED REGION EVAL" in report
    assert "95% CI" in report
    assert "Region accuracy" in report
    assert "Answer-key label distribution" in report
    assert "global` cluster" in report
    # region must be reported before the ride-along axes
    assert report.index("Region accuracy") < report.index("Category accuracy")


def test_report_names_the_judge_gate_it_stands_on():
    report = sre.build_report(_preds())
    assert gold_eval.JUDGE_MODEL in report
    assert "100.0%" in report  # the gated judge-region agreement
    assert "ADR-014" in report


def test_report_limitations_block_flags_a_region_skew(monkeypatch):
    rows = _preds(n=60, region_wrong=0)
    rows["judge_region"] = ["global"] * 59 + ["africa"]
    rows["pred_region"] = rows["judge_region"]
    monkeypatch.setattr(sre, "gold_reference", lambda: None)
    report = sre.build_report(rows)
    assert "Known limitation" in report
    assert "africa n=1" in report


def test_report_omits_the_shrink_block_when_the_gold_snapshot_is_absent(monkeypatch):
    monkeypatch.setattr(sre, "gold_reference", lambda: None)
    report = sre.build_report(_preds())
    assert "noise-floor shrink" not in report


def test_gold_reference_reads_the_v3_snapshot(monkeypatch, tmp_path):
    gold = tmp_path / "gold.csv"
    gold.write_text(
        "id,category,domain,region\ng001,operations,air,global\n"
        "g002,operations,air,europe\n",
        encoding="utf-8",
    )
    preds = tmp_path / "gold_predictions_v3.csv"
    preds.write_text(
        "id,pred_category,pred_operational_domain,pred_region\n"
        "g001,operations,air,global\n"
        "g002,operations,air,americas\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sre, "GOLD_PATH", str(gold))
    monkeypatch.setattr(sre, "GOLD_PREDS_PATH", str(preds))
    ref = sre.gold_reference()
    assert ref["region"]["n"] == 2
    assert ref["region"]["accuracy"] == pytest.approx(0.5)
    assert ref["category"]["accuracy"] == pytest.approx(1.0)


def test_gold_reference_is_none_when_the_snapshot_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(sre, "GOLD_PREDS_PATH", str(tmp_path / "nope.csv"))
    assert sre.gold_reference() is None


def test_region_confusion_puts_the_judge_on_the_rows():
    matrix = sre.region_confusion(_preds(n=60, region_wrong=6))
    # the six pulled rows are judge=global, predicted americas
    assert matrix.loc["global", "americas"] == 6
    assert matrix.index.name == "true"
    assert matrix.columns.name == "predicted"


# ---------------------------------------------------------------------------
# Loading + guards.
# ---------------------------------------------------------------------------


def test_load_predictions_rejects_a_two_axis_v2_file(tmp_path):
    path = tmp_path / "scale_predictions_v3.csv"
    path.write_text(
        "id,pred_category,pred_operational_domain,judge_category,"
        "judge_operational_domain\ns001,operations,air,operations,air\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="pred_region"):
        sre.load_predictions(str(path))


def test_load_predictions_accepts_a_three_axis_file(tmp_path):
    path = tmp_path / "scale_predictions_v3.csv"
    _preds(n=3).to_csv(path, index=False)
    assert len(sre.load_predictions(str(path))) == 3


def test_resume_guard_allows_a_fresh_run():
    live = provenance.fingerprint("prompt", "workhorse", "judge")
    sre.assert_resume_is_honest(set(), live)  # no rows yet -- nothing to blend


def test_resume_guard_allows_a_matching_prompt(tmp_path, monkeypatch):
    path = tmp_path / "sidecar.json"
    live = provenance.fingerprint("prompt", "workhorse", "judge")
    provenance.write(live, "evals/x.csv", path=str(path))
    monkeypatch.setattr(sre, "PROVENANCE_PATH", str(path))
    sre.assert_resume_is_honest({"s001"}, live)


def test_resume_guard_refuses_to_blend_two_classifiers(tmp_path, monkeypatch):
    path = tmp_path / "sidecar.json"
    recorded = provenance.fingerprint("old prompt", "workhorse", "judge")
    provenance.write(recorded, "evals/x.csv", path=str(path))
    monkeypatch.setattr(sre, "PROVENANCE_PATH", str(path))
    live = provenance.fingerprint("NEW prompt", "workhorse", "judge")
    with pytest.raises(ValueError, match="different prompt or model"):
        sre.assert_resume_is_honest({"s001"}, live)


# ---------------------------------------------------------------------------
# The live path, driven entirely by fakes.
# ---------------------------------------------------------------------------


def test_run_writes_three_axis_predictions_and_a_provenance_sidecar(
    tmp_path, monkeypatch, tool_client
):
    scale = tmp_path / "scale_set.csv"
    scale.write_text("id,text\ns001,a real snippet\n", encoding="utf-8")
    preds_path = tmp_path / "scale_predictions_v3.csv"
    sidecar = tmp_path / "scale_predictions_v3.provenance.json"

    monkeypatch.setattr(gold_eval, "SLEEP_BETWEEN_CALLS", 0)
    monkeypatch.setattr(sre, "SCALE_SET_PATH", str(scale))
    monkeypatch.setattr(sre, "PREDS_PATH", str(preds_path))
    monkeypatch.setattr(sre, "PROVENANCE_PATH", str(sidecar))
    monkeypatch.setattr(
        sre,
        "make_client",
        lambda: tool_client(
            {
                "category": "operations",
                "operational_domain": "sea",
                "region": "middle-east",
            }
        ),
    )

    sre.run()

    written = pd.read_csv(preds_path)
    assert set(written.columns) == sre.REQUIRED_COLUMNS
    assert written.loc[0, "judge_region"] == "middle-east"

    record = json.loads(sidecar.read_text(encoding="utf-8"))
    assert record["predictions"] == str(preds_path)
    assert record["recorded"]["judge_model"] == gold_eval.JUDGE_MODEL
    assert record["recorded"]["workhorse_model"] == gold_eval.WORKHORSE_MODEL


def test_run_makes_no_call_and_writes_no_sidecar_when_everything_is_done(
    tmp_path, monkeypatch
):
    scale = tmp_path / "scale_set.csv"
    scale.write_text("id,text\ns000,a real snippet\n", encoding="utf-8")
    preds_path = tmp_path / "scale_predictions_v3.csv"
    _preds(n=1).to_csv(preds_path, index=False)
    sidecar = tmp_path / "sidecar.json"

    monkeypatch.setattr(sre, "SCALE_SET_PATH", str(scale))
    monkeypatch.setattr(sre, "PREDS_PATH", str(preds_path))
    monkeypatch.setattr(sre, "PROVENANCE_PATH", str(sidecar))

    def explode():
        raise AssertionError("run() must not build a client when nothing is pending")

    monkeypatch.setattr(sre, "make_client", explode)

    sre.run()
    assert not sidecar.exists()


def test_report_is_offline_and_writes_both_artifacts(tmp_path, monkeypatch):
    preds_path = tmp_path / "scale_predictions_v3.csv"
    _preds(n=60, region_wrong=6).to_csv(preds_path, index=False)
    report_path = tmp_path / "scale_eval_v3.txt"
    confusion_path = tmp_path / "scale_confusion_v3_region.csv"

    monkeypatch.setattr(sre, "PREDS_PATH", str(preds_path))
    monkeypatch.setattr(sre, "REPORT_PATH", str(report_path))
    monkeypatch.setattr(sre, "REGION_CONFUSION_PATH", str(confusion_path))
    monkeypatch.setattr(sre, "gold_reference", lambda: None)

    def explode():
        raise AssertionError("report() must never build a client")

    monkeypatch.setattr(sre, "make_client", explode)

    text = sre.report()
    assert "SCALED REGION EVAL" in text
    assert report_path.read_text(encoding="utf-8") == text
    assert pd.read_csv(confusion_path, index_col=0).loc["global", "americas"] == 6


def test_cli_refuses_a_no_op_invocation(monkeypatch):
    monkeypatch.setattr("sys.argv", ["scale_region_eval.py"])
    with pytest.raises(SystemExit):
        sre.main()


def test_cli_refuses_batch_without_run(monkeypatch):
    monkeypatch.setattr("sys.argv", ["scale_region_eval.py", "--batch"])
    with pytest.raises(SystemExit):
        sre.main()


def test_cli_report_only_never_touches_the_live_path(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["scale_region_eval.py", "--report"])
    monkeypatch.setattr(sre, "report", lambda: "REPORT BODY")

    def explode(batch=False):
        raise AssertionError("--report must not invoke the live pass")

    monkeypatch.setattr(sre, "run", explode)
    sre.main()
    assert "REPORT BODY" in capsys.readouterr().out
