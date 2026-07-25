"""Tests for src/eval_gate.py (the evals-as-CI capability gate).

Offline only: eval_gate.py never calls the Anthropic API and needs no
ANTHROPIC_API_KEY, so every test here runs against monkeypatched fixtures or the real
committed snapshot in evals/ and data/gold/gold.csv -- no network, no key needed.
"""

import json
import sys

import pandas as pd
import pytest

import classify
import eval_gate
import gold_eval
import provenance

# --- gold_eval.metrics() extraction ------------------------------------------
# This feeds eval_gate.py's gated numbers directly, so its contract is tested
# here rather than only implicitly through build_report()'s existing tests.


def test_gold_eval_metrics_returns_expected_keys_and_values():
    merged = pd.DataFrame(
        [
            {
                "id": "g001",
                "category": "procurement",
                "operational_domain": "air",
                "pred_category": "procurement",
                "pred_operational_domain": "air",
                "judge_category": "procurement",
                "judge_operational_domain": "air",
            },
            {
                "id": "g002",
                "category": "operations",
                "operational_domain": "sea",
                "pred_category": "policy",  # workhorse miss
                "pred_operational_domain": "sea",
                "judge_category": "operations",  # judge agrees with human
                "judge_operational_domain": "sea",
            },
        ]
    )
    m = gold_eval.metrics(merged)

    assert set(m) == {
        "n",
        "category_accuracy",
        "category_macro_f1",
        "domain_accuracy",
        "domain_macro_f1",
        "judge_category_agreement",
        "judge_domain_agreement",
    }
    assert m["n"] == 2
    assert m["category_accuracy"] == pytest.approx(0.5)
    assert m["domain_accuracy"] == pytest.approx(1.0)
    assert m["judge_category_agreement"] == pytest.approx(1.0)
    assert m["judge_domain_agreement"] == pytest.approx(1.0)


# --- _check_sample_size -------------------------------------------------------
# Guards the inner join in _baseline_merged: if the predictions CSV is truncated or
# stale, the join silently drops gold ids and every floor can still clear on the
# smaller sample. This is what stands between that and a silent PASS.


def test_check_sample_size_passes_when_n_matches_expected(capsys):
    result = eval_gate._check_sample_size("baseline", 54, 54)

    assert result is True
    assert capsys.readouterr().out == ""


def test_check_sample_size_fails_when_predictions_are_truncated(capsys):
    result = eval_gate._check_sample_size("baseline", 40, 54)

    assert result is False
    err = capsys.readouterr().err
    assert "FAIL" in err
    assert "40 of 54" in err


# --- _print_table ------------------------------------------------------------


def test_print_table_reports_pass_when_every_row_clears_its_floor(capsys):
    rows = [("category_accuracy", 0.9, 0.8), ("domain_accuracy", 0.9, 0.8)]
    result = eval_gate._print_table("baseline", rows)

    assert result is True
    out = capsys.readouterr().out
    assert out.count("PASS") == 2
    assert "FAIL" not in out


def test_print_table_reports_fail_when_a_row_breaches_its_floor(capsys):
    rows = [("category_accuracy", 0.5, 0.8), ("domain_accuracy", 0.9, 0.8)]
    result = eval_gate._print_table("baseline", rows)

    assert result is False
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "PASS" in out  # the second row still clears its floor


# --- _rows_for_baseline ------------------------------------------------------


def test_rows_for_baseline_pairs_every_metric_with_its_floor():
    m = {
        "category_accuracy": 0.9,
        "category_macro_f1": 0.9,
        "domain_accuracy": 0.9,
        "domain_macro_f1": 0.9,
        "judge_category_agreement": 0.9,
        "judge_domain_agreement": 0.9,
        "region_accuracy": 0.9,
        "judge_region_agreement": 0.9,
        "n": 54,
    }
    floors = {
        "category_accuracy": 0.83,
        "category_macro_f1": 0.85,
        "domain_accuracy": 0.83,
        "domain_macro_f1": 0.83,
        "judge_category_agreement": 0.83,
        "judge_domain_agreement": 0.88,
        "region_accuracy": 0.78,
        "judge_region_agreement": 0.93,
    }
    rows = eval_gate._rows_for_baseline(m, floors)

    assert [r[0] for r in rows] == [
        "category_accuracy",
        "category_macro_f1",
        "domain_accuracy",
        "domain_macro_f1",
        "judge_category_agreement",
        "judge_domain_agreement",
        "region_accuracy",
        "judge_region_agreement",
    ]


