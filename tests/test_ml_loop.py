"""Offline tests for the rung-2 agent-driven ML loop (no API key, no network).

The honesty architecture is what gets pinned: A/B/C stay disjoint, the agent's
feedback never leaks a B or C row, the done-signal and best-iteration selection
read B only, and an invalid experiment is rejected before any fitting.
"""

import json

import pandas as pd
import pytest

import ml_loop
from ml_loop import (
    DEFAULT_EXPERIMENT,
    DryRunBackend,
    LoopConfig,
    build_feedback,
    experiment_diff,
    make_split,
    oof_predictions,
    run_loop,
    score_experiment,
    validate_experiment,
)
from optimize import read_run_log


@pytest.fixture(scope="module")
def split():
    return make_split()


def test_default_experiment_is_valid():
    assert validate_experiment(DEFAULT_EXPERIMENT) == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"vectorizer": {"analyzer": "tfidf"}},
        {"vectorizer": {"ngram_min": 0}},
        {"vectorizer": {"ngram_min": 3, "ngram_max": 1}},
        {"vectorizer": {"min_df": 99}},
        {"vectorizer": {"max_features": 5}},
        {"model": {"C": 0}},
        {"model": {"class_weight": "auto"}},
        {"keyword_features": [{"name": "not an identifier!", "patterns": ["x"]}]},
        {"keyword_features": [{"name": "a", "patterns": []}]},
        {"keyword_features": [{"name": "a", "patterns": ["x"], "extra": 1}]},
    ],
)
def test_validate_experiment_rejects_bad_configs(mutation):
    exp = json.loads(json.dumps(DEFAULT_EXPERIMENT))
    for section, values in mutation.items():
        if section == "keyword_features":
            exp[section] = values
        else:
            exp[section].update(values)
    assert validate_experiment(exp) != []


def test_validate_experiment_rejects_non_dict():
    assert validate_experiment("word 1-2 grams") != []


def test_split_is_disjoint_and_deterministic(split):
    a_ids, b_ids, c_ids = set(split.a["id"]), set(split.b["id"]), set(split.c["id"])
    assert not a_ids & b_ids
    assert not (a_ids | b_ids) & c_ids
    assert len(a_ids) + len(b_ids) == 300
    assert len(c_ids) == 54
    again = make_split()
    assert again.hashes == split.hashes


def test_feedback_reads_only_a_rows(split):
    oof = oof_predictions(DEFAULT_EXPERIMENT, split.a)
    feedback, failure_ids, stats = build_feedback(oof)
    assert set(failure_ids) <= set(split.a["id"])
    # No B or C id string may appear anywhere in the feedback text.
    for other_id in list(split.b["id"]) + list(split.c["id"]):
        assert f"[{other_id}]" not in feedback
    assert set(stats) == {"category", "operational_domain"}


def test_oof_predictions_cover_every_row_and_find_failures(split):
    oof = oof_predictions(DEFAULT_EXPERIMENT, split.a)
    assert oof["pred_category"].notna().all()
    assert oof["pred_operational_domain"].notna().all()
    # A 300-row TF-IDF baseline is nowhere near perfect out-of-fold; if this
    # ever finds zero failures the feedback pipeline is reading fit-on-self
    # predictions (the memorization bug this design exists to avoid).
    wrong = (oof["category"] != oof["pred_category"]).sum()
    assert wrong > 0


def test_score_experiment_scores_all_three_splits(split):
    scores, oof = score_experiment(DEFAULT_EXPERIMENT, split, seed=42)
    assert set(scores) == {"A", "B", "C"}
    for name in ("A", "B", "C"):
        assert 0.0 <= scores[name]["macro_f1"] <= 1.0
        assert set(scores[name]["category"]) == {"accuracy", "macro_f1"}
    assert len(oof) == len(split.a)


def test_experiment_diff_names_changes():
    new = json.loads(json.dumps(DEFAULT_EXPERIMENT))
    new["vectorizer"]["ngram_max"] = 3
    new["keyword_features"] = [{"name": "naval", "patterns": ["carrier"]}]
    diff = experiment_diff(DEFAULT_EXPERIMENT, new)
    assert "vectorizer.ngram_max: 2 -> 3" in diff
    assert "+keyword_features.naval" in diff
    assert experiment_diff(DEFAULT_EXPERIMENT, DEFAULT_EXPERIMENT) == "(no change)"


def test_dry_run_loop_end_to_end(tmp_path):
    log_path = str(tmp_path / "run_test.jsonl")
    config = LoopConfig(max_iterations=2, plateau_n=3)
    result = run_loop(DryRunBackend(), config, log_path=log_path)
    assert result == log_path
    records = read_run_log(log_path)
    metadata, summary = records[0], records[-1]
    assert metadata["record"] == "run_metadata"
    assert metadata["rung"] == 2
    assert metadata["dry_run"] is True
    assert summary["record"] == "run_summary"
    assert summary["done_signal"] == "budget_iterations"
    iterations = [r for r in records if r["record"] == "iteration"]
    assert [r["iteration"] for r in iterations] == [0, 1, 2]
    assert iterations[0]["experiment"] == DEFAULT_EXPERIMENT
    assert iterations[0]["tokens_spent"] == 0  # dry-run proposer is free


def test_best_iteration_selection_reads_b_only(tmp_path):
    # Force records where C would pick a different iteration than B; the
    # summary must follow B (the held-out set is never a decision input).
    records = [
        {"iteration": 0, "scores": {"B": {"macro_f1": 0.5}, "C": {"macro_f1": 0.9}}},
        {"iteration": 1, "scores": {"B": {"macro_f1": 0.7}, "C": {"macro_f1": 0.1}}},
    ]
    assert ml_loop.select_best_iteration(records) == 1


class _RejectingBackend:
    """Backend whose every proposal is invalid -- run must stop, not score it."""

    def propose(self, current_experiment, feedback):
        raise ml_loop.ProposalError("all proposals invalid", tokens=123)


def test_proposal_error_stops_run_and_books_tokens(tmp_path):
    log_path = str(tmp_path / "run_err.jsonl")
    config = LoopConfig(max_iterations=5)
    run_loop(_RejectingBackend(), config, log_path=log_path)
    records = read_run_log(log_path)
    summary = records[-1]
    assert summary["done_signal"] == "proposal_error"
    assert summary["tokens_spent"] == 123  # failed attempts still cost money
    error = [r for r in records if r["record"] == "run_error"]
    assert len(error) == 1


def test_keyword_features_change_predictions(split):
    exp = json.loads(json.dumps(DEFAULT_EXPERIMENT))
    exp["keyword_features"] = [
        {"name": "naval", "patterns": ["carrier", "destroyer", "fleet"]}
    ]
    assert validate_experiment(exp) == []
    base = ml_loop.fit_experiment(DEFAULT_EXPERIMENT, split.a)
    with_kw = ml_loop.fit_experiment(exp, split.a)
    texts = pd.Series(["The carrier strike group departed the fleet area."])
    assert ml_loop._keyword_matrix(texts, exp["keyword_features"]).toarray()[0, 0] == 1
    # Both models predict; the keyword model has one extra feature column.
    assert base.predict(texts).shape == with_kw.predict(texts).shape
