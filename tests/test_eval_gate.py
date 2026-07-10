"""Tests for src/eval_gate.py (the evals-as-CI capability gate).

Offline only: eval_gate.py never calls the Anthropic API and needs no
ANTHROPIC_API_KEY, so every test here runs against monkeypatched fixtures or the real
committed snapshot in evals/ and data/gold/gold.csv -- no network, no key needed.
"""

import sys

import pandas as pd
import pytest

import eval_gate
import gold_eval
import gold_eval_rag

# --- gold_eval.metrics() / gold_eval_rag.metrics() extraction --------------
# These feed eval_gate.py's gated numbers directly, so their contract is tested
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


def test_gold_eval_rag_metrics_returns_expected_keys_and_values():
    merged = pd.DataFrame(
        [
            {
                "id": "g001",
                "category": "procurement",
                "operational_domain": "air",
                "pred_category": "procurement",
                "pred_operational_domain": "air",
                "rag_category": "procurement",
                "rag_operational_domain": "air",
            },
            {
                "id": "g002",
                "category": "operations",
                "operational_domain": "sea",
                "pred_category": "policy",  # baseline miss
                "pred_operational_domain": "sea",
                "rag_category": "operations",  # grounding fixes it
                "rag_operational_domain": "sea",
            },
        ]
    )
    m = gold_eval_rag.metrics(merged)

    assert m["n"] == 2
    assert m["category_accuracy_baseline"] == pytest.approx(0.5)
    assert m["category_accuracy_grounded"] == pytest.approx(1.0)
    assert m["category_accuracy_delta"] == pytest.approx(0.5)
    assert m["category_flip"] == {
        "changed": 1,
        "wrong_to_right": 1,
        "right_to_wrong": 0,
        "lateral": 0,
    }
    assert m["domain_flip"] == {
        "changed": 0,
        "wrong_to_right": 0,
        "right_to_wrong": 0,
        "lateral": 0,
    }


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


# --- _rows_for_baseline / _rows_for_rag --------------------------------------


def test_rows_for_baseline_pairs_every_metric_with_its_floor():
    m = {
        "category_accuracy": 0.9,
        "category_macro_f1": 0.9,
        "domain_accuracy": 0.9,
        "domain_macro_f1": 0.9,
        "judge_category_agreement": 0.9,
        "judge_domain_agreement": 0.9,
        "n": 54,
    }
    floors = {
        "category_accuracy": 0.83,
        "category_macro_f1": 0.85,
        "domain_accuracy": 0.83,
        "domain_macro_f1": 0.83,
        "judge_category_agreement": 0.83,
        "judge_domain_agreement": 0.88,
    }
    rows = eval_gate._rows_for_baseline(m, floors)

    assert [r[0] for r in rows] == [
        "category_accuracy",
        "category_macro_f1",
        "domain_accuracy",
        "domain_macro_f1",
        "judge_category_agreement",
        "judge_domain_agreement",
    ]


def test_rows_for_rag_includes_absolute_and_delta_floors():
    m = {
        "category_accuracy_grounded": 0.9,
        "category_macro_f1_grounded": 0.9,
        "category_accuracy_delta": 0.02,
        "domain_accuracy_delta": -0.01,
    }
    floors = {
        "category_accuracy": 0.85,
        "category_macro_f1": 0.85,
        "category_delta_min": -0.03,
        "domain_delta_min": -0.03,
    }
    rows = eval_gate._rows_for_rag(m, floors)

    assert [r[0] for r in rows] == [
        "category_accuracy",
        "category_macro_f1",
        "category_delta_min",
        "domain_delta_min",
    ]


# --- check_baseline / check_rag (merged-frame construction + grading) -------


def test_check_baseline_passes_when_metrics_clear_floors(monkeypatch):
    monkeypatch.setattr(gold_eval, "load_gold", lambda: pd.DataFrame({"id": ["g001"]}))
    monkeypatch.setattr(eval_gate, "_baseline_merged", lambda gold: gold)
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
        }
    }
    assert eval_gate.check_baseline(thresholds) is True


