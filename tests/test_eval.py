"""Tests for src/eval.py.

Covers the pure metric functions (precision/recall/F1, confusion matrix,
report text) on hand-built frames where the right answer is obvious, plus
the retry wrapper around the classifier.
"""

import os
import sys

import pandas as pd
import pytest

import eval as evalmod


def _frame(rows):
    """Build a merged-style frame from (true_cat, pred_cat) tuples."""
    return pd.DataFrame([{"category": t, "pred_category": p} for t, p in rows])


# --- compute_metrics -----------------------------------------------------


def test_perfect_predictions_give_unit_scores():
    df = _frame([("air", "air"), ("air", "air"), ("land", "land")])
    # category values are reused as labels here for simplicity
    m = evalmod.compute_metrics(df, "category")
    assert m.loc["air", "precision"] == 1.0
    assert m.loc["air", "recall"] == 1.0
    assert m.loc["air", "f1"] == 1.0
    assert m.loc["air", "support"] == 2


def test_metrics_match_hand_computed_values():
    # "a": 2 correct, "a" also predicted once when truth was "b" -> 1 FP.
    #   precision = 2/3, recall = 2/2 = 1.0
    # "b": truth twice, predicted "a" once and "b" once -> 1 TP, 1 FN, 0 FP.
    #   precision = 1.0, recall = 1/2 = 0.5
    df = _frame([("a", "a"), ("a", "a"), ("b", "a"), ("b", "b")])
    m = evalmod.compute_metrics(df, "category")

    assert m.loc["a", "precision"] == round(2 / 3, 3)
    assert m.loc["a", "recall"] == 1.0
    assert m.loc["b", "precision"] == 1.0
    assert m.loc["b", "recall"] == 0.5
    # F1 for "b": harmonic mean of 1.0 and 0.5
    assert m.loc["b", "f1"] == round(2 * 1.0 * 0.5 / 1.5, 3)


def test_label_never_predicted_has_zero_precision_not_nan():
    # "b" is the true label but never predicted -> no TP/FP, recall 0, precision 0.
    df = _frame([("a", "a"), ("b", "a")])
    m = evalmod.compute_metrics(df, "category")
    assert m.loc["b", "precision"] == 0.0
    assert m.loc["b", "recall"] == 0.0
    assert m.loc["b", "f1"] == 0.0


def test_support_sums_to_row_count():
    df = _frame([("a", "a"), ("a", "b"), ("b", "b"), ("c", "c")])
    m = evalmod.compute_metrics(df, "category")
    assert m["support"].sum() == len(df)


# --- macro_average -------------------------------------------------------


def test_macro_average_is_unweighted_mean_of_per_label_metrics():
    # "a": 1 TP, 1 FP, 0 FN -> P=0.5, R=1.0, F1=0.667.
    # "b": 1 TP, 0 FP, 1 FN -> P=1.0, R=0.5, F1=0.667.
    df = _frame([("a", "a"), ("b", "a"), ("b", "b")])
    m = evalmod.compute_metrics(df, "category")
    macro = evalmod.macro_average(m)
    # Macro = unweighted mean across labels (support ignored).
    assert macro["precision"] == round((0.5 + 1.0) / 2, 3)  # 0.75
    assert macro["recall"] == round((1.0 + 0.5) / 2, 3)  # 0.75
    assert macro["f1"] == round((0.667 + 0.667) / 2, 3)  # 0.667


def test_macro_average_penalizes_collapsed_class_below_accuracy():
    # 9 correct "a" plus 1 "b" always missed: accuracy 0.9, but "b" F1 = 0,
    # so macro-F1 is dragged well below the accuracy number.
    df = _frame([("a", "a")] * 9 + [("b", "a")])
    m = evalmod.compute_metrics(df, "category")
    macro = evalmod.macro_average(m)
    assert macro["f1"] < 0.9


# --- confusion_matrix ----------------------------------------------------


def test_confusion_matrix_is_square_over_all_labels():
    df = _frame([("a", "a"), ("a", "b"), ("b", "b")])
    cm = evalmod.confusion_matrix(df, "category")
    assert list(cm.index) == ["a", "b"]
    assert list(cm.columns) == ["a", "b"]
    assert cm.loc["a", "b"] == 1  # one "a" misclassified as "b"
    assert cm.loc["a", "a"] == 1
    assert cm.loc["b", "b"] == 1


