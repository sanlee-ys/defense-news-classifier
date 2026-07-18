"""Tests for src/scale_eval.py (the v2.1.0 scaled eval).

Offline only: the scoring/report functions run against in-memory frames, and the one
prediction-loop test uses the fake tool client from conftest -- no network, no key.
"""

import pandas as pd
import pytest

import gold_eval
import scale_eval


def _preds(n_cat_wrong: int = 3, n_dom_wrong: int = 5, n: int = 60) -> pd.DataFrame:
    """Predictions frame with exactly n_cat_wrong / n_dom_wrong workhorse-vs-judge misses."""
    rows = []
    cats = ["operations", "technology", "procurement", "policy", "industry"]
    doms = ["air", "land", "sea", "cyber", "multi", "space"]
    for i in range(n):
        jc, jd = cats[i % len(cats)], doms[i % len(doms)]
        # A wrong row predicts the NEXT label in the cycle -- always distinct from jc.
        pc = cats[(i + 1) % len(cats)] if i < n_cat_wrong else jc
        pd_ = doms[(i + 1) % len(doms)] if i < n_dom_wrong else jd
        rows.append(
            {
                "id": f"s{i:03d}",
                "pred_category": pc,
                "pred_operational_domain": pd_,
                "judge_category": jc,
                "judge_operational_domain": jd,
            }
        )
    return pd.DataFrame(rows)


def test_load_scale_set_requires_id_and_text(tmp_path):
    good = tmp_path / "ok.csv"
    good.write_text("id,text\ns001,some snippet\n", encoding="utf-8")
    assert list(scale_eval.load_scale_set(good).columns) == ["id", "text"]

    bad = tmp_path / "bad.csv"
    bad.write_text("id,body\ns001,x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="text"):
        scale_eval.load_scale_set(bad)


def test_accuracy_row_counts_and_brackets_the_estimate():
    preds = _preds(n_cat_wrong=3, n=60)
    row = scale_eval._accuracy_row(preds, "pred_category", "judge_category")
    assert row["n"] == 60
    assert row["correct"] == 57  # 3 forced disagreements
    assert row["ci_low"] < row["accuracy"] < row["ci_high"]


def test_metrics_covers_both_axes_with_ci_distribution_and_macro():
    m = scale_eval.metrics(_preds())
    assert m["n"] == 60
    for axis in ("category", "operational_domain"):
        a = m[axis]
        assert {
            "accuracy",
            "ci_low",
            "ci_high",
            "macro_f1",
            "per_label",
            "distribution",
        } <= set(a)
        assert a["ci_low"] <= a["accuracy"] <= a["ci_high"]
        # the judge answer-key distribution sums back to n
        assert sum(a["distribution"].values()) == m["n"]


def test_build_report_leads_with_accuracy_and_wilson_cis():
    report = scale_eval.build_report(_preds())
    assert "SCALED EVAL" in report
    assert "95% CI" in report
    assert "Category accuracy" in report
    assert "Answer-key label distribution" in report


def test_run_predictions_writes_to_the_scale_path(tmp_path, monkeypatch, tool_client):
    """scale_eval relies on gold_eval.run_predictions honoring a custom preds_path."""
    monkeypatch.setattr(gold_eval, "SLEEP_BETWEEN_CALLS", 0)
    client = tool_client(
        {"category": "operations", "operational_domain": "air", "region": "global"}
    )
    df = pd.DataFrame([{"id": "s001", "text": "a real snippet"}])
    out = tmp_path / "scale_predictions.csv"

    gold_eval.run_predictions(client, df, set(), preds_path=str(out))

    written = pd.read_csv(out)
    assert written.loc[0, "id"] == "s001"
    assert set(written.columns) == {
        "id",
        "pred_category",
        "pred_operational_domain",
        "judge_category",
        "judge_operational_domain",
    }


def test_limitations_block_flags_a_skewed_axis_with_a_thin_class():
    rows = [
        {
            "id": f"s{i:03d}",
            "pred_category": "industry" if i == 0 else "operations",
            "pred_operational_domain": "air",
            "judge_category": "industry" if i == 0 else "operations",
            "judge_operational_domain": "air",
        }
        for i in range(60)  # 59 operations, 1 industry
    ]
    block = "\n".join(
        scale_eval._limitations_block(scale_eval.metrics(pd.DataFrame(rows)))
    )
    assert "Known limitation" in block
    assert "operations" in block and "industry n=1" in block
    assert "macro-F1" in block  # the distortion caveat fires on the thin class


def test_limitations_block_empty_when_axes_are_balanced():
    # _preds() spreads labels evenly (>= MIN_LABEL_SUPPORT each, none dominant).
    assert scale_eval._limitations_block(scale_eval.metrics(_preds())) == []
