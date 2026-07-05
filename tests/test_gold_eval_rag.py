"""
Tests for src/gold_eval_rag.py (v2 Step 3: does retrieval grounding beat the baseline?).

Offline only: the flip analysis, report assembly, and the retry wrapper are exercised
directly. The actual grounded-classification loop hits the network and is exercised
manually, like gold_eval.py's run_predictions.
"""

import pandas as pd

import gold_eval_rag

# --- _flip_line --------------------------------------------------------------


def test_flip_line_counts_wrong_to_right_right_to_wrong_and_lateral():
    merged = pd.DataFrame(
        [
            # wrong -> right: baseline missed, grounding fixed it
            {
                "category": "policy",
                "pred_category": "operations",
                "rag_category": "policy",
            },
            # right -> wrong: baseline had it, grounding broke it
            {
                "category": "policy",
                "pred_category": "policy",
                "rag_category": "operations",
            },
            # lateral: both wrong, just differently wrong
            {
                "category": "policy",
                "pred_category": "operations",
                "rag_category": "technology",
            },
            # unchanged: baseline and grounded agree (both correct here)
            {"category": "policy", "pred_category": "policy", "rag_category": "policy"},
        ]
    )
    line = gold_eval_rag._flip_line(merged, "category", "Category")

    assert "grounding changed 3 calls" in line
    assert "1 wrong->right" in line
    assert "1 right->wrong" in line
    assert "1 lateral" in line


# --- build_report --------------------------------------------------------


def test_build_report_runs_and_reports_baseline_vs_grounded():
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
    report = gold_eval_rag.build_report(merged)

    assert "RETRIEVAL-GROUNDED vs BASELINE" in report
    assert "Snippets : 2" in report
    assert "Category accuracy" in report
    assert "Domain accuracy" in report