def test_confusion_matrix_diagonal_equals_correct_count():
    df = _frame([("a", "a"), ("a", "a"), ("b", "b"), ("b", "a")])
    cm = evalmod.confusion_matrix(df, "category")
    correct = sum(cm.loc[lbl, lbl] for lbl in cm.index)
    assert correct == int((df["category"] == df["pred_category"]).sum())


# --- build_report --------------------------------------------------------


def _full_frame(rows):
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


def test_report_reports_accuracy_and_counts():
    df = _full_frame(
        [
            ("procurement", "procurement", "air", "air"),  # both right
            ("operations", "policy", "land", "land"),  # category wrong
            ("policy", "policy", "sea", "air"),  # domain wrong
            ("technology", "technology", "cyber", "cyber"),  # both right
        ]
    )
    report = evalmod.build_report(df)

    assert "Articles evaluated : 4" in report
    assert "Category accuracy           : 75.0%" in report  # 3/4
    assert "Operational domain accuracy : 75.0%" in report  # 3/4
    # Two rows have at least one wrong field.
    assert "Misclassified : 2 / 4" in report
    # Macro-F1 is surfaced next to accuracy and under each per-label table.
    assert "macro-F1" in report
    assert "macro avg" in report


# --- classify_with_retry -------------------------------------------------


class _FakeRateLimit(Exception):
    pass


class _FakeServerError(Exception):
    pass


@pytest.fixture(autouse=True)
def patch_anthropic_errors(monkeypatch):
    """Swap the SDK exception classes for plain ones we can raise freely."""
    monkeypatch.setattr(evalmod.anthropic, "RateLimitError", _FakeRateLimit)
    monkeypatch.setattr(evalmod.anthropic, "InternalServerError", _FakeServerError)
    monkeypatch.setattr(evalmod.time, "sleep", lambda *_: None)  # no real waiting


def test_retry_returns_on_first_success(monkeypatch):
    calls = []

    def fake_classify(_client, text):
        calls.append(text)
        return {"category": "policy", "operational_domain": "multi"}

    monkeypatch.setattr(evalmod, "classify", fake_classify)
    result = evalmod.classify_with_retry(None, "x")
    assert result["category"] == "policy"
    assert len(calls) == 1


def test_retry_recovers_after_transient_errors(monkeypatch):
    attempts = {"n": 0}

    def flaky_classify(_client, _text):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _FakeServerError("boom")
        return {"category": "industry", "operational_domain": "land"}

    monkeypatch.setattr(evalmod, "classify", flaky_classify)
    result = evalmod.classify_with_retry(None, "x", max_retries=3)
    assert result["operational_domain"] == "land"
    assert attempts["n"] == 3


def test_retry_reraises_after_exhausting_attempts(monkeypatch):
    def always_fails(_client, _text):
        raise _FakeRateLimit("nope")

    monkeypatch.setattr(evalmod, "classify", always_fails)
    with pytest.raises(_FakeRateLimit):
        evalmod.classify_with_retry(None, "x", max_retries=2)


# --- main() + run_predictions (end-to-end on a tiny dataset) --------------


def _write_dataset(tmp_path):
    """Create data/synthetic_articles.csv under tmp_path and return the frame."""
    (tmp_path / "data").mkdir()
    df = pd.DataFrame(
        [
            {
                "id": 0,
                "text": "Air strike reported.",
                "category": "operations",
                "operational_domain": "air",
            },
            {
                "id": 1,
                "text": "New treaty signed.",
                "category": "policy",
                "operational_domain": "sea",
            },
        ]
    )
    df.to_csv(tmp_path / "data" / "synthetic_articles.csv", index=False)
    return df


def test_main_runs_predictions_and_writes_all_outputs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # DATA_PATH/PREDS_PATH/etc are relative paths
    monkeypatch.setattr(sys, "argv", ["eval.py"])  # argparse must not see pytest's argv
    _write_dataset(tmp_path)

    monkeypatch.setattr(evalmod, "make_client", lambda: object())
    monkeypatch.setattr(evalmod.time, "sleep", lambda *_: None)
    # Predict ground truth for id 0 and a wrong domain for id 1, so the
    # misclassification log has exactly one entry.
    preds = {
        "Air strike reported.": {"category": "operations", "operational_domain": "air"},
        "New treaty signed.": {"category": "policy", "operational_domain": "air"},
    }
    monkeypatch.setattr(evalmod, "classify", lambda _c, text: preds[text])

    evalmod.main()

    pred_df = pd.read_csv(tmp_path / "evals" / "predictions.csv")
    assert len(pred_df) == 2
    assert (tmp_path / "evals" / "metrics.txt").exists()
    assert (tmp_path / "evals" / "confusion_category.csv").exists()
    assert (tmp_path / "evals" / "confusion_domain.csv").exists()

    misc = pd.read_csv(tmp_path / "evals" / "misclassifications.csv")
    assert list(misc["id"]) == [1]  # only id 1 was wrong


