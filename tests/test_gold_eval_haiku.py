"""Tests for src/gold_eval_haiku.py (the Haiku eval arm).

Offline only: metric/flip/report assembly and the batch-path plumbing. The
synchronous prediction loop hits the network and is exercised manually, like
gold_eval.py's run_predictions.
"""

import os
import sys

import pandas as pd

import gold_eval_haiku


def _merged(rows):
    """Build a merged frame with human + baseline (pred_*) + Haiku (haiku_*) cols."""
    return pd.DataFrame(rows)


# --- metrics + flips ------------------------------------------------------


def test_metrics_reports_delta_and_flips():
    merged = _merged(
        [
            # Haiku matches baseline & human -> no change, both right
            {
                "id": "g001",
                "category": "procurement",
                "operational_domain": "air",
                "pred_category": "procurement",
                "pred_operational_domain": "air",
                "haiku_category": "procurement",
                "haiku_operational_domain": "air",
            },
            # Sonnet right, Haiku wrong -> the escalation gap (haiku_worse)
            {
                "id": "g002",
                "category": "operations",
                "operational_domain": "sea",
                "pred_category": "operations",
                "pred_operational_domain": "sea",
                "haiku_category": "policy",
                "haiku_operational_domain": "sea",
            },
            # Sonnet wrong, Haiku right -> Haiku better
            {
                "id": "g003",
                "category": "industry",
                "operational_domain": "land",
                "pred_category": "procurement",
                "pred_operational_domain": "land",
                "haiku_category": "industry",
                "haiku_operational_domain": "land",
            },
        ]
    )
    m = gold_eval_haiku.metrics(merged)

    assert m["n"] == 3
    # category: baseline 2/3 right, haiku 2/3 right (g002 miss, g003 fix)
    assert m["category_accuracy_baseline"] == 2 / 3
    assert m["category_accuracy_haiku"] == 2 / 3
    flip = m["category_flip"]
    assert flip["changed"] == 2  # g002 and g003 differ from baseline
    assert flip["haiku_better"] == 1  # g003
    assert flip["haiku_worse"] == 1  # g002
    assert flip["lateral"] == 0


def test_build_report_runs_and_labels_arms():
    merged = _merged(
        [
            {
                "id": "g001",
                "category": "procurement",
                "operational_domain": "air",
                "pred_category": "procurement",
                "pred_operational_domain": "air",
                "haiku_category": "procurement",
                "haiku_operational_domain": "air",
            },
        ]
    )
    report = gold_eval_haiku.build_report(merged)
    assert "HAIKU EVAL ARM" in report
    assert gold_eval_haiku.HAIKU_MODEL in report
    assert gold_eval_haiku.WORKHORSE_MODEL in report
    assert "escalating from Haiku to Sonnet" in report


# --- batch path -----------------------------------------------------------


def _gold_df():
    return pd.DataFrame(
        [
            {"id": "g001", "text": "a", "category": "procurement", "domain": "air"},
            {"id": "g002", "text": "b", "category": "operations", "domain": "sea"},
        ]
    )


def test_run_predictions_batch_writes_one_row_per_id(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)
    os.makedirs("evals", exist_ok=True)
    client = batch_client(
        {
            "g001": {"category": "procurement", "operational_domain": "air"},
            "g002": {"category": "policy", "operational_domain": "sea"},
        }
    )
    gold_eval_haiku.run_predictions_batch(client, _gold_df(), done_ids=set())

    preds = pd.read_csv(gold_eval_haiku.HAIKU_PREDS_PATH)
    assert set(preds["id"]) == {"g001", "g002"}
    assert preds[preds["id"] == "g002"].iloc[0]["haiku_category"] == "policy"


def test_run_predictions_batch_submits_haiku_model_for_todo_rows(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)
    os.makedirs("evals", exist_ok=True)
    client = batch_client({"g002": {"category": "policy", "operational_domain": "sea"}})
    gold_eval_haiku.run_predictions_batch(client, _gold_df(), done_ids={"g001"})

    submitted = client.messages.batches.created_requests
    assert {r["custom_id"] for r in submitted} == {"g002"}
    assert submitted[0]["params"]["model"] == gold_eval_haiku.HAIKU_MODEL


def test_run_predictions_batch_skips_errored_item(monkeypatch, batch_client, tmp_path):
    monkeypatch.chdir(tmp_path)
    os.makedirs("evals", exist_ok=True)
    client = batch_client(
        {
            "g001": "errored",
            "g002": {"category": "operations", "operational_domain": "sea"},
        }
    )
    gold_eval_haiku.run_predictions_batch(client, _gold_df(), done_ids=set())

    preds = pd.read_csv(gold_eval_haiku.HAIKU_PREDS_PATH)
    assert set(preds["id"]) == {"g002"}


def test_run_predictions_batch_noop_when_nothing_todo(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)

    def boom(requests):
        raise AssertionError("must not submit a batch when everything is done")

    client = batch_client({})
    client.messages.batches.create = boom
    gold_eval_haiku.run_predictions_batch(
        client, _gold_df(), done_ids={"g001", "g002"}
    )  # should not raise


# --- main() skip branch ---------------------------------------------------


def test_main_skips_api_when_predictions_complete(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["gold_eval_haiku.py"])
    (tmp_path / "data" / "gold").mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "id": "g001",
                "dvids_id": "news:1",
                "source_url": "http://x/1",
                "text": "t1",
                "category": "procurement",
                "domain": "air",
            },
            {
                "id": "g002",
                "dvids_id": "news:2",
                "source_url": "http://x/2",
                "text": "t2",
                "category": "operations",
                "domain": "sea",
            },
        ]
    ).to_csv(tmp_path / "data" / "gold" / "gold.csv", index=False)

    (tmp_path / "evals").mkdir()
    # committed Sonnet baseline
    pd.DataFrame(
        [
            {
                "id": "g001",
                "pred_category": "procurement",
                "pred_operational_domain": "air",
            },
            {
                "id": "g002",
                "pred_category": "operations",
                "pred_operational_domain": "sea",
            },
        ]
    ).to_csv(tmp_path / "evals" / "gold_predictions.csv", index=False)
    # complete Haiku preds -> main() takes the skip branch
    pd.DataFrame(
        [
            {
                "id": "g001",
                "haiku_category": "procurement",
                "haiku_operational_domain": "air",
            },
            {
                "id": "g002",
                "haiku_category": "policy",
                "haiku_operational_domain": "sea",
            },
        ]
    ).to_csv(
        tmp_path / "evals" / gold_eval_haiku.HAIKU_PREDS_PATH.split("/")[-1],
        index=False,
    )

    def boom():
        raise AssertionError("make_client must not be called when preds are complete")

    monkeypatch.setattr(gold_eval_haiku, "make_client", boom)

    gold_eval_haiku.main()  # should not raise
    assert (tmp_path / "evals" / "gold_haiku_eval.txt").exists()
