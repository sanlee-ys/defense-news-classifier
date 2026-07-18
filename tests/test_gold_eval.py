"""Tests for src/gold_eval.py (the v2 gold-set eval).

Offline only: gold-set validation and report assembly. The two-model prediction
loop hits the network and is exercised manually, like eval.py's run_predictions.
"""

import csv
import os
import re
import sys

import pandas as pd
import pytest

import gold_eval

GOLD_COLUMNS = ["id", "dvids_id", "source_url", "text", "category", "domain", "region"]


def _row(rid, category, domain, region="global"):
    return {
        "id": rid,
        "dvids_id": "news:1",
        "source_url": "http://example/x",
        "text": "some real defense news snippet text",
        "category": category,
        "domain": domain,
        "region": region,
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


def test_load_gold_rejects_blank_region(tmp_path):
    path = tmp_path / "gold.csv"
    _write_gold(
        path,
        [_row("g001", "procurement", "air"), _row("g002", "operations", "sea", "")],
    )
    with pytest.raises(ValueError):
        gold_eval.load_gold(str(path))


def test_load_gold_rejects_invalid_region(tmp_path):
    # "pacific" is not a label; the axis uses "indo-pacific" (decisions/014).
    path = tmp_path / "gold.csv"
    _write_gold(path, [_row("g001", "procurement", "air", "pacific")])
    with pytest.raises(ValueError, match="region"):
        gold_eval.load_gold(str(path))


# --- build_report ---------------------------------------------------------


def test_build_report_runs_and_reports_accuracy():
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
                "judge_region": "global",
            },
            {
                "id": "g002",
                "category": "operations",
                "operational_domain": "sea",
                "region": "indo-pacific",
                "pred_category": "policy",  # workhorse miss
                "pred_operational_domain": "sea",
                "pred_region": "global",  # workhorse region miss
                "judge_category": "operations",  # judge agrees with human
                "judge_operational_domain": "sea",
                "judge_region": "indo-pacific",
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
        return {"category": "policy", "operational_domain": "multi", "region": "global"}

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
        return {
            "category": "industry",
            "operational_domain": "land",
            "region": "global",
        }

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


def test_retry_recovers_from_a_transient_invalid_label(monkeypatch):
    """Regression guard for the live g014 judge blip (2026-07-18).

    strict:true 'guarantees' schema-valid tool input, but one live call
    returned an input with no category at all and the identical replay was
    clean -- so the harness retries a transient InvalidLabelError instead of
    dying 13 rows into a 54-row pass.
    """
    attempts = {"n": 0}

    def blips_once(_client, _text, model):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise gold_eval.InvalidLabelError("category None is not one of [...]")
        return {
            "category": "operations",
            "operational_domain": "cyber",
            "region": "indo-pacific",
        }

    monkeypatch.setattr(gold_eval, "classify", blips_once)
    result = gold_eval.classify_retry(None, "x", "claude-opus-4-8", max_retries=3)

    assert result["region"] == "indo-pacific"
    assert attempts["n"] == 2


def test_retry_reraises_a_persistent_invalid_label(monkeypatch):
    # A blip that never clears is a real API regression -- it must surface,
    # not spin forever.
    def always_invalid(_client, _text, model):
        raise gold_eval.InvalidLabelError("category None is not one of [...]")

    monkeypatch.setattr(gold_eval, "classify", always_invalid)
    with pytest.raises(gold_eval.InvalidLabelError):
        gold_eval.classify_retry(None, "x", "claude-opus-4-8", max_retries=2)


def test_retry_raises_value_error_when_max_retries_is_zero():
    # range(0) never runs the loop body, so classify is never called at all —
    # this is a pure guard-clause test, no fake needed for classify itself.
    with pytest.raises(ValueError, match="max_retries must be >= 1"):
        gold_eval.classify_retry(None, "x", "claude-sonnet-4-6", max_retries=0)


# --- main() + run_predictions (end-to-end on a tiny gold set) --------------


def test_main_runs_predictions_and_writes_all_outputs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["gold_eval.py"]
    )  # keep argparse off pytest's argv
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
            "region": "global",
        },
    )

    gold_eval.main()

    preds = pd.read_csv(tmp_path / gold_eval.PREDS_PATH)
    assert len(preds) == 2
    assert set(preds["id"]) == {"g001", "g002"}
    assert (tmp_path / gold_eval.REPORT_PATH).exists()


def test_main_skips_api_when_predictions_already_complete(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["gold_eval.py"]
    )  # keep argparse off pytest's argv
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
                "pred_region": "global",
                "judge_category": "procurement",
                "judge_operational_domain": "air",
                "judge_region": "global",
            },
            {
                "id": "g002",
                "pred_category": "operations",
                "pred_operational_domain": "sea",
                "pred_region": "global",
                "judge_category": "operations",
                "judge_operational_domain": "sea",
                "judge_region": "global",
            },
        ]
    ).to_csv(tmp_path / gold_eval.PREDS_PATH, index=False)

    def boom():
        raise AssertionError("make_client must not be called when preds are complete")

    monkeypatch.setattr(gold_eval, "make_client", boom)

    gold_eval.main()  # should not raise — no API client built

    assert (tmp_path / gold_eval.REPORT_PATH).exists()


# --- run_predictions_batch (Message Batches API path) ----------------------


def _gold_df():
    return pd.DataFrame(
        [_row("g001", "procurement", "air"), _row("g002", "operations", "sea")]
    )


