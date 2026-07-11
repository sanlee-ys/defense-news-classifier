"""Tests for src/stability.py.

Covers the pure aggregation/reporting functions on hand-built data. The
API-calling runner (run_one_pass / main) is not exercised here — it's a thin
loop over the already-tested classify_with_retry.
"""

import pandas as pd
import pytest

import stability


def _merged(rows):
    """Rows = (cat, pred_cat, dom, pred_dom)."""
    return pd.DataFrame(
        [
            {
                "category": c,
                "pred_category": pc,
                "operational_domain": d,
                "pred_operational_domain": pd_,
            }
            for c, pc, d, pd_ in rows
        ]
    )


# --- headline_metrics ----------------------------------------------------


def test_headline_metrics_all_correct_is_unit():
    m = _merged(
        [
            ("procurement", "procurement", "air", "air"),
            ("policy", "policy", "sea", "sea"),
        ]
    )
    h = stability.headline_metrics(m)
    assert h["category_accuracy"] == 1.0
    assert h["category_macro_f1"] == 1.0
    assert h["domain_accuracy"] == 1.0
    assert h["domain_macro_f1"] == 1.0


def test_headline_metrics_reports_accuracy_fraction():
    m = _merged(
        [
            ("procurement", "procurement", "air", "air"),  # cat right, dom right
            ("policy", "industry", "sea", "sea"),  # cat wrong, dom right
        ]
    )
    h = stability.headline_metrics(m)
    assert h["category_accuracy"] == 0.5
    assert h["domain_accuracy"] == 1.0


# --- summarize_runs ------------------------------------------------------


def test_summarize_single_run_has_zero_std():
    per_run = [
        {
            "category_accuracy": 0.79,
            "category_macro_f1": 0.765,
            "domain_accuracy": 0.973,
            "domain_macro_f1": 0.973,
        }
    ]
    s = stability.summarize_runs(per_run)
    assert s["category_accuracy"]["std"] == 0.0
    assert s["category_accuracy"]["mean"] == 0.79
    assert s["category_accuracy"]["min"] == s["category_accuracy"]["max"] == 0.79


def test_summarize_computes_mean_std_min_max():
    per_run = [
        {
            "category_accuracy": 0.80,
            "category_macro_f1": 0.0,
            "domain_accuracy": 0.0,
            "domain_macro_f1": 0.0,
        },
        {
            "category_accuracy": 0.76,
            "category_macro_f1": 0.0,
            "domain_accuracy": 0.0,
            "domain_macro_f1": 0.0,
        },
    ]
    s = stability.summarize_runs(per_run)["category_accuracy"]
    assert s["mean"] == 0.78
    assert s["min"] == 0.76
    assert s["max"] == 0.80
    # sample std of [0.80, 0.76] = 0.0283
    assert s["std"] == pytest.approx(0.0283, abs=1e-4)


def test_summarize_empty_raises():
    with pytest.raises(ValueError):
        stability.summarize_runs([])


# --- label_consistency ---------------------------------------------------


def _preds(rows):
    """Rows = list of (id, pred_cat, pred_dom) for one run."""
    return pd.DataFrame(
        [
            {"id": i, "pred_category": c, "pred_operational_domain": d}
            for i, c, d in rows
        ]
    )


def test_label_consistency_all_runs_agree_is_unit():
    frames = [
        _preds([("a", "policy", "air"), ("b", "industry", "sea")]),
        _preds([("a", "policy", "air"), ("b", "industry", "sea")]),
    ]
    c = stability.label_consistency(frames)
    assert c["category_consistency"] == 1.0
    assert c["domain_consistency"] == 1.0


def test_label_consistency_counts_disagreements():
    frames = [
        _preds([("a", "policy", "air"), ("b", "industry", "sea")]),
        _preds([("a", "policy", "air"), ("b", "procurement", "land")]),  # b flips both
    ]
    c = stability.label_consistency(frames)
    assert c["category_consistency"] == 0.5  # only "a" stable
    assert c["domain_consistency"] == 0.5


def test_label_consistency_single_run_is_trivially_unit():
    frames = [_preds([("a", "policy", "air"), ("b", "industry", "sea")])]
    c = stability.label_consistency(frames)
    assert c["category_consistency"] == 1.0
    assert c["domain_consistency"] == 1.0


def test_label_consistency_empty_raises():
    with pytest.raises(ValueError):
        stability.label_consistency([])


# --- build_stability_report ----------------------------------------------


def test_report_includes_runs_noise_guidance_and_consistency():
    per_run = [
        {
            "category_accuracy": 0.79,
            "category_macro_f1": 0.765,
            "domain_accuracy": 0.973,
            "domain_macro_f1": 0.973,
        },
        {
            "category_accuracy": 0.77,
            "category_macro_f1": 0.75,
            "domain_accuracy": 0.97,
            "domain_macro_f1": 0.97,
        },
    ]
    summary = stability.summarize_runs(per_run)
    consistency = {"category_consistency": 0.98, "domain_consistency": 0.99}
    report = stability.build_stability_report(per_run, summary, consistency)

    assert "Runs     : 2" in report
    # The temperature knob is gone; sampling is the API default now.
    assert "Temperature" not in report
    assert "category_accuracy" in report
    assert "2x the" in report  # the noise-floor guidance is present
    assert "Label consistency" in report
    assert "0.9800" in report and "0.9900" in report  # the consistency numbers
    assert "run 1:" in report and "run 2:" in report
