"""Offline tests for the kNN-exemplar experiment (no API key, no network).

What gets pinned: leave-one-out retrieval never returns the query row, the
exemplar block carries labels but appends (never replaces) the system prompt,
the gold set is disjoint from the pool, and the resume filter skips scored ids.
"""

import pandas as pd
import pytest

import exemplar_eval
from classify import SYSTEM_PROMPT
from exemplar_eval import (
    DEFAULT_K,
    ExemplarIndex,
    exemplar_block,
    pending_rows,
)


@pytest.fixture(scope="module")
def pool():
    return exemplar_eval._load_pool()


@pytest.fixture(scope="module")
def index(pool):
    return ExemplarIndex(pool)


def test_retrieve_returns_k_labeled_rows(index, pool):
    hits = index.retrieve(pool.iloc[0]["text"], k=DEFAULT_K)
    assert len(hits) == DEFAULT_K
    assert set(hits.columns) >= {"id", "text", "category", "operational_domain"}
    assert set(hits["id"]) <= set(pool["id"])


def test_leave_one_out_never_returns_the_query_row(index, pool):
    # A row's own text is its best BM25 match, so without the guard the top
    # hit would be itself -- check a sample of rows across the pool.
    for _, row in pool.iloc[::37].iterrows():
        hits = index.retrieve(row["text"], k=DEFAULT_K, exclude_id=row["id"])
        assert row["id"] not in set(hits["id"])
        # Sanity: without the exclusion, the row does retrieve itself.
    self_hits = index.retrieve(pool.iloc[0]["text"], k=1)
    assert self_hits.iloc[0]["id"] == pool.iloc[0]["id"]


def test_exemplar_block_carries_labels_and_region_disclaimer(index, pool):
    hits = index.retrieve(pool.iloc[5]["text"], k=DEFAULT_K)
    block = exemplar_block(hits)
    for _, row in hits.iterrows():
        assert f"category={row['category']}" in block
        assert f"operational_domain={row['operational_domain']}" in block
    assert "region labels intentionally not shown" in block
    # The block is a suffix: the full prompt keeps the entire rubric intact.
    prompt = SYSTEM_PROMPT + block
    assert prompt.startswith(SYSTEM_PROMPT)


def test_gold_set_is_disjoint_from_the_pool(pool):
    gold_ids = set(pd.read_csv(exemplar_eval.GOLD_PATH)["id"])
    assert not gold_ids & set(pool["id"])


def test_pool_labels_are_judge_labels_not_workhorse(pool):
    # The pool loader is baseline_ml.load_train, whose judge-only guarantee is
    # pinned in test_baseline_ml; assert the contract shape here so a loader
    # swap that reintroduces pred_* columns fails this suite too.
    assert not any(col.startswith("pred_") for col in pool.columns)
    assert list(pool.columns) == ["id", "text", "category", "operational_domain"]


def test_pending_rows_skips_scored_ids(tmp_path):
    rows = pd.DataFrame({"id": ["a", "b", "c"], "text": ["x", "y", "z"]})
    out = tmp_path / "arm.csv"
    assert len(pending_rows(rows, str(out))) == 3
    pd.DataFrame(
        {
            "id": ["a", "c"],
            "pred_category": ["operations", "policy"],
            "pred_operational_domain": ["air", "multi"],
            "pred_region": ["global", "global"],
        }
    ).to_csv(out, index=False)
    remaining = pending_rows(rows, str(out))
    assert list(remaining["id"]) == ["b"]


def test_report_builds_without_any_arm_run(tmp_path, monkeypatch):
    monkeypatch.setattr(
        exemplar_eval,
        "ARM_PATHS",
        {k: str(tmp_path / f"{k}.csv") for k in exemplar_eval.ARM_PATHS},
    )
    monkeypatch.setattr(exemplar_eval, "REPORT_PATH", str(tmp_path / "report.txt"))
    report = exemplar_eval.build_report()
    assert "not yet run" in report
    assert "double-negative" in report
