"""
Tests for src/eval.py.

Covers the pure metric functions (precision/recall/F1, confusion matrix,
report text) on hand-built frames where the right answer is obvious, plus
the retry wrapper around the classifier.
"""

import pandas as pd
import pytest

import eval as evalmod


def _frame(rows):
    """Build a merged-style frame from (true_cat, pred_cat) tuples."""
    return pd.DataFrame(
        [{"category": t, "pred_category": p} for t, p in rows]
    )


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
    """rows = (cat, pred_cat, dom, pred_dom)."""
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
    df = _full_frame([
        ("procurement", "procurement", "air", "air"),     # both right
        ("operations", "policy", "land", "land"),          # category wrong
        ("policy", "policy", "sea", "air"),                # domain wrong
        ("technology", "technology", "cyber", "cyber"),    # both right
    ])
    report = evalmod.build_report(df)

    assert "Articles evaluated : 4" in report
    assert "Category accuracy           : 75.0%" in report   # 3/4
    assert "Operational domain accuracy : 75.0%" in report   # 3/4
    # Two rows have at least one wrong field.
    assert "Misclassified : 2 / 4" in report


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

    def fake_classify(client, text):
        calls.append(text)
        return {"category": "policy", "operational_domain": "multi"}

    monkeypatch.setattr(evalmod, "classify", fake_classify)
    result = evalmod.classify_with_retry(None, "x")
    assert result["category"] == "policy"
    assert len(calls) == 1


def test_retry_recovers_after_transient_errors(monkeypatch):
    attempts = {"n": 0}

    def flaky_classify(client, text):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _FakeServerError("boom")
        return {"category": "industry", "operational_domain": "land"}

    monkeypatch.setattr(evalmod, "classify", flaky_classify)
    result = evalmod.classify_with_retry(None, "x", max_retries=3)
    assert result["operational_domain"] == "land"
    assert attempts["n"] == 3


def test_retry_reraises_after_exhausting_attempts(monkeypatch):
    def always_fails(client, text):
        raise _FakeRateLimit("nope")

    monkeypatch.setattr(evalmod, "classify", always_fails)
    with pytest.raises(_FakeRateLimit):
        evalmod.classify_with_retry(None, "x", max_retries=2)
