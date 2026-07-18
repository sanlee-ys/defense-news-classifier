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
#
# These pin to the FROZEN v2 predictions snapshot, not the module's live (v3)
# PREDS_PATH: the v3 file only exists after the owner's live pass, and these
# cells are the record behind the published two-axis numbers -- they must not
# drift even while the v3 harness is being built.

V2_PREDS_PATH = "evals/gold_predictions.csv"


def _merged():
    return eval_confusion.load_merged(preds_path=V2_PREDS_PATH)


def test_gold_join_is_complete():
    merged = _merged()
    # Every prediction row joins to a gold row (no orphaned ids on either side).
    preds = pd.read_csv(V2_PREDS_PATH)
    gold = pd.read_csv(eval_confusion.GOLD_PATH)
    assert len(merged) == len(preds) == len(gold)


def test_judge_vs_human_category_cells():
    cells = eval_confusion.disagreement_cells(_merged(), "category", "judge_category")
    as_dict = {(t, p): ids for t, p, ids in cells}
    # Cells reset after the PR #79 prompt change: the tech-vs-ops clause cleared
    # g036 and g040 (technology->operations went from x3 to x1), leaving g007.
    assert as_dict == {
        ("technology", "operations"): ["g007"],
        ("procurement", "industry"): ["g020"],
        ("operations", "policy"): ["g053"],
    }


def test_judge_vs_human_domain_cells():
    cells = eval_confusion.disagreement_cells(
        _merged(), "operational_domain", "judge_operational_domain"
    )
    as_dict = {(t, p): sorted(ids) for t, p, ids in cells}
    # Cells reset after the PR #79 prompt change: the air-over-ground clause cleared
    # g034 (multi->land) and moved g033 off land (air->land became air->multi).
    assert as_dict == {
        ("air", "land"): ["g021"],
        ("air", "multi"): ["g033"],
        ("land", "multi"): ["g041"],
    }


def test_report_covers_all_axes_and_comparisons():
    # Synthetic frame (not the v2 snapshot): the report now renders the region
    # axis, which the frozen v2 predictions don't carry.
    merged = pd.DataFrame(
        [
            {
                "id": "g001",
                "category": "procurement",
                "operational_domain": "air",
                "region": "global",
                "pred_category": "procurement",
                "pred_operational_domain": "air",
                "pred_region": "global",
                "judge_category": "procurement",
                "judge_operational_domain": "air",
                "judge_region": "americas",  # one region disagreement to render
            },
            {
                "id": "g002",
                "category": "operations",
                "operational_domain": "sea",
                "region": "indo-pacific",
                "pred_category": "operations",
                "pred_operational_domain": "sea",
                "pred_region": "indo-pacific",
                "judge_category": "operations",
                "judge_operational_domain": "sea",
                "judge_region": "indo-pacific",
            },
        ]
    )
    report = eval_confusion.build_report(merged)
    assert "## Category" in report
    assert "## Operational domain" in report
    assert "## Region" in report
    for title in ("workhorse vs human", "judge vs human", "workhorse vs judge"):
        assert title in report


def test_confusion_csv_paths_cover_every_axis():
    # The machine-readable judge-vs-human matrices must exist for each axis the
    # report renders -- adding an axis without its CSV is the drift this guards.
    assert set(eval_confusion.CONFUSION_CSV) == {
        field for field, _ in eval_confusion.AXES
    }
    # v3 filenames only: the v2 outputs are frozen records (ADR-014).
    for path in eval_confusion.CONFUSION_CSV.values():
        assert "_v3" in path