# --- check_baseline (merged-frame construction + grading) --------------------


def test_check_baseline_passes_when_metrics_clear_floors(monkeypatch):
    monkeypatch.setattr(gold_eval, "load_gold", lambda: pd.DataFrame({"id": ["g001"]}))
    monkeypatch.setattr(
        eval_gate, "_baseline_merged", lambda gold, _preds_path=None: gold
    )
    monkeypatch.setattr(
        gold_eval,
        "metrics",
        lambda merged: {
            "n": len(merged),
            "category_accuracy": 0.90,
            "category_macro_f1": 0.90,
            "domain_accuracy": 0.90,
            "domain_macro_f1": 0.90,
            "judge_category_agreement": 0.90,
            "judge_domain_agreement": 0.90,
            "region_accuracy": 0.90,
            "judge_region_agreement": 0.90,
        },
    )
    thresholds = {
        "baseline": {
            "category_accuracy": 0.80,
            "category_macro_f1": 0.80,
            "domain_accuracy": 0.80,
            "domain_macro_f1": 0.80,
            "judge_category_agreement": 0.80,
            "judge_domain_agreement": 0.80,
            "region_accuracy": 0.80,
            "judge_region_agreement": 0.80,
        }
    }
    assert eval_gate.check_baseline(thresholds) is True


def test_check_baseline_fails_when_a_metric_breaches_its_floor(monkeypatch):
    monkeypatch.setattr(gold_eval, "load_gold", lambda: pd.DataFrame({"id": ["g001"]}))
    monkeypatch.setattr(
        eval_gate, "_baseline_merged", lambda gold, _preds_path=None: gold
    )
    monkeypatch.setattr(
        gold_eval,
        "metrics",
        lambda merged: {
            "n": len(merged),
            "category_accuracy": 0.50,  # below the floor
            "category_macro_f1": 0.90,
            "domain_accuracy": 0.90,
            "domain_macro_f1": 0.90,
            "judge_category_agreement": 0.90,
            "judge_domain_agreement": 0.90,
            "region_accuracy": 0.90,
            "judge_region_agreement": 0.90,
        },
    )
    thresholds = {
        "baseline": {
            "category_accuracy": 0.80,
            "category_macro_f1": 0.80,
            "domain_accuracy": 0.80,
            "domain_macro_f1": 0.80,
            "judge_category_agreement": 0.80,
            "judge_domain_agreement": 0.80,
            "region_accuracy": 0.80,
            "judge_region_agreement": 0.80,
        }
    }
    assert eval_gate.check_baseline(thresholds) is False


def test_check_baseline_fails_when_predictions_are_truncated(monkeypatch, capsys):
    """A partial gold_predictions.csv (40 of 54 ids) must FAIL, not silently grade 40."""
    monkeypatch.setattr(
        gold_eval,
        "load_gold",
        lambda: pd.DataFrame({"id": [f"g{i:03d}" for i in range(54)]}),
    )
    monkeypatch.setattr(
        eval_gate, "_baseline_merged", lambda gold, _preds_path=None: gold.iloc[:40]
    )  # simulates the inner join dropping 14 unpredicted ids
    monkeypatch.setattr(
        gold_eval,
        "metrics",
        lambda merged: {
            "n": len(merged),
            "category_accuracy": 0.95,  # would clear every floor on the smaller sample
            "category_macro_f1": 0.95,
            "domain_accuracy": 0.95,
            "domain_macro_f1": 0.95,
            "judge_category_agreement": 0.95,
            "judge_domain_agreement": 0.95,
            "region_accuracy": 0.95,
            "judge_region_agreement": 0.95,
        },
    )
    thresholds = {
        "baseline": {
            "category_accuracy": 0.80,
            "category_macro_f1": 0.80,
            "domain_accuracy": 0.80,
            "domain_macro_f1": 0.80,
            "judge_category_agreement": 0.80,
            "judge_domain_agreement": 0.80,
            "region_accuracy": 0.80,
            "judge_region_agreement": 0.80,
        }
    }

    assert eval_gate.check_baseline(thresholds) is False
    assert "40 of 54" in capsys.readouterr().err