def test_main_skips_api_when_predictions_already_complete(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["eval.py"])  # argparse must not see pytest's argv
    _write_dataset(tmp_path)

    # Pre-seed a complete predictions file so the resume branch is taken.
    (tmp_path / "evals").mkdir()
    pd.DataFrame(
        [
            {"id": 0, "pred_category": "operations", "pred_operational_domain": "air"},
            {"id": 1, "pred_category": "policy", "pred_operational_domain": "sea"},
        ]
    ).to_csv(tmp_path / "evals" / "predictions.csv", index=False)

    def boom():
        raise AssertionError("make_client must not be called when preds are complete")

    monkeypatch.setattr(evalmod, "make_client", boom)

    evalmod.main()  # should not raise — no API client built


# --- run_predictions_batch (Message Batches API path) ---------------------


def test_run_predictions_batch_writes_one_row_per_article(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)
    df = _write_dataset(tmp_path)
    os.makedirs("evals", exist_ok=True)

    client = batch_client(
        {
            "0": {"category": "operations", "operational_domain": "air"},
            "1": {"category": "policy", "operational_domain": "sea"},
        }
    )
    evalmod.run_predictions_batch(client, df, done_ids=set())

    preds = pd.read_csv(evalmod.PREDS_PATH)
    assert len(preds) == 2
    assert set(preds["id"]) == {0, 1}


def test_run_predictions_batch_submits_only_todo_rows(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)
    df = _write_dataset(tmp_path)
    os.makedirs("evals", exist_ok=True)

    client = batch_client({"1": {"category": "policy", "operational_domain": "sea"}})
    evalmod.run_predictions_batch(client, df, done_ids={0})

    submitted_ids = {r["custom_id"] for r in client.messages.batches.created_requests}
    assert submitted_ids == {"1"}


def test_run_predictions_batch_skips_a_bad_item_without_aborting(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)
    df = _write_dataset(tmp_path)
    os.makedirs("evals", exist_ok=True)

    client = batch_client(
        {
            "0": {"category": "operations", "operational_domain": "air"},
            "1": "errored",  # batch item failed -- must not crash the whole run
        }
    )
    evalmod.run_predictions_batch(client, df, done_ids=set())

    preds = pd.read_csv(evalmod.PREDS_PATH)
    assert set(preds["id"]) == {0}  # id 1 stays todo, not written


def test_run_predictions_batch_noop_when_nothing_todo(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)
    df = _write_dataset(tmp_path)

    def boom(requests):
        raise AssertionError("must not submit a batch when everything is already done")

    client = batch_client({})
    client.messages.batches.create = boom
    evalmod.run_predictions_batch(client, df, done_ids={0, 1})  # should not raise


def test_main_batch_flag_calls_run_predictions_batch(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["eval.py", "--batch"])
    _write_dataset(tmp_path)

    monkeypatch.setattr(evalmod, "make_client", lambda: object())

    called = {}

    def fake_batch(_client, _df, _done_ids):
        called["yes"] = True
        pd.DataFrame(
            [
                {
                    "id": 0,
                    "pred_category": "operations",
                    "pred_operational_domain": "air",
                },
                {"id": 1, "pred_category": "policy", "pred_operational_domain": "sea"},
            ]
        ).to_csv(evalmod.PREDS_PATH, index=False)

    monkeypatch.setattr(evalmod, "run_predictions_batch", fake_batch)

    def boom(*_a, **_kw):
        raise AssertionError("--batch must not fall through to run_predictions")

    monkeypatch.setattr(evalmod, "run_predictions", boom)

    evalmod.main()
    assert called == {"yes": True}
    assert (tmp_path / "evals" / "metrics.txt").exists()

    assert (tmp_path / "evals" / "metrics.txt").exists()
