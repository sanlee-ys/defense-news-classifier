"""
Tests for src/gold_eval.py (the v2 gold-set eval).

Offline only: gold-set validation and report assembly. The two-model prediction
loop hits the network and is exercised manually, like eval.py's run_predictions.
"""

import csv

import pandas as pd
import pytest

import gold_eval

GOLD_COLUMNS = ["id", "dvids_id", "source_url", "text", "category", "domain"]


def _row(rid, category, domain):
    return {
        "id": rid,
        "dvids_id": "news:1",
        "source_url": "http://example/x",
        "text": "some real defense news snippet text",
        "category": category,
        "domain": domain,
    }


def _write_gold(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=GOLD_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


# --- load_gold validation -------------------------------------------------


def test_load_gold_accepts_valid(tmp_path):
    path = tmp_path / "gold.csv"
    _write_gold(
        path, [_row("g001", "procurement", "air"), _row("g002", "operations", "sea")]
    )
    assert len(gold_eval.load_gold(str(path))) == 2


def test_load_gold_rejects_blank_labels(tmp_path):
    path = tmp_path / "gold.csv"
    _write_gold(path, [_row("g001", "procurement", "air"), _row("g002", "", "")])
    with pytest.raises(ValueError):
        gold_eval.load_gold(str(path))


def test_load_gold_rejects_invalid_label(tmp_path):
    path = tmp_path / "gold.csv"
    _write_gold(
        path, [_row("g001", "procurement", "air"), _row("g002", "bogus", "sea")]
    )
    with pytest.raises(ValueError):
        gold_eval.load_gold(str(path))


# --- build_report ---------------------------------------------------------


def test_build_report_runs_and_reports_accuracy():
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
    report = gold_eval.build_report(merged)
    assert "GOLD-SET EVAL" in report
    assert "Category accuracy" in report
    assert "Judge validation" in report
