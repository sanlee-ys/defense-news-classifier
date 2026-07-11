"""Tests for src/retrieval_error_analysis.py (BM25-vs-embeddings analysis slice).

Fully offline: the module never calls the API, so we test the retrieval-hit
classifier, the on/off-target bucketing, and report assembly against small
hand-built frames and doc-label maps.
"""

import pandas as pd

import retrieval_error_analysis as rea

# doc-id -> label map, standing in for the corpus manifest
LABELS = {
    "doc_ops_sea": {"category": "operations", "operational_domain": "sea"},
    "doc_proc_air": {"category": "procurement", "operational_domain": "air"},
}


def test_retrieval_hit_true_when_true_label_present():
    # true category "operations" IS carried by doc_ops_sea in the citations
    assert rea._retrieval_hit(
        "doc_ops_sea;doc_proc_air", "operations", "category", LABELS
    )


def test_retrieval_hit_false_when_true_label_absent():
    # true category "policy" is carried by neither retrieved doc
    assert not rea._retrieval_hit(
        "doc_ops_sea;doc_proc_air", "policy", "category", LABELS
    )


def test_retrieval_hit_ignores_unknown_doc_ids():
    assert not rea._retrieval_hit("nonexistent_doc", "operations", "category", LABELS)


def _merged(rows):
    return pd.DataFrame(rows)


def test_analyze_buckets_on_and_off_target():
    merged = _merged(
        [
            # grounded category miss; BM25 retrieved a same-category (operations)
            # doc -> retrieval on-target (not retrieval's fault)
            {
                "id": "g1",
                "category": "operations",
                "operational_domain": "sea",
                "pred_category": "operations",
                "pred_operational_domain": "sea",
                "rag_category": "procurement",
                "rag_operational_domain": "sea",
                "citations": "doc_ops_sea;doc_proc_air",
            },
            # grounded category miss; no retrieved doc carries "policy"
            # -> retrieval off-target
            {
                "id": "g2",
                "category": "policy",
                "operational_domain": "air",
                "pred_category": "policy",
                "pred_operational_domain": "air",
                "rag_category": "procurement",
                "rag_operational_domain": "air",
                "citations": "doc_ops_sea;doc_proc_air",
            },
            # fully correct row -> contributes no cases
            {
                "id": "g3",
                "category": "procurement",
                "operational_domain": "air",
                "pred_category": "procurement",
                "pred_operational_domain": "air",
                "rag_category": "procurement",
                "rag_operational_domain": "air",
                "citations": "doc_proc_air",
            },
        ]
    )
    a = rea.analyze(merged, LABELS)

    assert a["n"] == 3
    cat = a["fields"]["category"]
    assert cat["grounded_miss"] == 2
    assert cat["retrieval_on_target"] == 1  # g1
    assert cat["retrieval_off_target"] == 1  # g2
    # one case per (snippet, field) grounded miss -> 2 category misses here
    assert len([c for c in a["cases"] if c["field"] == "category"]) == 2


def test_build_report_renders_headline_and_tables():
    merged = _merged(
        [
            {
                "id": "g1",
                "category": "operations",
                "operational_domain": "sea",
                "pred_category": "operations",
                "pred_operational_domain": "sea",
                "rag_category": "procurement",
                "rag_operational_domain": "sea",
                "citations": "doc_proc_air",  # off-target
            },
        ]
    )
    report = rea.build_report(rea.analyze(merged, LABELS))
    assert "BM25-vs-embeddings analysis" in report
    assert "retrieval-off-target" in report
    assert "upper bound" in report.lower()
    assert "Per-case detail" in report
