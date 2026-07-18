"""Tests for src/route_eval.py (the v2.2.0 routing experiment). Offline only."""

import re

import pandas as pd
import pytest

import gold_eval
import route_eval


def _runner(rows) -> pd.DataFrame:
    """Runner-up pass frame from (id, cat, dom, runner_up) tuples."""
    return pd.DataFrame(
        [
            {
                "id": i,
                "rp_category": c,
                "rp_operational_domain": d,
                "runner_up_category": r,
            }
            for i, c, d, r in rows
        ]
    )


def _stored(rows) -> pd.DataFrame:
    """Stored predictions frame from (id, pred_cat, pred_dom, judge_cat, judge_dom)."""
    return pd.DataFrame(
        [
            {
                "id": i,
                "pred_category": pc,
                "pred_operational_domain": pd_,
                "judge_category": jc,
                "judge_operational_domain": jd,
            }
            for i, pc, pd_, jc, jd in rows
        ]
    )


def test_escalated_mask_matches_should_escalate_semantics():
    runner = _runner(
        [
            ("g001", "technology", "air", "operations"),
            ("g002", "operations", "land", "technology"),
            ("g003", "technology", "air", "none"),
            ("g004", "industry", "sea", "procurement"),
        ]
    )
    assert list(route_eval.escalated_mask(runner)) == [True, True, False, False]


def test_compose_routed_replays_escalations_from_the_stored_judge():
    runner = _runner(
        [
            ("g001", "technology", "air", "operations"),  # escalates
            ("g002", "policy", "multi", "none"),  # does not
        ]
    )
    stored = _stored(
        [
            ("g001", "technology", "air", "operations", "land"),
            ("g002", "policy", "multi", "policy", "multi"),
        ]
    )
    composed = route_eval.compose_routed(runner, stored)
    esc = composed.set_index("id")
    # The escalated row takes the judge's labels on BOTH axes; the other keeps its own.
    assert esc.loc["g001", "routed_category"] == "operations"
    assert esc.loc["g001", "routed_operational_domain"] == "land"
    assert esc.loc["g002", "routed_category"] == "policy"
    assert esc.loc["g002", "routed_operational_domain"] == "multi"
    assert list(composed["escalated"]) == [True, False]


def _gold_fixture():
    """A 4-row gold set where routing fixes one row and breaks another."""
    gold = pd.DataFrame(
        [
            {"id": "g001", "category": "operations", "domain": "land"},
            {"id": "g002", "category": "technology", "domain": "air"},
            {"id": "g003", "category": "policy", "domain": "multi"},
            {"id": "g004", "category": "industry", "domain": "sea"},
        ]
    )
    runner = _runner(
        [
            # Escalates; workhorse wrong (technology), judge right (operations) -> fixed.
            ("g001", "technology", "air", "operations"),
            # Escalates; workhorse right, judge wrong (operations) -> broke.
            ("g002", "technology", "air", "operations"),
            ("g003", "policy", "multi", "none"),
            ("g004", "industry", "sea", "none"),
        ]
    )
    stored = _stored(
        [
            ("g001", "technology", "air", "operations", "land"),
            ("g002", "technology", "air", "operations", "land"),
            ("g003", "policy", "multi", "policy", "multi"),
            ("g004", "industry", "sea", "industry", "sea"),
        ]
    )
    return gold, route_eval.compose_routed(runner, stored)


def test_gold_metrics_grades_all_three_systems_with_cis():
    gold, composed = _gold_fixture()
    gm = route_eval.gold_metrics(gold, composed)
    assert gm["n"] == 4
    assert gm["escalated"] == 2
    assert gm["escalated_ids"] == ["g001", "g002"]
    cat = gm["category"]
    # Baseline: g001 wrong (pred technology vs true operations) -> 3/4.
    assert cat["baseline"]["correct"] == 3
    # Routed: fixes g001, breaks g002 -> still 3/4 (the wash the report must show).
    assert cat["routed"]["correct"] == 3
    for system in ("baseline", "routed", "all_opus"):
        row = cat[system]
        assert row["ci_low"] <= row["accuracy"] <= row["ci_high"]
    assert gm["escalation_effect"] == {"fixed": 1, "broke": 1, "unchanged": 0}


def test_perturbation_check_counts_moved_labels():
    _, composed = _gold_fixture()
    p = route_eval.perturbation_check(composed)
    # In the fixture the runner-up pass agrees with the stored baseline everywhere.
    assert p["category"] == {"agree": 4, "n": 4, "moved": 0}
    assert p["operational_domain"]["moved"] == 0


def test_scale_metrics_reports_rate_and_movement_never_accuracy():
    runner = _runner(
        [
            ("s001", "technology", "air", "operations"),  # escalates, label changes
            ("s002", "operations", "land", "none"),
            ("s003", "policy", "multi", "none"),
            ("s004", "operations", "sea", "technology"),  # escalates, label unchanged
        ]
    )
    stored = _stored(
        [
            ("s001", "technology", "air", "operations", "air"),
            ("s002", "operations", "land", "operations", "land"),
            ("s003", "policy", "multi", "policy", "multi"),
            ("s004", "operations", "sea", "operations", "sea"),
        ]
    )
    sm = route_eval.scale_metrics(route_eval.compose_routed(runner, stored))
    assert sm["n"] == 4
    assert sm["escalated"] == 2
    assert sm["rate"] == pytest.approx(0.5)
    assert sm["category_changed"] == 1
    assert sm["escalated_ids"] == ["s001", "s004"]
    assert "accuracy" not in sm


