"""Tests for src/gold_eval_rag.py (v2 Step 3: does retrieval grounding beat the baseline?).

Offline only: the flip analysis, report assembly, and the retry wrapper are exercised
directly. The actual grounded-classification loop hits the network and is exercised
manually, like gold_eval.py's run_predictions.
"""

import types

import pandas as pd
import pytest

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


# --- classify_retry (backoff on transient API errors) --------------------


class _FakeRateLimit(Exception):
    pass


class _FakeServerError(Exception):
    pass


@pytest.fixture
def patch_transient(monkeypatch):
    """Swap the SDK error classes for plain ones and disable the backoff sleep."""
    monkeypatch.setattr(gold_eval_rag.anthropic, "RateLimitError", _FakeRateLimit)
    monkeypatch.setattr(
        gold_eval_rag.anthropic, "InternalServerError", _FakeServerError
    )
    monkeypatch.setattr(gold_eval_rag.time, "sleep", lambda *_: None)


def test_classify_retry_returns_and_passes_configured_k(monkeypatch, patch_transient):
    seen_k = []

    def fake_grounded(_client, _text, _retriever, k):
        seen_k.append(k)
        return {"category": "policy", "operational_domain": "air", "citations": []}

    monkeypatch.setattr(gold_eval_rag, "classify_grounded", fake_grounded)
    out = gold_eval_rag.classify_retry(None, "text", object())

    assert out["category"] == "policy"
    assert seen_k == [gold_eval_rag.RETRIEVE_K]  # the configured k is threaded through


def test_classify_retry_recovers_after_transient_error(monkeypatch, patch_transient):
    attempts = {"n": 0}

    def flaky(_client, _text, _retriever, k):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise _FakeServerError("boom")
        return {"category": "industry", "operational_domain": "land", "citations": []}

    monkeypatch.setattr(gold_eval_rag, "classify_grounded", flaky)
    out = gold_eval_rag.classify_retry(None, "x", object(), max_retries=3)

    assert out["operational_domain"] == "land"
    assert attempts["n"] == 2


def test_classify_retry_reraises_after_exhausting_attempts(
    monkeypatch, patch_transient
):
    def always_429(_client, _text, _retriever, k):
        raise _FakeRateLimit("nope")

    monkeypatch.setattr(gold_eval_rag, "classify_grounded", always_429)
    with pytest.raises(_FakeRateLimit):
        gold_eval_rag.classify_retry(None, "x", object(), max_retries=2)


def test_classify_retry_zero_retries_raises_value_error():
    # range(0) never runs the loop body -> the guard clause fires.
    with pytest.raises(ValueError, match="max_retries must be >= 1"):
        gold_eval_rag.classify_retry(None, "x", object(), max_retries=0)


# --- run_grounded (the grounded-classification loop) ---------------------


def _grounded_df():
    return pd.DataFrame([{"id": "g001", "text": "a"}, {"id": "g002", "text": "b"}])


def test_run_grounded_writes_one_row_per_todo_id(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evals").mkdir()
    monkeypatch.setattr(gold_eval_rag.time, "sleep", lambda *_: None)

    def fake_retry(_client, _text, _retriever):
        return {
            "category": "operations",
            "operational_domain": "sea",
            "citations": [{"id": "news:1"}, {"id": "news:2"}],
        }

    monkeypatch.setattr(gold_eval_rag, "classify_retry", fake_retry)
    gold_eval_rag.run_grounded(object(), _grounded_df(), object(), done_ids=set())

    preds = pd.read_csv(gold_eval_rag.RAG_PREDS_PATH)
    assert list(preds.columns) == [
        "id",
        "rag_category",
        "rag_operational_domain",
        "citations",
    ]
    assert set(preds["id"]) == {"g001", "g002"}
    assert preds.iloc[0]["citations"] == "news:1;news:2"  # ;-joined citation ids


def test_run_grounded_skips_already_done_ids(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evals").mkdir()
    monkeypatch.setattr(gold_eval_rag.time, "sleep", lambda *_: None)

    seen = []

    def fake_retry(_client, text, _retriever):
        seen.append(text)
        return {"category": "policy", "operational_domain": "air", "citations": []}

    monkeypatch.setattr(gold_eval_rag, "classify_retry", fake_retry)
    gold_eval_rag.run_grounded(object(), _grounded_df(), object(), done_ids={"g001"})

    preds = pd.read_csv(gold_eval_rag.RAG_PREDS_PATH)
    assert set(preds["id"]) == {"g002"}  # g001 skipped
    assert seen == ["b"]  # only the not-yet-done row was classified


# --- main() (run branch + resume/skip branch) ----------------------------


def _gold_frame():
    return pd.DataFrame(
        [
            {"id": "g001", "text": "a", "category": "procurement", "domain": "air"},
            {"id": "g002", "text": "b", "category": "operations", "domain": "sea"},
        ]
    )


def _write_baseline():
    pd.DataFrame(
        [
            {
                "id": "g001",
                "pred_category": "procurement",
                "pred_operational_domain": "air",
            },
            {"id": "g002", "pred_category": "policy", "pred_operational_domain": "sea"},
        ]
    ).to_csv(gold_eval_rag.RAG_BASELINE_PREDS_PATH, index=False)


def _grounded_preds_rows():
    return pd.DataFrame(
        [
            {
                "id": "g001",
                "rag_category": "procurement",
                "rag_operational_domain": "air",
                "citations": "news:1",
            },
            {
                "id": "g002",
                "rag_category": "operations",
                "rag_operational_domain": "sea",
                "citations": "news:2",
            },
        ]
    )


def _patch_gold_and_retriever(monkeypatch):
    monkeypatch.setattr(gold_eval_rag, "load_gold", lambda: _gold_frame())
    monkeypatch.setattr(gold_eval_rag, "load_corpus", lambda: [])
    # main() prints len(retriever.docs), so the stand-in needs a `docs` attribute.
    monkeypatch.setattr(
        gold_eval_rag, "Retriever", lambda docs: types.SimpleNamespace(docs=list(docs))
    )


def test_main_runs_grounded_then_writes_report(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evals").mkdir()
    _patch_gold_and_retriever(monkeypatch)
    monkeypatch.setattr(gold_eval_rag, "make_client", lambda: object())
    _write_baseline()

    def fake_run_grounded(_client, _df, _retriever, _done_ids):
        _grounded_preds_rows().to_csv(gold_eval_rag.RAG_PREDS_PATH, index=False)

    monkeypatch.setattr(gold_eval_rag, "run_grounded", fake_run_grounded)

    gold_eval_rag.main()

    report_path = tmp_path / gold_eval_rag.REPORT_PATH
    assert report_path.exists()
    assert "RETRIEVAL-GROUNDED vs BASELINE" in report_path.read_text(encoding="utf-8")


def test_main_skips_api_when_grounded_preds_complete(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evals").mkdir()
    _patch_gold_and_retriever(monkeypatch)
    _write_baseline()
    # complete grounded preds already present -> main() must take the skip branch.
    _grounded_preds_rows().to_csv(gold_eval_rag.RAG_PREDS_PATH, index=False)

    def boom():
        raise AssertionError("make_client must not be called when preds are complete")

    monkeypatch.setattr(gold_eval_rag, "make_client", boom)

    gold_eval_rag.main()  # should not raise -- no API client built
    assert (tmp_path / gold_eval_rag.REPORT_PATH).exists()
