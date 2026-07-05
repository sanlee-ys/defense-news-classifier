"""Tests for src/gold_eval.py (the v2 gold-set eval).

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


# --- classify_retry --------------------------------------------------------


class _FakeRateLimit(Exception):
    pass


class _FakeServerError(Exception):
    pass


@pytest.fixture(autouse=True)
def patch_anthropic_errors(monkeypatch):
    """Swap the SDK exception classes for plain ones we can raise freely.

    Also replaces time.sleep so the retry backoff doesn't actually wait.
    """
    monkeypatch.setattr(gold_eval.anthropic, "RateLimitError", _FakeRateLimit)
    monkeypatch.setattr(gold_eval.anthropic, "InternalServerError", _FakeServerError)
    monkeypatch.setattr(gold_eval.time, "sleep", lambda *_: None)


def test_retry_returns_on_first_success(monkeypatch):
    calls = []

    def fake_classify(client, text, model):
        calls.append((text, model))
        return {"category": "policy", "operational_domain": "multi"}

    monkeypatch.setattr(gold_eval, "classify", fake_classify)
    result = gold_eval.classify_retry(None, "some article text", "claude-sonnet-4-6")

    assert result["category"] == "policy"
    assert len(calls) == 1


def test_retry_recovers_after_transient_errors(monkeypatch):
    attempts = {"n": 0}

    def flaky_classify(client, text, model):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _FakeServerError("boom")
        return {"category": "industry", "operational_domain": "land"}

    monkeypatch.setattr(gold_eval, "classify", flaky_classify)
    result = gold_eval.classify_retry(None, "x", "claude-sonnet-4-6", max_retries=3)

    assert result["operational_domain"] == "land"
    assert attempts["n"] == 3


def test_retry_reraises_after_exhausting_attempts(monkeypatch):
    def always_fails(_client, _text, model):
        raise _FakeRateLimit("nope")

    monkeypatch.setattr(gold_eval, "classify", always_fails)
    with pytest.raises(_FakeRateLimit):
        gold_eval.classify_retry(None, "x", "claude-sonnet-4-6", max_retries=2)


def test_retry_raises_value_error_when_max_retries_is_zero():
    # range(0) never runs the loop body, so classify is never called at all —
    # this is a pure guard-clause test, no fake needed for classify itself.
    with pytest.raises(ValueError, match="max_retries must be >= 1"):
        gold_eval.classify_retry(None, "x", "claude-sonnet-4-6", max_retries=0)


# --- main() + run_predictions (end-to-end on a tiny gold set) --------------


def test_main_runs_predictions_and_writes_all_outputs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "gold").mkdir(parents=True)
    _write_gold(
        tmp_path / "data" / "gold" / "gold.csv",
        [_row("g001", "procurement", "air"), _row("g002", "operations", "sea")],
    )

    monkeypatch.setattr(gold_eval, "make_client", lambda: object())
    monkeypatch.setattr(
        gold_eval,
        "classify",
        lambda _client, _text, model: {
            "category": "procurement",
            "operational_domain": "air",
        },
    )

    gold_eval.main()

    preds = pd.read_csv(tmp_path / "evals" / "gold_predictions.csv")
    assert len(preds) == 2
    assert set(preds["id"]) == {"g001", "g002"}
    assert (tmp_path / "evals" / "gold_eval.txt").exists()


def test_main_skips_api_when_predictions_already_complete(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "gold").mkdir(parents=True)
    _write_gold(
        tmp_path / "data" / "gold" / "gold.csv",
        [_row("g001", "procurement", "air"), _row("g002", "operations", "sea")],
    )

    # Pre-seed a complete predictions file so main() takes the resume/skip branch.
    (tmp_path / "evals").mkdir()
    pd.DataFrame(
        [
            {
                "id": "g001",
                "pred_category": "procurement",
                "pred_operational_domain": "air",
                "judge_category": "procurement",
                "judge_operational_domain": "air",
            },
            {
                "id": "g002",
                "pred_category": "operations",
                "pred_operational_domain": "sea",
                "judge_category": "operations",
                "judge_operational_domain": "sea",
            },
        ]
    ).to_csv(tmp_path / "evals" / "gold_predictions.csv", index=False)

    def boom():
        raise AssertionError("make_client must not be called when preds are complete")

    monkeypatch.setattr(gold_eval, "make_client", boom)

    gold_eval.main()  # should not raise — no API client built

    assert (tmp_path / "evals" / "gold_eval.txt").exists()
