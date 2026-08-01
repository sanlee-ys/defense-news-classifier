"""Offline tests for the paired comparison layer (no API key, no network).

Three properties carry the module and are each pinned here: canonicalization
fails loud rather than producing a lossy key, the group key is stable under
irrelevant differences (dict ordering) and content-derived when no id exists,
and the pairing rules exclude exactly what they claim to -- one-sided rows,
duplicates, errors, blanks -- while reporting each exclusion as a diagnostic.
"""

import math

import pandas as pd
import pytest

import paired_compare
from paired_compare import (
    CanonicalizationError,
    Diagnostic,
    DiagnosticReason,
    Observation,
    Outcome,
    canonical_json,
    canonicalize,
    derive_group_key,
    diagnostic_counts,
    load_answer_key,
    observations_from_frame,
    pair_observations,
    summarize_correctness,
    summarize_metric,
)

# ---------------------------------------------------------------------------
# Canonicalization: fail loud, not lossy.
# ---------------------------------------------------------------------------


def test_dict_ordering_does_not_change_the_serialization():
    left = {"text": "a strike package", "id": "g001", "meta": {"b": 1, "a": 2}}
    right = {"meta": {"a": 2, "b": 1}, "id": "g001", "text": "a strike package"}
    assert canonical_json(left) == canonical_json(right)