def test_run_predictions_batch_writes_one_combined_row_per_gold_id(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)
    os.makedirs("evals", exist_ok=True)
    df = _gold_df()

    client = batch_client(
        {
            "g001__workhorse": {
                "category": "procurement",
                "operational_domain": "air",
                "region": "global",
            },
            "g001__judge": {
                "category": "procurement",
                "operational_domain": "air",
                "region": "global",
            },
            "g002__workhorse": {
                "category": "policy",
                "operational_domain": "sea",
                "region": "global",
            },
            "g002__judge": {
                "category": "operations",
                "operational_domain": "sea",
                "region": "global",
            },
        }
    )
    gold_eval.run_predictions_batch(client, df, done_ids=set())

    preds = pd.read_csv(gold_eval.PREDS_PATH)
    assert len(preds) == 2
    row = preds[preds["id"] == "g001"].iloc[0]
    assert row["pred_category"] == "procurement"
    assert row["judge_category"] == "procurement"
    row2 = preds[preds["id"] == "g002"].iloc[0]
    assert row2["pred_category"] == "policy"
    assert row2["judge_category"] == "operations"


def test_run_predictions_batch_submits_both_models_for_each_todo_row(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)
    os.makedirs("evals", exist_ok=True)
    df = _gold_df()

    client = batch_client(
        {
            "g002__workhorse": {
                "category": "policy",
                "operational_domain": "sea",
                "region": "global",
            },
            "g002__judge": {
                "category": "operations",
                "operational_domain": "sea",
                "region": "global",
            },
        }
    )
    gold_eval.run_predictions_batch(client, df, done_ids={"g001"})

    submitted = client.messages.batches.created_requests
    submitted_ids = {r["custom_id"] for r in submitted}
    assert submitted_ids == {"g002__workhorse", "g002__judge"}
    models = {r["custom_id"]: r["params"]["model"] for r in submitted}
    assert models["g002__workhorse"] == gold_eval.WORKHORSE_MODEL
    assert models["g002__judge"] == gold_eval.JUDGE_MODEL


def test_run_predictions_batch_drops_row_if_either_model_errors(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)
    os.makedirs("evals", exist_ok=True)
    df = _gold_df()

    client = batch_client(
        {
            "g001__workhorse": {
                "category": "procurement",
                "operational_domain": "air",
                "region": "global",
            },
            "g001__judge": "errored",  # one model failed for g001
            "g002__workhorse": {
                "category": "policy",
                "operational_domain": "sea",
                "region": "global",
            },
            "g002__judge": {
                "category": "operations",
                "operational_domain": "sea",
                "region": "global",
            },
        }
    )
    gold_eval.run_predictions_batch(client, df, done_ids=set())

    preds = pd.read_csv(gold_eval.PREDS_PATH)
    # g001 is dropped entirely (half a row is worse than no row -- it stays todo).
    assert set(preds["id"]) == {"g002"}


def test_run_predictions_batch_noop_when_nothing_todo(
    monkeypatch, batch_client, tmp_path
):
    monkeypatch.chdir(tmp_path)
    df = _gold_df()

    def boom(requests):
        raise AssertionError("must not submit a batch when everything is already done")

    client = batch_client({})
    client.messages.batches.create = boom
    gold_eval.run_predictions_batch(
        client, df, done_ids={"g001", "g002"}
    )  # should not raise


def test_main_batch_flag_calls_run_predictions_batch(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["gold_eval.py", "--batch"])
    (tmp_path / "data" / "gold").mkdir(parents=True)
    _write_gold(
        tmp_path / "data" / "gold" / "gold.csv",
        [_row("g001", "procurement", "air"), _row("g002", "operations", "sea")],
    )

    monkeypatch.setattr(gold_eval, "make_client", lambda: object())

    called = {}

    def fake_batch(_client, _df, _done_ids):
        called["yes"] = True
        pd.DataFrame(
            [
                {
                    "id": "g001",
                    "pred_category": "procurement",
                    "pred_operational_domain": "air",
                    "pred_region": "global",
                    "judge_category": "procurement",
                    "judge_operational_domain": "air",
                    "judge_region": "global",
                },
                {
                    "id": "g002",
                    "pred_category": "operations",
                    "pred_operational_domain": "sea",
                    "pred_region": "global",
                    "judge_category": "operations",
                    "judge_operational_domain": "sea",
                    "judge_region": "global",
                },
            ]
        ).to_csv(gold_eval.PREDS_PATH, index=False)

    monkeypatch.setattr(gold_eval, "run_predictions_batch", fake_batch)

    def boom(*_a, **_kw):
        raise AssertionError("--batch must not fall through to run_predictions")

    monkeypatch.setattr(gold_eval, "run_predictions", boom)

    gold_eval.main()
    assert called == {"yes": True}
    assert (tmp_path / gold_eval.REPORT_PATH).exists()


def test_batch_custom_ids_match_the_anthropic_pattern():
    """Batch custom_ids must satisfy ^[a-zA-Z0-9_-]{1,64}$ (the "::" separator did not).

    Regression guard: the previous separator produced ids like ``s001::workhorse``,
    which the Batches API rejects with a 400 -- only surfaced the first time a real
    (non-faked) batch was submitted. This keeps the separator API-legal and round-trips.
    """
    pattern = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
    for which in ("workhorse", "judge"):
        cid = f"s001{gold_eval._BATCH_ID_SEP}{which}"
        assert pattern.match(cid), f"illegal custom_id: {cid!r}"
        row_id, _, parsed = cid.rpartition(gold_eval._BATCH_ID_SEP)
        assert (row_id, parsed) == ("s001", which)
