import os
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import loop_metrics as lm  # noqa: E402

import optimize  # noqa: E402  (importable via the src path loop_metrics inserts)

# ---------------------------------------------------------------------------
# The ledger must never default into the worktree: that is the whole of the
# "the agent cannot read B and C" guarantee.
# ---------------------------------------------------------------------------


def test_ledger_path_refuses_without_an_explicit_location(monkeypatch):
    monkeypatch.delenv("LOOP_LEDGER", raising=False)
    with pytest.raises(SystemExit):
        lm.ledger_path(None)


def test_ledger_path_reads_the_environment(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "ledger.jsonl"
    monkeypatch.setenv("LOOP_LEDGER", str(target))
    assert lm.ledger_path(None) == target.resolve()
    assert target.parent.exists()


def test_ledger_path_prefers_the_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("LOOP_LEDGER", str(tmp_path / "from_env.jsonl"))
    flagged = tmp_path / "from_flag.jsonl"
    assert lm.ledger_path(str(flagged)) == flagged.resolve()


def test_append_and_read_round_trip(tmp_path):
    path = tmp_path / "ledger.jsonl"
    lm.append_ledger(path, {"kind": "baseline", "iteration": 0})
    lm.append_ledger(path, {"kind": "iteration", "iteration": 1})
    assert [r["iteration"] for r in lm.read_ledger(path)] == [0, 1]


def test_read_ledger_of_a_missing_file_is_empty(tmp_path):
    assert lm.read_ledger(tmp_path / "absent.jsonl") == []


# ---------------------------------------------------------------------------
# The ratchet: a rejected iteration must not raise the bar it failed.
# ---------------------------------------------------------------------------


def test_best_b_ignores_rejected_iterations():
    records = [
        {"kind": "baseline", "verdict": "baseline", "b": {"macro_f1": 0.70}},
        {"kind": "iteration", "verdict": "accept", "b": {"macro_f1": 0.75}},
        {"kind": "iteration", "verdict": "reject", "b": {"macro_f1": 0.99}},
    ]
    assert lm.best_b(records) == 0.75


def test_best_b_is_none_before_anything_is_scored():
    assert lm.best_b([]) is None


def test_baseline_prompt_finds_the_baseline_record():
    records = [
        {"kind": "iteration", "prompt": "wrong"},
        {"kind": "baseline", "prompt": "the start prompt"},
    ]
    assert lm.baseline_prompt(records) == "the start prompt"
    assert lm.baseline_prompt([{"kind": "iteration"}]) is None


# ---------------------------------------------------------------------------
# The agent-visible report carries split A and nothing else.
# ---------------------------------------------------------------------------


@pytest.fixture
def redirect_state(monkeypatch, tmp_path):
    monkeypatch.setattr(lm, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lm, "REPORT_A", tmp_path / "report_A.md")
    monkeypatch.setattr(lm, "VERDICT", tmp_path / "verdict.md")
    return tmp_path


def _merged_a():
    return pd.DataFrame(
        [
            {
                "id": 1,
                "text": "A contract award for new tankers.",
                "category": "procurement",
                "operational_domain": "air",
                "pred_category": "industry",
                "pred_operational_domain": "air",
            },
            {
                "id": 2,
                "text": "A new cyber doctrine was published.",
                "category": "policy",
                "operational_domain": "cyber",
                "pred_category": "policy",
                "pred_operational_domain": "cyber",
            },
        ]
    )


def test_report_a_names_only_set_a(redirect_state):
    lm.write_report_a("a prompt", _merged_a(), iteration=2)
    text = (redirect_state / "report_A.md").read_text(encoding="utf-8")
    assert "Set A" in text
    assert "procurement -> industry" in text
    # The report must not carry the hidden splits' scores in any form.
    assert "macro_f1" not in text
    assert "Set B" not in text
    assert "Set C" not in text


def test_verdict_never_quotes_a_hidden_number(redirect_state):
    lm.write_verdict(3, "reject", "the hidden validation split regressed")
    text = (redirect_state / "verdict.md").read_text(encoding="utf-8")
    assert "reject" in text
    assert not any(char.isdigit() for char in text.split("reason:")[1])


# ---------------------------------------------------------------------------
# Exit codes are the contract the outer script branches on.
# ---------------------------------------------------------------------------


def test_exit_codes_are_distinct():
    codes = {
        lm.EXIT_ACCEPT,
        lm.EXIT_ERROR,
        lm.EXIT_REJECT_B,
        lm.EXIT_REJECT_REGION,
    }
    assert len(codes) == 4


def test_b_tolerance_allows_no_slack():
    # A tolerance here would let every iteration give back a little, and the
    # sum of "a little" is the regression the gate exists to stop.
    assert lm.B_TOLERANCE == 0.0


# ---------------------------------------------------------------------------
# End to end, zero API: a baseline record lands with all three splits, and
# the region rubric gate rejects a damaged prompt.
# ---------------------------------------------------------------------------


def _args(mode, ledger, **overrides):
    import argparse

    values = {
        "mode": mode,
        "ledger": str(ledger),
        "dry_run": True,
        "model": None,
        "seed": 42,
        "split_ratio": 0.7,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.mark.skipif(
    not (lm.REPO_ROOT / lm.DATA_PATH).exists(), reason="dataset not present"
)
def test_baseline_records_all_three_splits(redirect_state, tmp_path, monkeypatch):
    monkeypatch.chdir(lm.REPO_ROOT)
    ledger = tmp_path / "ledger.jsonl"
    assert lm.run(_args("baseline", ledger)) == lm.EXIT_ACCEPT
    records = lm.read_ledger(ledger)
    assert len(records) == 1
    assert set(records[0]) >= {"a", "b", "c", "region_guardrail", "prompt"}


@pytest.mark.skipif(
    not (lm.REPO_ROOT / lm.DATA_PATH).exists(), reason="dataset not present"
)
def test_a_damaged_region_rubric_is_rejected(redirect_state, tmp_path, monkeypatch):
    monkeypatch.chdir(lm.REPO_ROOT)
    ledger = tmp_path / "ledger.jsonl"
    lm.run(_args("baseline", ledger))
    # The next iteration renames the frozen block's header, which is how a
    # proposer "improves the wording" and deletes an adopted rubric (ADR-024).
    monkeypatch.setattr(
        lm, "SYSTEM_PROMPT", lm.SYSTEM_PROMPT.replace("Region rules:", "Region notes:")
    )
    assert lm.run(_args("check", ledger)) == lm.EXIT_REJECT_REGION
    assert lm.read_ledger(ledger)[-1]["reject_gate"] == "region_rubric"


@pytest.mark.skipif(
    not (lm.REPO_ROOT / lm.DATA_PATH).exists(), reason="dataset not present"
)
def test_a_b_regression_is_rejected(redirect_state, tmp_path, monkeypatch):
    monkeypatch.chdir(lm.REPO_ROOT)
    ledger = tmp_path / "ledger.jsonl"
    lm.run(_args("baseline", ledger))
    # Raise the accepted bar above anything the mock backend can score, so
    # the next check must fail the hidden gate rather than pass it by luck.
    lm.append_ledger(
        ledger,
        {"kind": "iteration", "verdict": "accept", "b": {"macro_f1": 0.999}},
    )
    assert lm.run(_args("check", ledger)) == lm.EXIT_REJECT_B
    last = lm.read_ledger(ledger)[-1]
    assert last["reject_gate"] == "b_regression"
    # The rejected iteration must not become the new bar.
    assert lm.best_b(lm.read_ledger(ledger)) == 0.999


def test_state_dir_is_inside_the_repo_but_the_ledger_is_not():
    # The report the agent reads lives in the tree. The ledger must not.
    assert str(lm.STATE_DIR).startswith(str(lm.REPO_ROOT))
    assert "LOOP_LEDGER" not in os.environ or not str(
        Path(os.environ["LOOP_LEDGER"]).resolve()
    ).startswith(str(lm.REPO_ROOT))


def test_score_all_surfaces_errored_counts_per_split():
    # A truncated/refused row is excluded from scoring (ADR-021), which
    # changes that split's denominator -- the ledger record must say so, or
    # a reviewer comparing B across iterations cannot see the ruler moved.
    class _DropMarkedRowsBackend:
        """Perfect predictions; rows whose text is "DROP" error out instead."""

        def score(self, prompt, df):
            kept = df[df["text"] != "DROP"]
            merged = kept.assign(
                pred_category=kept["category"],
                pred_operational_domain=kept["operational_domain"],
                pred_region=kept["region"],
            )
            return optimize.ScoreOutcome(
                merged=merged,
                tokens=1,
                errored_ids=list(df.loc[df["text"] == "DROP", "id"]),
            )

    def _df(ids, drop_first=False):
        rows = []
        for i, row_id in enumerate(ids):
            rows.append(
                {
                    "id": row_id,
                    "text": "DROP" if (drop_first and i == 0) else f"t{row_id}",
                    "category": "policy",
                    "operational_domain": "air",
                    "region": "europe",
                }
            )
        return pd.DataFrame(rows)

    split = optimize.Split(
        a=_df([1, 2, 3], drop_first=True),
        b=_df([10, 11]),
        c=_df([20, 21]),
        hashes={"A": "ha", "B": "hb", "C": "hc"},
    )
    record = lm.score_all("PROMPT", _DropMarkedRowsBackend(), split)

    assert record["errored"] == {"A": 1, "B": 0, "C": 0}
    assert list(record["merged_a"]["id"]) == [2, 3]  # the errored row is absent
