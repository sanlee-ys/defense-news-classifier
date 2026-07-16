"""Tests for src/eval_confusion.py (per-cell gold-set confusion breakdown).

Offline only: the module reads two committed CSVs and joins them, no network.
The data-backed cases double as a regression guard on the judge-vs-human
disagreement cells -- if a gold relabel or a re-run of the predictions shifts a
cell, these fail and flag it for review.
"""

import pandas as pd

import eval_confusion


def test_disagreement_cells_groups_and_sorts():
    df = pd.DataFrame(
        {
            "id": ["a", "b", "c", "d", "e"],
            "t": ["x", "x", "x", "y", "z"],
            "p": ["x", "y", "y", "x", "z"],  # b,c: x->y ; d: y->x ; a,e correct
        }
    )
    cells = eval_confusion.disagreement_cells(df, "t", "p")
    # Larger cell (x->y, 2 ids) sorts ahead of the singleton (y->x).
    assert cells == [("x", "y", ["b", "c"]), ("y", "x", ["d"])]


def test_disagreement_cells_empty_when_perfect():
    df = pd.DataFrame({"id": ["a", "b"], "t": ["x", "y"], "p": ["x", "y"]})
    assert eval_confusion.disagreement_cells(df, "t", "p") == []


def test_view_aliases_columns_for_reuse():
    merged = pd.DataFrame({"category": ["a", "b"], "judge_category": ["a", "c"]})
    view = eval_confusion._view(merged, "category", "judge_category", "category")
    assert list(view.columns) == ["category", "pred_category"]
    assert view["pred_category"].tolist() == ["a", "c"]


# --- Data-backed regression guard on the committed gold set ------------------


def _merged():
    return eval_confusion.load_merged()


def test_gold_join_is_complete():
    merged = _merged()
    # Every prediction row joins to a gold row (no orphaned ids on either side).
    preds = pd.read_csv(eval_confusion.PREDS_PATH)
    gold = pd.read_csv(eval_confusion.GOLD_PATH)
    assert len(merged) == len(preds) == len(gold)


def test_judge_vs_human_category_cells():
    cells = eval_confusion.disagreement_cells(_merged(), "category", "judge_category")
    as_dict = {(t, p): ids for t, p, ids in cells}
    assert as_dict == {
        ("technology", "operations"): ["g007", "g036", "g040"],
        ("procurement", "industry"): ["g020"],
        ("operations", "policy"): ["g053"],
    }


def test_judge_vs_human_domain_cells():
    cells = eval_confusion.disagreement_cells(
        _merged(), "operational_domain", "judge_operational_domain"
    )
    as_dict = {(t, p): sorted(ids) for t, p, ids in cells}
    assert as_dict == {
        ("air", "land"): ["g021", "g033"],
        ("multi", "land"): ["g034"],
        ("land", "multi"): ["g041"],
    }


def test_report_covers_all_axes_and_comparisons():
    report = eval_confusion.build_report(_merged())
    assert "## Category" in report
    assert "## Operational domain" in report
    for title in ("workhorse vs human", "judge vs human", "workhorse vs judge"):
        assert title in report