def test_check_baseline_refuses_a_two_axis_predictions_file(monkeypatch, capsys):
    """A v2-shaped file (no pred_region) must FAIL loudly, not gate 6 of 8."""
    monkeypatch.setattr(gold_eval, "load_gold", lambda: pd.DataFrame({"id": ["g001"]}))
    monkeypatch.setattr(
        eval_gate, "_baseline_merged", lambda gold, _preds_path=None: gold
    )
    # metrics() omits the region keys when the frame carries no pred_region.
    monkeypatch.setattr(
        gold_eval,
        "metrics",
        lambda merged: {
            "n": len(merged),
            "category_accuracy": 0.95,
            "category_macro_f1": 0.95,
            "domain_accuracy": 0.95,
            "domain_macro_f1": 0.95,
            "judge_category_agreement": 0.95,
            "judge_domain_agreement": 0.95,
        },
    )
    thresholds = {"baseline": {}}

    assert eval_gate.check_baseline(thresholds) is False
    assert "two-axis" in capsys.readouterr().err


# --- main(): SystemExit contract ---------------------------------------------


def test_main_exits_nonzero_when_a_floor_is_breached(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "thresholds.toml").write_text(
        "[baseline]\n"
        "category_accuracy = 0.99\n"  # impossible floor, forces a breach
        "category_macro_f1 = 0.0\n"
        "domain_accuracy = 0.0\n"
        "domain_macro_f1 = 0.0\n"
        "judge_category_agreement = 0.0\n"
        "judge_domain_agreement = 0.0\n"
        "region_accuracy = 0.0\n"
        "judge_region_agreement = 0.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gold_eval, "load_gold", lambda: pd.DataFrame({"id": ["g001"]}))
    monkeypatch.setattr(
        eval_gate, "_baseline_merged", lambda gold, _preds_path=None: gold
    )
    monkeypatch.setattr(
        gold_eval,
        "metrics",
        lambda merged: {
            "n": 1,
            "category_accuracy": 0.50,
            "category_macro_f1": 0.90,
            "domain_accuracy": 0.90,
            "domain_macro_f1": 0.90,
            "judge_category_agreement": 0.90,
            "judge_domain_agreement": 0.90,
            "region_accuracy": 0.90,
            "judge_region_agreement": 0.90,
        },
    )
    monkeypatch.setattr(sys, "argv", ["eval_gate.py"])

    with pytest.raises(SystemExit) as exc_info:
        eval_gate.main()
    assert exc_info.value.code == 1


def test_baseline_merged_honors_a_preds_path_override(tmp_path):
    """The CI live job grades its freshly regenerated file via --preds.

    The default is the committed v3 snapshot; this exercises the override the
    workflow's live leg depends on (grading an arbitrary v3-shaped file).
    """
    preds_path = tmp_path / "fresh_v3.csv"
    pd.DataFrame(
        [
            {
                "id": "g001",
                "pred_category": "procurement",
                "pred_operational_domain": "air",
                "pred_region": "global",
                "judge_category": "procurement",
                "judge_operational_domain": "air",
                "judge_region": "global",
            }
        ]
    ).to_csv(preds_path, index=False)
    gold = pd.DataFrame(
        [
            {
                "id": "g001",
                "category": "procurement",
                "domain": "air",
                "region": "global",
            }
        ]
    )

    merged = eval_gate._baseline_merged(gold, str(preds_path))

    assert len(merged) == 1
    m = gold_eval.metrics(merged)
    # The six gated v2 keys are present AND the ungated region numbers ride along.
    assert m["category_accuracy"] == 1.0
    assert m["region_accuracy"] == 1.0


# --- check_provenance ---------------------------------------------------------
# The gate grades a FROZEN snapshot, so "the shipped numbers still clear the bar" is
# only true while that snapshot still describes the shipped classifier. Without this,
# editing classify.SYSTEM_PROMPT and skipping the paid gold re-run leaves the offline
# gate reporting the measured floors as met for a classifier that never made those
# predictions -- the same hole scripts/gen_metrics_artifact.py already refuses.


def test_provenance_passes_on_the_real_committed_snapshot():
    """The committed sidecar must match the prompt and models on disk today."""
    assert eval_gate.check_provenance() is True


def test_an_edited_prompt_stops_the_gate(monkeypatch, capsys):
    """The headline case: a prompt edit with no gold re-run must not grade green."""
    monkeypatch.setattr(classify, "SYSTEM_PROMPT", classify.SYSTEM_PROMPT + "\nedit")

    assert eval_gate.check_provenance() is False
    assert "STALE SNAPSHOT" in capsys.readouterr().err


def test_a_model_swap_stops_the_gate(monkeypatch, capsys):
    """A model migration invalidates the snapshot as thoroughly as a prompt edit."""
    monkeypatch.setattr(gold_eval, "WORKHORSE_MODEL", "claude-sonnet-6")

    assert eval_gate.check_provenance() is False
    assert "workhorse_model" in capsys.readouterr().err


def test_the_failure_names_grading_not_publishing(monkeypatch, capsys):
    """Wrong consequence sends the reader to gen_metrics_artifact.py for a gate bug."""
    monkeypatch.setattr(classify, "SYSTEM_PROMPT", classify.SYSTEM_PROMPT + "\nedit")

    eval_gate.check_provenance()

    err = capsys.readouterr().err
    assert "Grading now" in err
    assert "Publishing now" not in err
    # The remedy is the shared one -- re-run the eval, or waive it on the record.
    assert "src/gold_eval.py" in err and "waiver" in err


def test_a_waiver_accepting_the_current_fingerprint_lets_the_gate_run(
    monkeypatch, tmp_path, capsys
):
    """A prompt edit must be waivable on the record, or the guard gets deleted."""
    monkeypatch.setattr(classify, "SYSTEM_PROMPT", "reworded")
    live = provenance.fingerprint(
        "reworded", gold_eval.WORKHORSE_MODEL, gold_eval.JUDGE_MODEL
    )
    sidecar = tmp_path / "p.json"
    record = json.loads(
        provenance.render(provenance.fingerprint("old", "m1", "m2"), "x")
    )
    record["waiver"] = {"accepts": live, "reason": "comment-only reword"}
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(provenance, "PROVENANCE_PATH", str(sidecar))

    assert eval_gate.check_provenance() is True
    assert "WAIVED" in capsys.readouterr().out


def test_a_missing_sidecar_fails_rather_than_skipping(monkeypatch, tmp_path, capsys):
    """Otherwise deleting one file is a one-command bypass of the whole guard."""
    monkeypatch.setattr(provenance, "PROVENANCE_PATH", str(tmp_path / "absent.json"))

    assert eval_gate.check_provenance() is False
    assert "is missing" in capsys.readouterr().err


def test_a_non_default_preds_file_is_reported_unpinned_not_failed(tmp_path, capsys):
    """Only PREDS_PATH has a sidecar; --preds elsewhere is unpinned, not broken.

    The frozen v2 snapshot is the reason this must not hard-fail -- it has no record
    and must never acquire a hand-written one.
    """
    assert eval_gate.check_provenance(str(tmp_path / "experiment.csv")) is True

    out = capsys.readouterr().out
    assert "UNPINNED" in out
    assert "No prompt/model pairing" in out


def test_the_live_jobs_explicit_default_path_is_still_checked(capsys):
    """The live job names the default file explicitly; it must still be checked.

    CI passes --preds evals/gold_predictions_v3.csv, which is the default path by
    another spelling and must not slip through as UNPINNED.
    """
    assert eval_gate.check_provenance("evals/gold_predictions_v3.csv") is True
    assert "UNPINNED" not in capsys.readouterr().out


def test_main_exits_nonzero_on_a_stale_snapshot(monkeypatch, capsys):
    """And says it is a pairing failure, not a breached floor."""
    monkeypatch.setattr(classify, "SYSTEM_PROMPT", classify.SYSTEM_PROMPT + "\nedit")
    monkeypatch.setattr(sys, "argv", ["eval_gate.py"])

    with pytest.raises(SystemExit) as exc_info:
        eval_gate.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "not pinned to the classifier on disk" in err
    assert "below its floor" not in err


# --- against the real committed snapshot -------------------------------------


def test_thresholds_toml_has_every_required_key():
    thresholds = eval_gate.load_thresholds()

    required_baseline = {
        "category_accuracy",
        "category_macro_f1",
        "domain_accuracy",
        "domain_macro_f1",
        "judge_category_agreement",
        "judge_domain_agreement",
        "region_accuracy",
        "judge_region_agreement",
    }
    assert required_baseline <= set(thresholds["baseline"])
    # BM25 grounding was retired (ADR-012); there is no [rag] table any more.
    assert "rag" not in thresholds


def test_gate_passes_on_the_real_committed_snapshot():
    thresholds = eval_gate.load_thresholds()

    assert eval_gate.check_baseline(thresholds) is True


def test_main_succeeds_on_the_real_committed_snapshot(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["eval_gate.py"])

    eval_gate.main()  # must not raise SystemExit