def test_nested_structures_round_trip_with_sorted_keys():
    canonical = canonicalize({"b": [{"z": 1, "y": 2}], "a": None})
    assert list(canonical) == ["a", "b"]
    assert list(canonical["b"][0]) == ["y", "z"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_rejected(value):
    with pytest.raises(CanonicalizationError, match="finite"):
        canonicalize({"score": value})


def test_circular_references_are_rejected():
    node = {"id": "a"}
    node["self"] = node
    with pytest.raises(CanonicalizationError, match="circular"):
        canonicalize(node)

    row = []
    row.append(row)
    with pytest.raises(CanonicalizationError, match="circular"):
        canonicalize(row)


def test_repeated_but_acyclic_references_are_fine():
    # The same object twice is not a cycle; a naive "seen" set would reject it.
    shared = {"a": 1}
    assert canonical_json({"x": shared, "y": shared}) == '{"x":{"a":1},"y":{"a":1}}'


@pytest.mark.parametrize(
    "value",
    [
        ("a", "b"),
        {"a", "b"},
        object(),
        {"nested": ("a",)},
    ],
)
def test_non_plain_containers_are_rejected(value):
    with pytest.raises(CanonicalizationError):
        canonicalize(value)


def test_non_string_mapping_keys_are_rejected():
    with pytest.raises(CanonicalizationError, match="keys must be strings"):
        canonicalize({1: "one"})


# ---------------------------------------------------------------------------
# Group keys.
# ---------------------------------------------------------------------------


def test_explicit_id_wins_and_is_trimmed():
    assert derive_group_key({"id": "  g001 ", "text": "x"}) == "g001"


def test_missing_id_falls_back_to_a_content_hash():
    left = {"text": "a strike package", "source": "dvids"}
    right = {"source": "dvids", "text": "a strike package"}
    key = derive_group_key(left)
    assert len(key) == 64 and key == derive_group_key(right)
    assert key != derive_group_key({"text": "something else", "source": "dvids"})


def test_blank_id_falls_back_to_the_content_hash():
    # A blank id is not an identity -- two blank-id rows must not collide into
    # one group just because the column was empty.
    left = derive_group_key({"id": "   ", "text": "alpha"})
    right = derive_group_key({"id": "", "text": "bravo"})
    assert len(left) == 64 and len(right) == 64
    assert left != right


def test_unhashable_record_without_an_id_fails_loud():
    with pytest.raises(CanonicalizationError):
        derive_group_key({"text": "alpha", "score": math.nan})


# ---------------------------------------------------------------------------
# Pairing rules.
# ---------------------------------------------------------------------------


def scored(group_key, arm, score):
    return Observation(group_key, arm, Outcome.SCORED, score=score)


def test_one_sided_observation_is_excluded_and_flagged():
    result = pair_observations(
        [scored("g001", "base", 1.0), scored("g002", "base", 0.0)],
        [scored("g001", "cand", 1.0)],
    )
    assert [pair.group_key for pair in result.pairs] == ["g001"]
    assert result.total_groups == 2
    assert result.diagnostics == [
        Diagnostic(
            "g002",
            "cand",
            DiagnosticReason.MISSING_OBSERVATION,
            "no observation from candidate arm",
        )
    ]
    lift = summarize_correctness(result.pairs)
    assert lift.total_pairs == 1 and lift.eligible_pairs == 1


def test_duplicate_observation_drops_the_group_and_is_flagged():
    result = pair_observations(
        [scored("g001", "base", 1.0), scored("g001", "base", 0.0)],
        [scored("g001", "cand", 1.0)],
    )
    assert result.pairs == []
    assert [d.reason for d in result.diagnostics] == [
        DiagnosticReason.DUPLICATE_OBSERVATION
    ]
    assert "2 observations" in result.diagnostics[0].detail


def test_errored_and_blank_sides_are_paired_but_never_scored():
    result = pair_observations(
        [
            scored("g001", "base", 1.0),
            Observation("g002", "base", Outcome.ERRORED, detail="500"),
            scored("g003", "base", 1.0),
        ],
        [
            scored("g001", "cand", 0.0),
            scored("g002", "cand", 1.0),
            Observation("g003", "cand", Outcome.UNSCORED),
        ],
    )
    assert len(result.pairs) == 3
    lift = summarize_correctness(result.pairs)
    # Only g001 has both sides scored, so the rates are over n=1, not n=3 --
    # the errored and blank rows are excluded, not imputed as failures.
    assert lift.total_pairs == 3
    assert lift.eligible_pairs == 1
    assert lift.baseline_pass_rate == 1.0
    assert lift.candidate_pass_rate == 0.0
    assert lift.lift == -1.0
    counts = diagnostic_counts(result.diagnostics)
    assert counts["harness-error"] == 1
    assert counts["missing-score"] == 1
    assert counts["missing-observation"] == 0


def test_unscorable_outcome_is_reported_under_its_own_reason():
    result = pair_observations(
        [Observation("g001", "base", Outcome.UNSCORABLE, detail="no answer key")],
        [scored("g001", "cand", 1.0)],
    )
    assert diagnostic_counts(result.diagnostics)["unscorable-outcome"] == 1
    assert summarize_correctness(result.pairs).eligible_pairs == 0


def test_empty_comparison_reports_none_not_zero():
    lift = summarize_correctness([])
    assert lift.baseline_pass_rate is None
    assert lift.candidate_pass_rate is None
    assert lift.lift is None
    assert lift.p_value == 1.0


def test_wins_ties_and_mcnemar_over_discordant_pairs():
    pairs = pair_observations(
        [scored(f"g{i:03d}", "base", 0.0) for i in range(8)],
        [scored(f"g{i:03d}", "cand", 1.0) for i in range(8)],
    ).pairs
    lift = summarize_correctness(pairs)
    assert (lift.candidate_wins, lift.baseline_wins, lift.ties) == (8, 0, 0)
    assert lift.lift == 1.0
    assert lift.p_value == pytest.approx(0.0078125)


def test_diagnostic_counts_lists_every_reason_even_at_zero():
    counts = diagnostic_counts([])
    assert set(counts) == {reason.value for reason in DiagnosticReason}
    assert set(counts.values()) == {0}


# ---------------------------------------------------------------------------
# Continuous metrics.
# ---------------------------------------------------------------------------


def test_summarize_metric_skips_pairs_missing_a_side():
    pairs = pair_observations(
        [
            Observation("g001", "base", Outcome.SCORED, 1.0, {"latency_ms": 100.0}),
            Observation("g002", "base", Outcome.SCORED, 1.0, {}),
        ],
        [
            Observation("g001", "cand", Outcome.SCORED, 1.0, {"latency_ms": 80.0}),
            Observation("g002", "cand", Outcome.SCORED, 1.0, {"latency_ms": 60.0}),
        ],
    ).pairs
    metric = summarize_metric(pairs, "latency_ms")
    assert metric.total_pairs == 2
    assert metric.eligible_pairs == 1
    assert metric.baseline_mean == 100.0
    assert metric.candidate_mean == 80.0
    assert metric.mean_delta == -20.0


def test_summarize_metric_with_no_eligible_pairs_reports_none():
    metric = summarize_metric([], "latency_ms")
    assert metric.baseline_mean is None and metric.mean_delta is None


# ---------------------------------------------------------------------------
# CSV adapter + end-to-end report.
# ---------------------------------------------------------------------------


def write_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


@pytest.fixture()
def answer_key(tmp_path):
    return write_csv(
        tmp_path / "gold.csv",
        [
            {"id": "g001", "category": "policy", "domain": "air"},
            {"id": "g002", "category": "operations", "domain": "sea"},
            {"id": "g003", "category": "industry", "domain": "land"},
        ],
    )


def test_answer_key_falls_back_to_the_gold_domain_column(answer_key):
    assert load_answer_key(answer_key, "operational_domain") == {
        "g001": "air",
        "g002": "sea",
        "g003": "land",
    }


def test_answer_key_without_the_axis_column_fails_loud(answer_key):
    with pytest.raises(ValueError, match="no answer-key column"):
        load_answer_key(answer_key, "region")


def test_observations_classify_blank_sentinel_and_ungradable_rows(answer_key):
    answers = load_answer_key(answer_key, "category")
    frame = pd.DataFrame(
        [
            {"id": "g001", "pred_category": "policy"},
            {"id": "g002", "pred_category": ""},
            {"id": "g003", "pred_category": paired_compare.UNCLASSIFIED},
            {"id": "g999", "pred_category": "policy"},
        ]
    ).astype(str)
    observations = observations_from_frame(frame, "arm", "pred_category", answers)
    assert [o.outcome for o in observations] == [
        Outcome.SCORED,
        Outcome.UNSCORED,
        Outcome.ERRORED,
        Outcome.UNSCORABLE,
    ]
    assert observations[0].score == 1.0


def test_observations_require_the_prediction_column(answer_key):
    answers = load_answer_key(answer_key, "category")
    frame = pd.DataFrame([{"id": "g001", "prediction": "policy"}])
    with pytest.raises(ValueError, match="no column 'pred_category'"):
        observations_from_frame(frame, "arm", "pred_category", answers)


def test_compare_prediction_files_end_to_end(tmp_path, answer_key):
    baseline = write_csv(
        tmp_path / "baseline.csv",
        [
            {"id": "g001", "pred_category": "policy"},
            {"id": "g002", "pred_category": "policy"},
            {"id": "g003", "pred_category": "industry"},
        ],
    )
    candidate = write_csv(
        tmp_path / "candidate.csv",
        [
            {"id": "g001", "pred_category": "policy"},
            {"id": "g002", "pred_category": "operations"},
            # g003 never ran on the candidate arm: excluded, not counted wrong.
        ],
    )
    result, lift, report = paired_compare.compare_prediction_files(
        baseline, candidate, answer_key, "category"
    )
    assert lift.total_pairs == 2 and lift.eligible_pairs == 2
    assert lift.baseline_pass_rate == 0.5
    assert lift.candidate_pass_rate == 1.0
    assert lift.lift == 0.5
    assert (lift.candidate_wins, lift.baseline_wins, lift.ties) == (1, 0, 1)
    assert diagnostic_counts(result.diagnostics)["missing-observation"] == 1
    assert "PAIRED COMPARISON -- category" in report
    assert "HARNESS HEALTH" in report
    assert "missing-observation" in report


def test_report_says_so_when_nothing_was_dropped(tmp_path, answer_key):
    rows = [
        {"id": "g001", "pred_category": "policy"},
        {"id": "g002", "pred_category": "operations"},
        {"id": "g003", "pred_category": "industry"},
    ]
    baseline = write_csv(tmp_path / "b.csv", rows)
    candidate = write_csv(tmp_path / "c.csv", rows)
    _, lift, report = paired_compare.compare_prediction_files(
        baseline, candidate, answer_key, "category"
    )
    assert lift.eligible_pairs == 3 and lift.lift == 0.0
    assert "Clean: every group paired and scored" in report


def test_reproduces_the_committed_bakeoff_pairing():
    # Cross-validation against a comparison the repo already did by hand: run
    # the generic layer over the same two committed CSVs the ADR-017 bake-off
    # paired, and check the discordant counts against a from-scratch pandas
    # computation. No published constant is hardcoded here -- both sides are
    # derived from the files, so refreshing a snapshot cannot make this stale,
    # only the two implementations disagreeing can fail it.
    result, lift, _ = paired_compare.compare_prediction_files(
        "evals/baseline_predictions.csv",
        "evals/gold_predictions_v3.csv",
        "data/gold/gold.csv",
        "category",
    )
    gold = pd.read_csv("data/gold/gold.csv")[["id", "category"]]
    ml = pd.read_csv("evals/baseline_predictions.csv")[["id", "pred_category"]]
    llm = pd.read_csv("evals/gold_predictions_v3.csv")[["id", "pred_category"]].rename(
        columns={"pred_category": "llm_category"}
    )
    merged = gold.merge(ml, on="id").merge(llm, on="id")
    ml_right = merged["category"] == merged["pred_category"]
    llm_right = merged["category"] == merged["llm_category"]

    assert lift.eligible_pairs == len(merged)
    assert lift.baseline_wins == int((ml_right & ~llm_right).sum())
    assert lift.candidate_wins == int((~ml_right & llm_right).sum())
    assert lift.ties == int((ml_right == llm_right).sum())
    assert result.diagnostics == []


def test_ids_are_read_as_text_so_leading_zeros_still_pair(tmp_path):
    key = write_csv(tmp_path / "key.csv", [{"id": "007", "category": "policy"}])
    arm = write_csv(tmp_path / "arm.csv", [{"id": "007", "pred_category": "policy"}])
    _, lift, _ = paired_compare.compare_prediction_files(arm, arm, key, "category")
    assert lift.eligible_pairs == 1