def test_check_baseline_fails_when_a_metric_breaches_its_floor(monkeypatch):
    monkeypatch.setattr(gold_eval, "load_gold", lambda: pd.DataFrame({"id": ["g001"]}))
    monkeypatch.setattr(eval_gate, "_baseline_merged", lambda gold: gold)
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
        }
    }
    assert eval_gate.check_baseline(thresholds) is False


def test_check_rag_fails_when_a_delta_breaches_its_floor(monkeypatch):
    monkeypatch.setattr(gold_eval, "load_gold", lambda: pd.DataFrame({"id": ["g001"]}))
    monkeypatch.setattr(eval_gate, "_rag_merged", lambda gold: gold)
    monkeypatch.setattr(
        gold_eval_rag,
        "metrics",
        lambda merged: {
            "n": len(merged),
            "category_accuracy_grounded": 0.90,
            "category_macro_f1_grounded": 0.90,
            "category_accuracy_delta": -0.10,  # grounding tanked accuracy
            "domain_accuracy_delta": 0.0,
        },
    )
    thresholds = {
        "rag": {
            "category_accuracy": 0.80,
            "category_macro_f1": 0.80,
            "category_delta_min": -0.03,
            "domain_delta_min": -0.03,
        }
    }
    assert eval_gate.check_rag(thresholds) is False


# --- main(): CLI dispatch + SystemExit contract ------------------------------


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
        "\n"
        "[rag]\n"
        "category_accuracy = 0.0\n"
        "category_macro_f1 = 0.0\n"
        "category_delta_min = -1.0\n"
        "domain_delta_min = -1.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gold_eval, "load_gold", lambda: pd.DataFrame({"id": ["g001"]}))
    monkeypatch.setattr(eval_gate, "_baseline_merged", lambda gold: gold)
    monkeypatch.setattr(eval_gate, "_rag_merged", lambda gold: gold)
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
        },
    )
    monkeypatch.setattr(
        gold_eval_rag,
        "metrics",
        lambda merged: {
            "n": 1,
            "category_accuracy_grounded": 0.90,
            "category_macro_f1_grounded": 0.90,
            "category_accuracy_delta": 0.0,
            "domain_accuracy_delta": 0.0,
        },
    )
    monkeypatch.setattr(sys, "argv", ["eval_gate.py"])

    with pytest.raises(SystemExit) as exc_info:
        eval_gate.main()
    assert exc_info.value.code == 1


def test_main_check_flag_selects_a_single_gate(monkeypatch):
    """--check baseline must not touch the rag gate at all."""
    monkeypatch.setattr(gold_eval, "load_gold", lambda: pd.DataFrame({"id": ["g001"]}))
    monkeypatch.setattr(eval_gate, "_baseline_merged", lambda gold: gold)
    monkeypatch.setattr(
        gold_eval,
        "metrics",
        lambda merged: {
            "n": 1,
            "category_accuracy": 0.90,
            "category_macro_f1": 0.90,
            "domain_accuracy": 0.90,
            "domain_macro_f1": 0.90,
            "judge_category_agreement": 0.90,
            "judge_domain_agreement": 0.90,
        },
    )

    def boom(_gold):
        raise AssertionError("rag gate must not run under --check baseline")

    monkeypatch.setattr(eval_gate, "_rag_merged", boom)
    monkeypatch.setattr(sys, "argv", ["eval_gate.py", "--check", "baseline"])

    eval_gate.main()  # must not raise


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
    }
    required_rag = {
        "category_accuracy",
        "category_macro_f1",
        "category_delta_min",
        "domain_delta_min",
    }
    assert required_baseline <= set(thresholds["baseline"])
    assert required_rag <= set(thresholds["rag"])


def test_gate_passes_on_the_real_committed_snapshot():
    thresholds = eval_gate.load_thresholds()

    assert eval_gate.check_baseline(thresholds) is True
    assert eval_gate.check_rag(thresholds) is True


def test_main_succeeds_on_the_real_committed_snapshot(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["eval_gate.py"])

    eval_gate.main()  # must not raise SystemExit