def test_cost_lines_price_the_escalation_rate():
    lines = "\n".join(route_eval.cost_lines(0.10))
    assert "workhorse only : 1.00x" in lines
    assert "routed         : 1.50x" in lines
    assert "all-Opus       : 5.00x" in lines


def test_build_report_states_the_hypothesis_and_the_circularity_guard():
    gold, composed = _gold_fixture()
    report = route_eval.build_report(
        route_eval.gold_metrics(gold, composed),
        route_eval.scale_metrics(composed),
        route_eval.perturbation_check(composed),
    )
    assert "ROUTING EXPERIMENT" in report
    assert "Hypothesis going in" in report
    assert "fixed 1, broke 1" in report
    # The circularity guard must be stated where the scale numbers appear.
    assert "No accuracy here BY DESIGN" in report
    assert "Cost model" in report


# ---------------------------------------------------------------------------
# The live pass loops (driven with the conftest fakes)
# ---------------------------------------------------------------------------


def test_run_runner_up_predictions_appends_resume_safe(
    tmp_path, monkeypatch, tool_client
):
    monkeypatch.setattr(gold_eval, "SLEEP_BETWEEN_CALLS", 0)
    client = tool_client(
        {
            "category": "operations",
            "operational_domain": "air",
            "runner_up_category": "none",
        }
    )
    df = pd.DataFrame(
        [{"id": "s001", "text": "snippet one"}, {"id": "s002", "text": "snippet two"}]
    )
    out = tmp_path / "runner.csv"

    route_eval.run_runner_up_predictions(client, df, {"s001"}, preds_path=str(out))

    written = pd.read_csv(out)
    assert list(written["id"]) == ["s002"]  # done_ids skipped
    assert set(written.columns) == {
        "id",
        "rp_category",
        "rp_operational_domain",
        "runner_up_category",
    }


def test_run_runner_up_predictions_batch_writes_valid_rows(tmp_path, batch_client):
    client = batch_client(
        {
            "s001": {
                "category": "technology",
                "operational_domain": "air",
                "runner_up_category": "operations",
            },
            "s002": "errored",  # transport failure -> skipped, stays todo
        }
    )
    df = pd.DataFrame(
        [{"id": "s001", "text": "snippet one"}, {"id": "s002", "text": "snippet two"}]
    )
    out = tmp_path / "runner.csv"

    route_eval.run_runner_up_predictions_batch(client, df, set(), preds_path=str(out))

    written = pd.read_csv(out)
    assert list(written["id"]) == ["s001"]
    assert written.loc[0, "runner_up_category"] == "operations"


def test_batch_refusal_writes_the_sentinel_row_and_continues(tmp_path, batch_client):
    """Regression guard for the live s151 crash.

    A safety-layer refusal must not abort the results loop -- it records the
    REFUSED sentinel so the id counts as done on resume, and every other row is
    still written.
    """
    client = batch_client(
        {
            "s001": {
                "category": "technology",
                "operational_domain": "air",
                "runner_up_category": "operations",
            },
            "s002": "refusal",
        }
    )
    df = pd.DataFrame(
        [{"id": "s001", "text": "snippet one"}, {"id": "s002", "text": "snippet two"}]
    )
    out = tmp_path / "runner.csv"

    route_eval.run_runner_up_predictions_batch(client, df, set(), preds_path=str(out))

    written = pd.read_csv(out).set_index("id")
    assert written.loc["s002", "rp_category"] == route_eval.REFUSED
    assert written.loc["s001", "rp_category"] == "technology"


def test_load_runner_splits_out_refused_rows(tmp_path):
    path = tmp_path / "runner.csv"
    pd.DataFrame(
        [
            {
                "id": "s001",
                "rp_category": "operations",
                "rp_operational_domain": "air",
                "runner_up_category": None,
            },
            {
                "id": "s002",
                "rp_category": route_eval.REFUSED,
                "rp_operational_domain": route_eval.REFUSED,
                "runner_up_category": route_eval.REFUSED,
            },
        ]
    ).to_csv(path, index=False)

    df, refused = route_eval._load_runner(str(path))

    assert refused == ["s002"]
    assert list(df["id"]) == ["s001"]
    assert df.loc[0, "runner_up_category"] == "none"  # NaN-safe fill still applies


def test_build_report_names_refusals_only_when_present():
    gold, composed = _gold_fixture()
    gm = route_eval.gold_metrics(gold, composed)
    sm = route_eval.scale_metrics(composed)
    perturb = route_eval.perturbation_check(composed)

    silent = route_eval.build_report(gm, sm, perturb, refused={"gold": [], "scale": []})
    assert "Refusals" not in silent

    loud = route_eval.build_report(gm, sm, perturb, refused={"scale": ["s151"]})
    assert "Refusals (excluded from every number above)" in loud
    assert "scale: 1 -- s151" in loud


def test_route_batch_custom_ids_match_the_anthropic_pattern():
    """Regression guard for the '::' custom_id 400 (see gold_eval._BATCH_ID_SEP)."""
    pattern = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
    for row_id in ("g001", "s300"):
        request = route_eval._build_route_batch_request(row_id, "text")
        assert pattern.match(request["custom_id"])
