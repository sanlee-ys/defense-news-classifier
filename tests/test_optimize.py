"""Tests for src/optimize.py (the rung-1 prompt-optimization loop).

Offline only, same convention as the rest of the suite: the Anthropic SDK is
faked (AnthropicBackend tests) or bypassed entirely (DryRunBackend, the
orchestrator, and the CLI --dry-run path), so this file runs with no network
and no API key. The Goodhart-guard section is first-class: it proves, via a
full run_optimization pass, that B and C never reach the proposer and that
the done-signal / winner selection read B, not A or C.
"""

import json
import sys
import types

import pandas as pd
import pytest
from conftest import make_tool_block

import eval as evalmod
import optimize

CATEGORIES = ["procurement", "operations", "policy", "technology", "industry"]
DOMAINS = ["air", "land", "sea", "cyber", "space", "multi"]


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _synth_df(n, start_id=0):
    """N synthetic-shaped rows cycling through all categories/domains."""
    return pd.DataFrame(
        [
            {
                "id": start_id + i,
                "text": f"synthetic article {i}",
                "category": CATEGORIES[i % len(CATEGORIES)],
                "operational_domain": DOMAINS[i % len(DOMAINS)],
            }
            for i in range(n)
        ]
    )


def _gold_df(n):
    """N gold-shaped rows, already normalized with `operational_domain` (not `domain`)."""
    return pd.DataFrame(
        [
            {
                "id": f"g{i:03d}",
                "text": f"gold article {i}",
                "category": CATEGORIES[i % len(CATEGORIES)],
                "operational_domain": DOMAINS[i % len(DOMAINS)],
            }
            for i in range(n)
        ]
    )


def _marker_df(marker, n, start_id=0, category="policy", domain="air"):
    """N rows sharing ONE true category/domain, with a distinctive marker in the text.

    Sharing a single true category makes each split's macro-F1 an exact,
    hand-computable function of how many rows are marked correct: with only
    one true label, precision is always 1.0 (no other true label exists to
    be a false positive), so macro-F1 = 2r/(1+r) where r = n_correct / n.
    That is what lets the end-to-end done-signal tests below assert exact
    expected scores rather than approximate ones.
    """
    return pd.DataFrame(
        [
            {
                "id": start_id + i,
                "text": f"{marker} article {i} about defense topics.",
                "category": category,
                "operational_domain": domain,
            }
            for i in range(n)
        ]
    )


def _write_synth_csv(path, n=10):
    _synth_df(n).to_csv(path, index=False)


def _write_gold_csv(path, n=4):
    """Write a gold.csv in gold_eval.load_gold()'s expected shape.

    Uses `domain`, not `operational_domain` -- the rename happens after
    loading, matching gold_eval.py's own convention.
    """
    rows = [
        {
            "id": f"g{i:03d}",
            "dvids_id": f"news:{i}",
            "source_url": "http://example/x",
            "text": f"gold article {i}",
            "category": CATEGORIES[i % len(CATEGORIES)],
            "domain": DOMAINS[i % len(DOMAINS)],
        }
        for i in range(n)
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FixedBackend:
    """Returns pre-built predictions regardless of prompt; for score_split unit tests."""

    def __init__(self, preds_df, tokens=7):
        self._preds = preds_df
        self.tokens = tokens

    def score(self, prompt, df):
        merged = df.merge(self._preds, on="id")
        return optimize.ScoreOutcome(merged=merged, tokens=self.tokens)

    def propose(self, current_prompt, feedback):
        raise NotImplementedError("not used by score_split tests")


_WRONG_CATEGORY = "technology"  # distinct from every _marker_df's "policy" fixture rows


class _ScriptedBackend:
    """Test double for run_optimization: a scripted per-split correct-count sequence.

    Distinguishes which split it is scoring by object identity against the
    fixture DataFrames passed in, since run_optimization always passes the
    same split.a/.b/.c objects on every iteration -- never a copy. Each of
    a_correct/b_correct/c_correct can be a constant int (same every
    iteration) or a list (one entry per iteration, clamped to the last
    entry if the run goes longer than scripted -- matching conftest's
    FakeSequenceMessages reuse-the-last-payload convention).
    """

    def __init__(
        self,
        a_df,
        b_df,
        c_df,
        a_correct=None,
        b_correct=None,
        c_correct=None,
        score_tokens=0,
        propose_tokens=0,
    ):
        self._a_df, self._b_df, self._c_df = a_df, b_df, c_df
        self._a_correct = self._as_list(a_correct, len(a_df))
        self._b_correct = self._as_list(b_correct, len(b_df))
        self._c_correct = self._as_list(c_correct, len(c_df))
        self._iteration = 0
        self.score_tokens = score_tokens
        self.propose_tokens = propose_tokens
        self.propose_feedback_log = []  # every feedback string ever sent to propose()

    @staticmethod
    def _as_list(value, default_n):
        if value is None:
            return [default_n]  # default: always fully correct
        if isinstance(value, int):
            return [value]
        return list(value)

    def _n_correct_for(self, script):
        idx = min(self._iteration, len(script) - 1)
        return script[idx]

    @staticmethod
    def _score_df(df, n_correct):
        rows = []
        for i, (_, row) in enumerate(df.iterrows()):
            correct = i < n_correct
            pred_category = row["category"] if correct else _WRONG_CATEGORY
            rows.append(
                {
                    "id": row["id"],
                    "pred_category": pred_category,
                    "pred_operational_domain": row["operational_domain"],
                }
            )
        return df.merge(pd.DataFrame(rows), on="id")

    def score(self, prompt, df):
        if df is self._b_df:
            n_correct = self._n_correct_for(self._b_correct)
        elif df is self._a_df:
            n_correct = self._n_correct_for(self._a_correct)
        elif df is self._c_df:
            n_correct = self._n_correct_for(self._c_correct)
        else:
            raise AssertionError("unexpected df passed to _ScriptedBackend.score")
        merged = self._score_df(df, n_correct)
        return optimize.ScoreOutcome(merged=merged, tokens=self.score_tokens)

    def propose(self, current_prompt, feedback):
        self.propose_feedback_log.append(feedback)
        self._iteration += 1
        return optimize.ProposeOutcome(
            revised_prompt=f"{current_prompt}\n[scripted edit {self._iteration}]",
            rationale="scripted rationale",
            edit_summary=f"scripted edit {self._iteration}",
            tokens=self.propose_tokens,
        )


class _ProposeFailsBackend(_ScriptedBackend):
    """Like _ScriptedBackend, but propose() always raises ProposalError.

    For testing run_optimization's graceful-stop path when the proposer
    itself can't produce a usable revision (as opposed to a scoring row --
    that's the separate `_OneBadRowBackend` case below).
    """

    def __init__(self, *args, fail_tokens=999, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_tokens = fail_tokens

    def propose(self, current_prompt, feedback):
        self.propose_feedback_log.append(feedback)
        raise optimize.ProposalError(
            "boom: propose_revision truncated mid-JSON", tokens=self.fail_tokens
        )


class _FakeUsage:
    """Mimics anthropic's response.usage.

    conftest's shared FakeMessages doesn't model this since classify()'s
    pinned contract never needed it.
    """

    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeProposeMessages:
    """Local (test_optimize.py-only) fake resembling conftest's FakeMessages.

    The response also carries `.usage`, which AnthropicBackend.propose()
    reads.
    """

    def __init__(self, payload, usage=(100, 50)):
        self._payload = payload
        self.usage = _FakeUsage(*usage)
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        block = make_tool_block(self._payload)
        return types.SimpleNamespace(content=[block], usage=self.usage)


class _FakeProposeClient:
    def __init__(self, payload, usage=(100, 50)):
        self.messages = _FakeProposeMessages(payload, usage)


class _FakeProposeSequenceMessages:
    """Returns a different payload per create() call.

    For propose()'s own retry loop (test_propose_retries_* below).
    A `None` entry simulates a response with no ToolUseBlock at all
    (truncated before the tool call even opens); a dict missing a required
    key simulates truncation mid-JSON, after the block opens but before it
    closes. The final entry repeats if create() is called more times than
    there are payloads -- same convention as conftest's FakeSequenceMessages.
    """

    def __init__(self, payloads, usage=(100, 50)):
        self._payloads = list(payloads)
        self.usage = _FakeUsage(*usage)
        self.calls = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        i = min(self.calls, len(self._payloads) - 1)
        self.calls += 1
        payload = self._payloads[i]
        blocks = [] if payload is None else [make_tool_block(payload)]
        return types.SimpleNamespace(content=blocks, usage=self.usage)


class _FakeProposeSequenceClient:
    def __init__(self, payloads, usage=(100, 50)):
        self.messages = _FakeProposeSequenceMessages(payloads, usage)


# ---------------------------------------------------------------------------
# make_split / _hash_ids
# ---------------------------------------------------------------------------


def test_make_split_is_deterministic_for_same_seed():
    df_synth, df_gold = _synth_df(20), _gold_df(6)
    s1 = optimize.make_split(df_synth, df_gold, ratio=0.7, seed=42)
    s2 = optimize.make_split(df_synth, df_gold, ratio=0.7, seed=42)
    assert list(s1.a["id"]) == list(s2.a["id"])
    assert list(s1.b["id"]) == list(s2.b["id"])
    assert s1.hashes == s2.hashes


def test_make_split_disjoint_and_covers_all_synthetic_rows():
    df_synth, df_gold = _synth_df(20), _gold_df(6)
    s = optimize.make_split(df_synth, df_gold, ratio=0.7, seed=1)
    ids_a, ids_b = set(s.a["id"]), set(s.b["id"])
    assert ids_a.isdisjoint(ids_b)
    assert ids_a | ids_b == set(df_synth["id"])


def test_make_split_ratio_controls_sizes():
    df_synth, df_gold = _synth_df(20), _gold_df(6)
    s = optimize.make_split(df_synth, df_gold, ratio=0.7, seed=1)
    assert len(s.a) == 14  # int(20 * 0.7)
    assert len(s.b) == 6


def test_make_split_c_is_the_entire_gold_set():
    df_synth, df_gold = _synth_df(20), _gold_df(6)
    s = optimize.make_split(df_synth, df_gold, ratio=0.7, seed=1)
    assert len(s.c) == 6
    assert set(s.c["id"]) == set(df_gold["id"])


def test_make_split_different_seed_changes_the_split():
    df_synth, df_gold = _synth_df(20), _gold_df(6)
    s1 = optimize.make_split(df_synth, df_gold, seed=1)
    s2 = optimize.make_split(df_synth, df_gold, seed=2)
    assert s1.hashes["A"] != s2.hashes["A"]


def test_hash_ids_is_stable_and_order_independent():
    assert optimize._hash_ids(pd.Series([3, 1, 2])) == optimize._hash_ids(
        pd.Series([1, 2, 3])
    )


def test_hash_ids_differs_for_different_sets():
    assert optimize._hash_ids(pd.Series([1, 2])) != optimize._hash_ids(
        pd.Series([1, 3])
    )


# ---------------------------------------------------------------------------
# score_split
# ---------------------------------------------------------------------------


def test_score_split_matches_eval_module_computation():
    df = pd.DataFrame(
        [
            {"id": 1, "text": "a", "category": "policy", "operational_domain": "air"},
            {"id": 2, "text": "b", "category": "policy", "operational_domain": "air"},
            {
                "id": 3,
                "text": "c",
                "category": "technology",
                "operational_domain": "sea",
            },
        ]
    )
    preds = pd.DataFrame(
        [
            {"id": 1, "pred_category": "policy", "pred_operational_domain": "air"},
            {"id": 2, "pred_category": "technology", "pred_operational_domain": "air"},
            {"id": 3, "pred_category": "technology", "pred_operational_domain": "sea"},
        ]
    )
    backend = _FixedBackend(preds, tokens=15)

    result = optimize.score_split("some prompt", backend, df)

    merged = df.merge(preds, on="id")
    expected_cat = evalmod.macro_average(evalmod.compute_metrics(merged, "category"))
    expected_dom = evalmod.macro_average(
        evalmod.compute_metrics(merged, "operational_domain")
    )
    assert result.macro_f1 == expected_cat["f1"]
    assert result.domain_macro_f1 == expected_dom["f1"]
    assert result.accuracy == round(2 / 3, 4)
    assert result.tokens == 15
    assert result.per_class_f1 == {
        str(k): float(v)
        for k, v in evalmod.compute_metrics(merged, "category")["f1"].to_dict().items()
    }


def test_score_split_output_is_json_serializable():
    # Regression guard: pandas Series.to_dict() / int64 ids must be cast to
    # native Python types before hitting json.dumps in the run log.
    df = pd.DataFrame(
        [
            {"id": 1, "text": "a", "category": "policy", "operational_domain": "air"},
            {
                "id": 2,
                "text": "b",
                "category": "technology",
                "operational_domain": "sea",
            },
        ]
    )
    preds = pd.DataFrame(
        [
            {"id": 1, "pred_category": "policy", "pred_operational_domain": "air"},
            {"id": 2, "pred_category": "policy", "pred_operational_domain": "sea"},
        ]
    )
    result = optimize.score_split("p", _FixedBackend(preds, tokens=3), df)
    json.dumps(result.as_dict())  # must not raise


def test_score_split_treats_unclassified_sentinel_as_a_miss_not_a_crash():
    # A row predicted with the UNCLASSIFIED sentinel (out-of-enum on both
    # axes by construction) must not crash compute_metrics / macro_average --
    # eval.py keys its label set off ground truth, so an out-of-enum
    # predicted value is invisible to `labels` and simply never matches,
    # scoring the row wrong on both category and domain. Prove it lowers
    # accuracy/macro-F1 versus an all-correct baseline, rather than raising.
    df = pd.DataFrame(
        [
            {"id": 1, "text": "a", "category": "policy", "operational_domain": "air"},
            {"id": 2, "text": "b", "category": "policy", "operational_domain": "air"},
            {"id": 3, "text": "c", "category": "policy", "operational_domain": "air"},
        ]
    )
    all_correct_preds = pd.DataFrame(
        [
            {"id": 1, "pred_category": "policy", "pred_operational_domain": "air"},
            {"id": 2, "pred_category": "policy", "pred_operational_domain": "air"},
            {"id": 3, "pred_category": "policy", "pred_operational_domain": "air"},
        ]
    )
    one_sentinel_preds = pd.DataFrame(
        [
            {"id": 1, "pred_category": "policy", "pred_operational_domain": "air"},
            {"id": 2, "pred_category": "policy", "pred_operational_domain": "air"},
            {
                "id": 3,
                "pred_category": optimize.UNCLASSIFIED,
                "pred_operational_domain": optimize.UNCLASSIFIED,
            },
        ]
    )

    baseline = optimize.score_split("p", _FixedBackend(all_correct_preds, tokens=0), df)
    with_sentinel = optimize.score_split(
        "p", _FixedBackend(one_sentinel_preds, tokens=0), df
    )

    assert with_sentinel.accuracy < baseline.accuracy
    assert with_sentinel.macro_f1 < baseline.macro_f1
    assert with_sentinel.domain_accuracy < baseline.domain_accuracy
    assert with_sentinel.domain_macro_f1 < baseline.domain_macro_f1
    json.dumps(
        with_sentinel.as_dict()
    )  # confusion_matrix-adjacent path stays serializable

    # confusion_matrix() (used by eval.py's report) must also tolerate the
    # sentinel without raising -- it reindexes to the true-label set, so the
    # sentinel column is simply dropped rather than blowing up crosstab.
    merged = df.merge(one_sentinel_preds, on="id")
    evalmod.confusion_matrix(merged, "category")  # must not raise


# ---------------------------------------------------------------------------
# build_feedback / _confusion_stats
# ---------------------------------------------------------------------------


def test_build_feedback_caps_examples_and_sources_from_a_only():
    rows = [
        {
            "id": i,
            "text": f"article {i}",
            "category": "policy",
            "pred_category": "policy" if i < 5 else "technology",
            "operational_domain": "air",
            "pred_operational_domain": "air",
        }
        for i in range(20)
    ]
    merged_a = pd.DataFrame(rows)

    feedback_text, failures_read, confusion_stats = optimize.build_feedback(
        merged_a, max_examples=12
    )

    assert len(failures_read) == 12  # capped even though 15 rows are wrong
    assert confusion_stats == {"policy->technology": 15}
    assert "policy -> technology" in feedback_text
    assert "x15" in feedback_text


def test_build_feedback_failures_have_expected_fields():
    merged_a = pd.DataFrame(
        [
            {
                "id": 7,
                "text": "some article text here",
                "category": "policy",
                "pred_category": "technology",
                "operational_domain": "air",
                "pred_operational_domain": "air",
            }
        ]
    )
    _, failures_read, _ = optimize.build_feedback(merged_a)
    assert failures_read == [
        {
            "id": 7,
            "text_snippet": "some article text here",
            "true_label": "policy",
            "predicted_label": "technology",
        }
    ]


def test_build_feedback_truncates_long_text_snippets():
    merged_a = pd.DataFrame(
        [
            {
                "id": 1,
                "text": "x" * 500,
                "category": "policy",
                "pred_category": "technology",
                "operational_domain": "air",
                "pred_operational_domain": "air",
            }
        ]
    )
    _, failures_read, _ = optimize.build_feedback(merged_a)
    assert len(failures_read[0]["text_snippet"]) == 200


def test_build_feedback_no_confusion_or_failures_when_all_correct():
    merged_a = pd.DataFrame(
        [
            {
                "id": 1,
                "text": "x",
                "category": "policy",
                "pred_category": "policy",
                "operational_domain": "air",
                "pred_operational_domain": "air",
            }
        ]
    )
    feedback_text, failures_read, confusion_stats = optimize.build_feedback(merged_a)
    assert failures_read == []
    assert confusion_stats == {}
    assert "none" in feedback_text.lower()


def test_build_feedback_failures_read_is_json_serializable():
    merged_a = pd.DataFrame(
        [
            {
                "id": 1,
                "text": "a",
                "category": "policy",
                "pred_category": "technology",
                "operational_domain": "air",
                "pred_operational_domain": "air",
            }
        ]
    )
    _, failures_read, confusion_stats = optimize.build_feedback(merged_a)
    json.dumps(failures_read)  # must not raise (numpy.int64 id would break this)
    json.dumps(confusion_stats)


def test_confusion_stats_excludes_diagonal_and_sorts_by_count_desc():
    merged = pd.DataFrame(
        [
            {"category": "policy", "pred_category": "policy"},  # diagonal, excluded
            {"category": "policy", "pred_category": "technology"},
            {"category": "policy", "pred_category": "technology"},
            {"category": "technology", "pred_category": "policy"},
            {"category": "industry", "pred_category": "industry"},  # diagonal, excluded
        ]
    )
    stats = optimize._confusion_stats(merged)
    assert stats == {"policy->technology": 2, "technology->policy": 1}
    assert next(iter(stats)) == "policy->technology"  # highest count first


# ---------------------------------------------------------------------------
# plateau_detected
# ---------------------------------------------------------------------------


def test_plateau_not_detected_with_too_few_points():
    assert optimize.plateau_detected([0.5, 0.6, 0.6], n=3) is False


def test_plateau_detected_after_n_flat_iterations():
    assert optimize.plateau_detected([0.5, 0.6, 0.6, 0.6, 0.6], n=3) is True


def test_plateau_not_detected_when_improvement_resets_the_counter():
    assert optimize.plateau_detected([0.5, 0.6, 0.65, 0.6, 0.6], n=3) is False


def test_plateau_detected_after_a_fresh_stall_window_post_improvement():
    assert optimize.plateau_detected([0.5, 0.6, 0.65, 0.6, 0.6, 0.6], n=3) is True


def test_plateau_tie_does_not_count_as_improvement():
    assert optimize.plateau_detected([0.7, 0.7, 0.7, 0.7], n=3) is True


# ---------------------------------------------------------------------------
# check_done_signal
# ---------------------------------------------------------------------------


def test_check_done_signal_threshold_fires_when_target_reached():
    signal = optimize.check_done_signal([0.5, 0.95], 0.9, 1, 10, 0, 999_999)
    assert signal == "threshold"


def test_check_done_signal_threshold_never_fires_at_iteration_zero():
    # A baseline that already meets the target must NOT stop the run: no edit
    # has been proposed yet, so "threshold" would be a vacuous success signal
    # reported on the un-optimized prompt.
    signal = optimize.check_done_signal([0.95], 0.9, 0, 10, 0, 999_999)
    assert signal is None


def test_check_done_signal_budget_still_backstops_iteration_zero():
    # F8 is unconditional: even at the baseline, a blown token budget halts.
    signal = optimize.check_done_signal([0.95], 0.9, 0, 10, 5000, 5000)
    assert signal == "budget_tokens"


def test_check_done_signal_returns_none_when_nothing_fires():
    signal = optimize.check_done_signal([0.5, 0.6], 0.9, 1, 10, 0, 999_999)
    assert signal is None


def test_check_done_signal_plateau_fires():
    hist = [0.5, 0.6, 0.6, 0.6, 0.6]
    signal = optimize.check_done_signal(hist, 0.99, 4, 100, 0, 999_999, plateau_n=3)
    assert signal == "plateau"


def test_check_done_signal_budget_iterations_fires():
    signal = optimize.check_done_signal([0.5], 0.99, 8, 8, 0, 999_999, plateau_n=100)
    assert signal == "budget_iterations"


def test_check_done_signal_budget_tokens_fires():
    signal = optimize.check_done_signal([0.5], 0.99, 1, 100, 5000, 5000, plateau_n=100)
    assert signal == "budget_tokens"


def test_check_done_signal_precedence_threshold_over_plateau_and_budget():
    hist = [0.5, 0.95, 0.95, 0.95, 0.95]  # also a flat plateau from index 1
    signal = optimize.check_done_signal(hist, 0.9, 8, 8, 999_999, 999_999, plateau_n=3)
    assert signal == "threshold"


def test_check_done_signal_precedence_plateau_over_budget():
    hist = [0.5, 0.6, 0.6, 0.6, 0.6]
    # iteration and tokens are ALSO at their caps here, but plateau must win.
    signal = optimize.check_done_signal(hist, 0.99, 4, 4, 999_999, 999_999, plateau_n=3)
    assert signal == "plateau"


def test_check_done_signal_none_when_history_empty():
    assert optimize.check_done_signal([], 0.9, 0, 10, 0, 999_999) is None


# ---------------------------------------------------------------------------
# select_best_iteration
# ---------------------------------------------------------------------------


def _iter_record(iteration, b_f1):
    return {"iteration": iteration, "scores": {"B": {"macro_f1": b_f1}}}


def test_select_best_iteration_picks_max_b():
    records = [_iter_record(0, 0.5), _iter_record(1, 0.8), _iter_record(2, 0.7)]
    assert optimize.select_best_iteration(records) == 1


def test_select_best_iteration_ties_prefer_earliest():
    records = [_iter_record(0, 0.5), _iter_record(1, 0.8), _iter_record(2, 0.8)]
    assert optimize.select_best_iteration(records) == 1


def test_select_best_iteration_baseline_can_win():
    # A plateau-stop's later iterations are, by definition, not better --
    # the baseline must be able to win if nothing ever improved on it.
    records = [_iter_record(0, 0.9), _iter_record(1, 0.5), _iter_record(2, 0.4)]
    assert optimize.select_best_iteration(records) == 0


def test_select_best_iteration_empty_raises():
    with pytest.raises(ValueError):
        optimize.select_best_iteration([])


# ---------------------------------------------------------------------------
# prompt_diff
# ---------------------------------------------------------------------------


def test_prompt_diff_shows_added_line():
    diff = optimize.prompt_diff("line1\nline2\n", "line1\nline2\nline3\n")
    assert "+line3" in diff


def test_prompt_diff_empty_for_identical_prompts():
    assert optimize.prompt_diff("same", "same") == ""


# ---------------------------------------------------------------------------
# Run-log helpers
# ---------------------------------------------------------------------------


def test_make_run_metadata_has_expected_fields():
    meta = optimize.make_run_metadata(
        "model-x", 1000, 5, {"A": "h1", "B": "h2", "C": "h3"}, "PROMPT", 42
    )
    assert meta["type"] == "run_metadata"
    assert meta["model"] == "model-x"
    assert meta["token_budget"] == 1000
    assert meta["iteration_cap"] == 5
    assert meta["split_hashes"] == {"A": "h1", "B": "h2", "C": "h3"}
    assert meta["start_prompt"] == "PROMPT"
    assert meta["seed"] == 42
    assert "timestamp" in meta


def test_make_iteration_record_has_full_section8_schema():
    rec = optimize.make_iteration_record(
        iteration=2,
        prompt="P",
        prompt_diff_text="D",
        scores={"A": {}, "B": {}, "C": {}},
        failures_read=[{"id": 1}],
        confusion_stats={"a->b": 1},
        agent_rationale="R",
        edit_summary="E",
        tokens_spent=100,
        done_signal=None,
    )
    expected_keys = {
        "type",
        "iteration",
        "prompt",
        "prompt_diff",
        "scores",
        "failures_read",
        "confusion_stats",
        "agent_rationale",
        "edit_summary",
        "tokens_spent",
        "done_signal",
        "unclassified",
    }
    assert set(rec.keys()) == expected_keys
    assert rec["type"] == "iteration"
    assert rec["done_signal"] is None
    # Additive/optional: a record built without passing `unclassified`
    # still has the key, defaulted to all-zero counts, so older callers and
    # the portfolio viewer never see a missing field.
    assert rec["unclassified"] == {"A": 0, "B": 0, "C": 0}


def test_iteration_zero_record_has_null_diff_rationale_edit_summary():
    rec = optimize.make_iteration_record(
        iteration=0,
        prompt="P",
        prompt_diff_text=None,
        scores={"A": {}, "B": {}, "C": {}},
        failures_read=[],
        confusion_stats={},
        agent_rationale=None,
        edit_summary=None,
        tokens_spent=0,
        done_signal=None,
    )
    assert rec["prompt_diff"] is None
    assert rec["agent_rationale"] is None
    assert rec["edit_summary"] is None


def test_make_run_summary_computes_deltas_and_best_iteration():
    records = [
        {
            "iteration": 0,
            "tokens_spent": 10,
            "scores": {
                "A": {"macro_f1": 0.5},
                "B": {"macro_f1": 0.5},
                "C": {"macro_f1": 0.5},
            },
        },
        {
            "iteration": 1,
            "tokens_spent": 20,
            "scores": {
                "A": {"macro_f1": 0.7},
                "B": {"macro_f1": 0.8},
                "C": {"macro_f1": 0.6},
            },
        },
    ]
    summary = optimize.make_run_summary(records, "threshold")
    assert summary["type"] == "run_summary"
    assert summary["best_iteration"] == 1
    assert summary["final_iteration"] == 1
    assert summary["done_signal"] == "threshold"
    assert summary["delta_macro_f1"] == {"A": 0.2, "B": 0.3, "C": 0.1}
    assert summary["overfitting_gap_a_vs_c"] == round(0.2 - 0.1, 4)
    assert summary["total_tokens_spent"] == 20


def test_make_run_summary_measures_deltas_on_best_not_final():
    # Plateau-shaped run: B peaks at iteration 1, then declines until the stop.
    # The headline deltas/overfitting gap must describe the winner (iteration
    # 1), not the discarded final prompt (iteration 3) -- otherwise the
    # summary attributes iteration 3's inflated A-vs-C gap to the prompt that
    # actually ships.
    def rec(iteration, a, b, c, tokens):
        return {
            "iteration": iteration,
            "tokens_spent": tokens,
            "scores": {
                "A": {"macro_f1": a},
                "B": {"macro_f1": b},
                "C": {"macro_f1": c},
            },
        }

    records = [
        rec(0, 0.5, 0.5, 0.5, 10),
        rec(1, 0.7, 0.85, 0.6, 20),  # the peak-B winner
        rec(2, 0.8, 0.84, 0.55, 30),
        rec(3, 0.95, 0.82, 0.52, 40),  # final, not best
    ]
    summary = optimize.make_run_summary(records, "plateau")
    assert summary["best_iteration"] == 1
    assert summary["final_iteration"] == 3
    # Baseline -> BEST, not baseline -> final (which would be A:0.45, C:0.02).
    assert summary["delta_macro_f1"] == {"A": 0.2, "B": 0.35, "C": 0.1}
    assert summary["overfitting_gap_a_vs_c"] == round(0.2 - 0.1, 4)
    # total_tokens_spent still reflects the whole run, including the
    # iterations after the peak -- spend is real even when discarded.
    assert summary["total_tokens_spent"] == 40


def test_append_and_read_run_log_roundtrip(tmp_path):
    path = str(tmp_path / "run.jsonl")
    optimize.append_run_log(path, {"type": "run_metadata", "x": 1})
    optimize.append_run_log(path, {"type": "iteration", "iteration": 0})
    optimize.append_run_log(path, {"type": "run_summary", "y": 2})

    records = optimize.read_run_log(path)
    assert [r["type"] for r in records] == ["run_metadata", "iteration", "run_summary"]


def test_append_run_log_writes_valid_jsonl(tmp_path):
    path = tmp_path / "run.jsonl"
    optimize.append_run_log(str(path), {"a": 1})
    optimize.append_run_log(str(path), {"b": 2})
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # each line independently parses


def test_run_log_survives_a_partial_write_crash(tmp_path):
    # Simulates N4: a crash after 2 records leaves exactly those 2 intact.
    path = str(tmp_path / "run.jsonl")
    optimize.append_run_log(path, {"type": "run_metadata"})
    optimize.append_run_log(path, {"type": "iteration", "iteration": 0})
    records = optimize.read_run_log(path)
    assert len(records) == 2


def test_iteration_records_filters_out_metadata_and_summary():
    records = [
        {"type": "run_metadata"},
        {"type": "iteration", "iteration": 0},
        {"type": "iteration", "iteration": 1},
        {"type": "run_summary"},
    ]
    result = optimize.iteration_records(records)
    assert [r["iteration"] for r in result] == [0, 1]


def test_new_run_log_path_creates_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = optimize.new_run_log_path(directory="evals/optimize")
    assert (tmp_path / "evals" / "optimize").is_dir()
    assert path.endswith(".jsonl")
    assert "run_" in path


# ---------------------------------------------------------------------------
# AnthropicBackend (Anthropic SDK faked, like the rest of the suite)
# ---------------------------------------------------------------------------


def test_anthropic_backend_score_calls_classify_with_prompt_and_model(monkeypatch):
    captured = []

    def fake_classify(client, text, model=None, system_prompt=None):
        captured.append((text, model, system_prompt))
        return {"category": "policy", "operational_domain": "air"}

    monkeypatch.setattr(optimize, "classify", fake_classify)

    df = pd.DataFrame(
        [
            {"id": 1, "text": "t1", "category": "policy", "operational_domain": "air"},
            {"id": 2, "text": "t2", "category": "policy", "operational_domain": "air"},
        ]
    )
    backend = optimize.AnthropicBackend(client=object(), model="claude-sonnet-4-6")
    outcome = backend.score("MY PROMPT", df)

    assert len(captured) == 2
    assert all(model == "claude-sonnet-4-6" for _, model, _ in captured)
    assert all(sp == "MY PROMPT" for _, _, sp in captured)
    assert outcome.tokens > 0
    assert len(outcome.merged) == 2
    assert (outcome.merged["pred_category"] == "policy").all()


def test_anthropic_backend_score_survives_persistent_invalid_label(monkeypatch, capsys):
    # classify() persistently raises InvalidLabelError for row id=2 only (as if
    # the model kept returning an out-of-enum label through all of classify()'s
    # own retries). score() must not propagate it: the row gets the
    # UNCLASSIFIED sentinel on both prediction columns, scoring continues for
    # every other row, and a visible warning is printed -- never a silent drop.
    def flaky_classify(client, text, model=None, system_prompt=None):
        if text == "bad row":
            raise optimize.InvalidLabelError("category 'cyber' is not one of [...]")
        return {"category": "policy", "operational_domain": "air"}

    monkeypatch.setattr(optimize, "classify", flaky_classify)

    df = pd.DataFrame(
        [
            {"id": 1, "text": "t1", "category": "policy", "operational_domain": "air"},
            {
                "id": 2,
                "text": "bad row",
                "category": "policy",
                "operational_domain": "air",
            },
            {"id": 3, "text": "t3", "category": "policy", "operational_domain": "air"},
        ]
    )
    backend = optimize.AnthropicBackend(client=object(), model="claude-sonnet-4-6")
    outcome = backend.score("MY PROMPT", df)

    assert len(outcome.merged) == 3  # the row is kept, not dropped
    assert outcome.unclassified_ids == [2]
    bad_row = outcome.merged[outcome.merged["id"] == 2].iloc[0]
    assert bad_row["pred_category"] == optimize.UNCLASSIFIED
    assert bad_row["pred_operational_domain"] == optimize.UNCLASSIFIED
    good_rows = outcome.merged[outcome.merged["id"] != 2]
    assert (good_rows["pred_category"] == "policy").all()  # everyone else unaffected

    out = capsys.readouterr().out
    assert "row 2" in out
    assert "unclassified after retries, counting as a miss" in out


def test_run_optimization_surfaces_unclassified_count_in_iteration_record(tmp_path):
    # End-to-end through run_optimization (not just AnthropicBackend.score in
    # isolation): a backend that raises InvalidLabelError for one row must
    # not abort the run, and the resulting iteration record's `unclassified`
    # field must reflect it.
    a_df = _marker_df("A", 4)
    b_df = _marker_df("B", 4, start_id=100)
    c_df = _marker_df("C", 2, start_id=200)
    split = optimize.Split(
        a=a_df, b=b_df, c=c_df, hashes={"A": "ha", "B": "hb", "C": "hc"}
    )

    class _OneBadRowBackend:
        """Raises InvalidLabelError for split A's first row; scores everything else."""

        def score(self, prompt, df):
            rows, unclassified = [], []
            for _, row in df.iterrows():
                if df is a_df and row["id"] == a_df.iloc[0]["id"]:
                    rows.append(
                        {
                            "id": row["id"],
                            "pred_category": optimize.UNCLASSIFIED,
                            "pred_operational_domain": optimize.UNCLASSIFIED,
                        }
                    )
                    unclassified.append(row["id"])
                else:
                    rows.append(
                        {
                            "id": row["id"],
                            "pred_category": row["category"],
                            "pred_operational_domain": row["operational_domain"],
                        }
                    )
            merged = df.merge(pd.DataFrame(rows), on="id")
            return optimize.ScoreOutcome(
                merged=merged, tokens=0, unclassified_ids=unclassified
            )

        def propose(self, current_prompt, feedback):
            return optimize.ProposeOutcome(
                revised_prompt=current_prompt,
                rationale="r",
                edit_summary="e",
                tokens=0,
            )

    config = optimize.OptimizationConfig(
        start_prompt="P", max_iterations=0, target_f1=1.1
    )
    log_path = str(tmp_path / "run.jsonl")
    optimize.run_optimization(_OneBadRowBackend(), split, config, run_log_path=log_path)

    records = optimize.read_run_log(log_path)
    iteration_0 = optimize.iteration_records(records)[0]
    assert iteration_0["unclassified"]["A"] == 1
    assert iteration_0["unclassified"]["B"] == 0
    assert iteration_0["unclassified"]["C"] == 0
    # The sentinel-scored row still counts as a miss, not a crash: A's
    # accuracy/F1 reflect one fewer correct row than a run with no
    # unclassified rows would.
    assert iteration_0["scores"]["A"]["accuracy"] < 1.0


def test_anthropic_backend_propose_sends_expected_request_and_exact_tokens():
    payload = {
        "revised_prompt": "REVISED PROMPT TEXT",
        "rationale": "because X",
        "edit_summary": "tightened Y",
    }
    client = _FakeProposeClient(payload, usage=(120, 40))
    backend = optimize.AnthropicBackend(client, model="claude-sonnet-4-6")

    outcome = backend.propose("CURRENT PROMPT", "FEEDBACK TEXT")

    assert outcome.revised_prompt == "REVISED PROMPT TEXT"
    assert outcome.rationale == "because X"
    assert outcome.edit_summary == "tightened Y"
    assert outcome.tokens == 160  # exact: 120 + 40 from response.usage

    kwargs = client.messages.last_kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["system"] == optimize.OPTIMIZER_SYSTEM_PROMPT
    assert kwargs["tool_choice"] == {"type": "tool", "name": "propose_revision"}
    assert "CURRENT PROMPT" in kwargs["messages"][0]["content"]
    assert "FEEDBACK TEXT" in kwargs["messages"][0]["content"]
    # 4096, not the original 2048: the echoed-back revised_prompt grows every
    # iteration (observed 239 -> 980 -> 1670 tokens across three live
    # iterations) and a response cut off mid-JSON crashed a live run at
    # iteration 3 with a KeyError on the truncated tool payload.
    assert kwargs["max_tokens"] == 4096


def test_propose_retries_on_truncated_payload_then_succeeds():
    # First two responses are missing `revised_prompt` -- as if the tool
    # call's JSON was cut off mid-object before it closed. The third is
    # complete. propose() must retry rather than raising, and every
    # attempt's real token cost (even the failed ones) must be reflected
    # in the final outcome.
    bad = {"rationale": "r", "edit_summary": "e"}  # missing revised_prompt
    good = {"revised_prompt": "R", "rationale": "r", "edit_summary": "e"}
    client = _FakeProposeSequenceClient([bad, bad, good], usage=(100, 50))
    backend = optimize.AnthropicBackend(client, model="claude-sonnet-4-6")

    outcome = backend.propose("CURRENT", "FEEDBACK")

    assert outcome.revised_prompt == "R"
    assert client.messages.calls == 3
    assert outcome.tokens == 450  # 150 tokens/attempt x 3 -- none dropped


def test_propose_retries_when_no_tool_block_returned():
    # Extreme truncation: the response has no ToolUseBlock at all (cut off
    # before the tool call even opens). Must be caught (StopIteration), not
    # crash with an unhandled exception.
    good = {"revised_prompt": "R", "rationale": "r", "edit_summary": "e"}
    client = _FakeProposeSequenceClient([None, good], usage=(20, 20))
    backend = optimize.AnthropicBackend(client, model="claude-sonnet-4-6")

    outcome = backend.propose("CURRENT", "FEEDBACK")

    assert outcome.revised_prompt == "R"
    assert client.messages.calls == 2


def test_propose_raises_proposal_error_after_exhausting_retries():
    bad = {
        "rationale": "r",
        "edit_summary": "e",
    }  # missing revised_prompt, every attempt
    client = _FakeProposeSequenceClient([bad, bad, bad], usage=(100, 50))
    backend = optimize.AnthropicBackend(client, model="claude-sonnet-4-6")

    with pytest.raises(optimize.ProposalError) as exc_info:
        backend.propose("CURRENT", "FEEDBACK", max_retries=3)

    assert client.messages.calls == 3
    # Every failed attempt still spent real tokens -- the caller (
    # run_optimization) needs this to keep tokens_spent honest even though
    # the run is about to stop.
    assert exc_info.value.tokens == 450  # 150 x 3


def test_estimate_tokens_scales_with_input_length():
    short = optimize._estimate_tokens("sys", "text")
    longer = optimize._estimate_tokens("sys" * 100, "text" * 100)
    assert longer > short
    assert short >= optimize._ESTIMATED_OUTPUT_TOKENS


def test_estimate_tokens_includes_per_call_overhead():
    # The estimate must lean HIGH (the F8 budget check compares against it),
    # so it has to count more than chars/4 + output: every real call also
    # bills the tool schema and message framing. Guard both the constant's
    # presence in the sum and that it stays large enough to plausibly cover
    # that overhead (~120-190 real tokens per call).
    prompt, text = "sys", "text"
    naive = -(-(len(prompt) + len(text)) // optimize._CHARS_PER_TOKEN)
    estimate = optimize._estimate_tokens(prompt, text)
    assert estimate == (
        naive + optimize._ESTIMATED_OUTPUT_TOKENS + optimize._PER_CALL_OVERHEAD_TOKENS
    )
    assert optimize._PER_CALL_OVERHEAD_TOKENS >= 200


class _FakeRateLimit(Exception):
    pass


class _FakeServerError(Exception):
    pass


@pytest.fixture()
def patch_anthropic_errors(monkeypatch):
    """Swap the SDK exception classes for plain ones we can raise freely.

    Also replaces time.sleep so the retry backoff doesn't actually wait.
    Same convention as tests/test_gold_eval.py's fixture of the same name.
    """
    monkeypatch.setattr(optimize.anthropic, "RateLimitError", _FakeRateLimit)
    monkeypatch.setattr(optimize.anthropic, "InternalServerError", _FakeServerError)
    monkeypatch.setattr(optimize.time, "sleep", lambda *_: None)


def test_classify_retry_recovers_after_transient_errors(
    monkeypatch, patch_anthropic_errors
):
    attempts = {"n": 0}

    def flaky_classify(client, text, model, system_prompt):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _FakeRateLimit("429")
        return {"category": "industry", "operational_domain": "land"}

    monkeypatch.setattr(optimize, "classify", flaky_classify)
    result = optimize._classify_retry(
        None, "x", "claude-sonnet-4-6", system_prompt="PROMPT", max_retries=3
    )

    assert result["operational_domain"] == "land"
    assert attempts["n"] == 3


def test_classify_retry_passes_the_iteration_prompt_through(
    monkeypatch, patch_anthropic_errors
):
    seen = {}

    def fake_classify(client, text, model, system_prompt):
        seen["system_prompt"] = system_prompt
        return {"category": "policy", "operational_domain": "multi"}

    monkeypatch.setattr(optimize, "classify", fake_classify)
    optimize._classify_retry(None, "x", "claude-sonnet-4-6", system_prompt="REVISED v3")

    assert seen["system_prompt"] == "REVISED v3"


def test_classify_retry_reraises_after_exhausting_attempts(
    monkeypatch, patch_anthropic_errors
):
    def always_fails(client, text, model, system_prompt):
        raise _FakeServerError("500")

    monkeypatch.setattr(optimize, "classify", always_fails)
    with pytest.raises(_FakeServerError):
        optimize._classify_retry(
            None, "x", "claude-sonnet-4-6", system_prompt="P", max_retries=2
        )


# ---------------------------------------------------------------------------
# DryRunBackend
# ---------------------------------------------------------------------------


def test_dryrun_backend_score_is_deterministic_across_instances():
    df = _marker_df("X", 6)
    out1 = optimize.DryRunBackend().score("SOME PROMPT", df)
    out2 = optimize.DryRunBackend().score("SOME PROMPT", df)
    assert list(out1.merged["pred_category"]) == list(out2.merged["pred_category"])
    assert out1.tokens == 0


def test_dryrun_backend_accuracy_increases_with_edit_markers():
    backend = optimize.DryRunBackend()
    base = "PROMPT"
    one_edit = "PROMPT\n[dry-run edit #1: x]"
    assert backend._accuracy_for(one_edit) > backend._accuracy_for(base)


def test_dryrun_backend_accuracy_caps_at_ceiling():
    backend = optimize.DryRunBackend(
        start_accuracy=0.5, improvement_per_edit=0.5, ceiling=0.8
    )
    many_edits = "PROMPT" + "\n[dry-run edit #1: x]" * 20
    assert backend._accuracy_for(many_edits) == 0.8


def test_dryrun_backend_more_edits_yields_higher_realized_accuracy():
    df = _marker_df("X", 100)  # large n so the realized rate tracks the nominal one
    backend = optimize.DryRunBackend()
    base_out = backend.score("PROMPT", df)
    edited_prompt = "PROMPT" + "".join(f"\n[dry-run edit #{i}: x]" for i in range(1, 4))
    edited_out = backend.score(edited_prompt, df)

    base_acc = (base_out.merged["category"] == base_out.merged["pred_category"]).mean()
    edited_acc = (
        edited_out.merged["category"] == edited_out.merged["pred_category"]
    ).mean()
    assert edited_acc > base_acc


def test_dryrun_backend_propose_appends_marker_and_spends_zero_tokens():
    outcome = optimize.DryRunBackend().propose("BASE PROMPT", "some feedback")
    assert "[dry-run edit #1" in outcome.revised_prompt
    assert outcome.tokens == 0
    assert "[dry-run]" in outcome.rationale


# ---------------------------------------------------------------------------
# run_optimization -- end-to-end on a scripted backend (no API, no DryRunBackend
# randomness: exact, hand-verifiable scores via _marker_df's single-label trick)
# ---------------------------------------------------------------------------


def test_run_optimization_stops_on_threshold(tmp_path):
    a_df, b_df, c_df = (
        _marker_df("A_MARKER", 8, start_id=0),
        _marker_df("B_MARKER", 8, start_id=100),
        _marker_df("C_MARKER", 8, start_id=200),
    )
    split = optimize.Split(
        a=a_df, b=b_df, c=c_df, hashes={"A": "h", "B": "h", "C": "h"}
    )
    # n=8: k=[2,3,5,7] -> f1=[0.400, 0.545, 0.769, 0.933]; only k=7 clears 0.9.
    backend = _ScriptedBackend(
        a_df, b_df, c_df, a_correct=4, c_correct=4, b_correct=[2, 3, 5, 7]
    )
    config = optimize.OptimizationConfig(
        start_prompt="BASE",
        max_iterations=10,
        target_f1=0.9,
        plateau_n=3,
        token_budget=10_000_000,
    )

    path = optimize.run_optimization(
        backend, split, config, run_log_path=str(tmp_path / "run.jsonl")
    )
    iters = optimize.iteration_records(optimize.read_run_log(path))

    assert iters[-1]["iteration"] == 3
    assert iters[-1]["done_signal"] == "threshold"
    assert iters[-1]["scores"]["B"]["macro_f1"] == 0.933
    assert all(r["done_signal"] is None for r in iters[:-1])


def test_run_optimization_stops_on_plateau(tmp_path):
    a_df, b_df, c_df = (
        _marker_df("A_MARKER", 8, start_id=0),
        _marker_df("B_MARKER", 8, start_id=100),
        _marker_df("C_MARKER", 8, start_id=200),
    )
    split = optimize.Split(
        a=a_df, b=b_df, c=c_df, hashes={"A": "h", "B": "h", "C": "h"}
    )
    # B flat at k=5/8 -> f1=0.769 every iteration; target is unreachable, so
    # only the plateau (N=3) can stop this run.
    backend = _ScriptedBackend(a_df, b_df, c_df, a_correct=4, c_correct=4, b_correct=5)
    config = optimize.OptimizationConfig(
        start_prompt="BASE",
        max_iterations=10,
        target_f1=0.999,
        plateau_n=3,
        token_budget=10_000_000,
    )

    path = optimize.run_optimization(
        backend, split, config, run_log_path=str(tmp_path / "run.jsonl")
    )
    all_records = optimize.read_run_log(path)
    iters = optimize.iteration_records(all_records)

    assert iters[-1]["iteration"] == 3
    assert iters[-1]["done_signal"] == "plateau"
    assert iters[-1]["scores"]["B"]["macro_f1"] == 0.769
    summary = all_records[-1]
    assert summary["best_iteration"] == 0  # all tied at 0.769 -> earliest wins


def test_run_optimization_halts_at_iteration_cap_when_never_converging(tmp_path):
    a_df, b_df, c_df = (
        _marker_df("A_MARKER", 6, start_id=0),
        _marker_df("B_MARKER", 6, start_id=100),
        _marker_df("C_MARKER", 6, start_id=200),
    )
    split = optimize.Split(
        a=a_df, b=b_df, c=c_df, hashes={"A": "h", "B": "h", "C": "h"}
    )
    # Unreachable threshold AND plateau_n larger than the whole run can ever
    # satisfy -- the iteration cap is the ONLY thing that can stop this run
    # (the F8 backstop).
    backend = _ScriptedBackend(a_df, b_df, c_df, a_correct=2, c_correct=2, b_correct=2)
    config = optimize.OptimizationConfig(
        start_prompt="BASE",
        max_iterations=4,
        target_f1=0.999,
        plateau_n=100,
        token_budget=10_000_000,
    )

    path = optimize.run_optimization(
        backend, split, config, run_log_path=str(tmp_path / "run.jsonl")
    )
    all_records = optimize.read_run_log(path)
    iters = optimize.iteration_records(all_records)

    assert [r["iteration"] for r in iters] == [0, 1, 2, 3, 4]
    assert iters[-1]["done_signal"] == "budget_iterations"
    assert all(r["done_signal"] is None for r in iters[:-1])
    assert all_records[0]["type"] == "run_metadata"
    assert all_records[-1]["type"] == "run_summary"


def test_run_optimization_stops_on_token_budget(tmp_path):
    a_df, b_df, c_df = (
        _marker_df("A_MARKER", 4, start_id=0),
        _marker_df("B_MARKER", 4, start_id=100),
        _marker_df("C_MARKER", 4, start_id=200),
    )
    split = optimize.Split(
        a=a_df, b=b_df, c=c_df, hashes={"A": "h", "B": "h", "C": "h"}
    )
    backend = _ScriptedBackend(
        a_df,
        b_df,
        c_df,
        a_correct=2,
        c_correct=2,
        b_correct=2,
        score_tokens=100,
        propose_tokens=50,
    )
    config = optimize.OptimizationConfig(
        start_prompt="BASE",
        max_iterations=50,
        target_f1=0.999,
        plateau_n=100,
        token_budget=500,
    )

    path = optimize.run_optimization(
        backend, split, config, run_log_path=str(tmp_path / "run.jsonl")
    )
    iters = optimize.iteration_records(optimize.read_run_log(path))

    # iter0 baseline: 3 splits x 100 = 300 (< 500, continue).
    # iter1: +50 propose = 350, +300 scoring = 650 (>= 500 -> stop).
    assert iters[-1]["iteration"] == 1
    assert iters[-1]["done_signal"] == "budget_tokens"
    assert iters[-1]["tokens_spent"] == 650


def test_run_optimization_stops_gracefully_when_proposer_exhausts_retries(tmp_path):
    # A proposer that never yields a usable revision (persistent truncation)
    # must stop the run cleanly and report the best iteration found so far
    # -- not propagate a KeyError and abort with the baseline's results
    # unrecorded. Live precedent: exactly this crashed an unattended run at
    # iteration 3 before this hotfix.
    a_df, b_df, c_df = (
        _marker_df("A_MARKER", 4, start_id=0),
        _marker_df("B_MARKER", 4, start_id=100),
        _marker_df("C_MARKER", 2, start_id=200),
    )
    split = optimize.Split(
        a=a_df, b=b_df, c=c_df, hashes={"A": "h", "B": "h", "C": "h"}
    )
    backend = _ProposeFailsBackend(a_df, b_df, c_df, score_tokens=10, fail_tokens=999)
    config = optimize.OptimizationConfig(
        start_prompt="BASE", max_iterations=8, target_f1=1.1
    )

    path = optimize.run_optimization(
        backend, split, config, run_log_path=str(tmp_path / "run.jsonl")
    )
    all_records = optimize.read_run_log(path)
    iters = optimize.iteration_records(all_records)

    # Only the baseline (iteration 0) exists: propose() failed before
    # iteration 1 could produce a new prompt/scores, so no iteration-1
    # record was ever written -- there is nothing to attach it to.
    assert [r["iteration"] for r in iters] == [0]
    assert backend.propose_feedback_log  # propose() really was called once

    summary = all_records[-1]
    assert summary["type"] == "run_summary"
    assert summary["done_signal"] == "proposer_failed"
    assert summary["best_iteration"] == 0
    # Baseline scoring: 3 splits x 10 tokens = 30. The failed proposal still
    # spent 999 real tokens (propose()'s own retries exhausted before
    # raising) -- that cost must not vanish from the total just because no
    # new iteration record exists to carry it.
    assert summary["total_tokens_spent"] == 30 + 999


# ---------------------------------------------------------------------------
# Goodhart guard -- first-class. These prove the structural claim: B and C
# never reach the proposer, the done-signal reads B (not A), and the winner
# is selected on B (not C).
# ---------------------------------------------------------------------------


def test_goodhart_guard_b_and_c_text_never_reach_the_proposer(tmp_path):
    a_df, b_df, c_df = (
        _marker_df("A_MARKER", 8, start_id=0),
        _marker_df("B_MARKER", 8, start_id=100),
        _marker_df("C_MARKER", 8, start_id=200),
    )
    split = optimize.Split(
        a=a_df, b=b_df, c=c_df, hashes={"A": "h", "B": "h", "C": "h"}
    )
    backend = _ScriptedBackend(
        a_df, b_df, c_df, a_correct=4, c_correct=8, b_correct=[2, 4, 6, 8]
    )
    config = optimize.OptimizationConfig(
        start_prompt="BASE PROMPT",
        max_iterations=5,
        target_f1=0.99,
        plateau_n=100,
        token_budget=10_000_000,
    )

    optimize.run_optimization(
        backend, split, config, run_log_path=str(tmp_path / "run.jsonl")
    )

    assert backend.propose_feedback_log  # at least one proposal happened
    for feedback in backend.propose_feedback_log:
        assert "B_MARKER" not in feedback
        assert "C_MARKER" not in feedback
        assert "A_MARKER" in feedback  # sanity: A's failures DO reach the proposer


def test_goodhart_guard_done_signal_reads_b_not_a(tmp_path):
    a_df, b_df, c_df = (
        _marker_df("A_MARKER", 8, start_id=0),
        _marker_df("B_MARKER", 8, start_id=100),
        _marker_df("C_MARKER", 8, start_id=200),
    )
    split = optimize.Split(
        a=a_df, b=b_df, c=c_df, hashes={"A": "h", "B": "h", "C": "h"}
    )
    # A is pinned FLAT the entire run (would plateau by iteration 3 if the
    # done-signal wrongly read A). B climbs the whole time and only clears
    # threshold at the last, later iteration -- if the code correctly reads
    # B, the run must continue past A's would-be plateau point to iteration 4.
    backend = _ScriptedBackend(
        a_df, b_df, c_df, a_correct=2, c_correct=2, b_correct=[1, 2, 3, 4, 8]
    )
    config = optimize.OptimizationConfig(
        start_prompt="BASE",
        max_iterations=10,
        target_f1=0.9,
        plateau_n=3,
        token_budget=10_000_000,
    )

    path = optimize.run_optimization(
        backend, split, config, run_log_path=str(tmp_path / "run.jsonl")
    )
    iters = optimize.iteration_records(optimize.read_run_log(path))

    assert iters[-1]["iteration"] == 4
    assert iters[-1]["done_signal"] == "threshold"


def test_goodhart_guard_best_iteration_reads_b_not_c(tmp_path):
    a_df, b_df, c_df = (
        _marker_df("A_MARKER", 8, start_id=0),
        _marker_df("B_MARKER", 8, start_id=100),
        _marker_df("C_MARKER", 8, start_id=200),
    )
    split = optimize.Split(
        a=a_df, b=b_df, c=c_df, hashes={"A": "h", "B": "h", "C": "h"}
    )
    # B peaks at iteration 1 then worsens; C keeps climbing the whole time.
    # If select_best_iteration were (bug) reading C, it would report the
    # final iteration as best; reading B correctly, it reports iteration 1.
    backend = _ScriptedBackend(
        a_df,
        b_df,
        c_df,
        a_correct=4,
        c_correct=[1, 2, 4, 8],
        b_correct=[2, 8, 3, 3],
    )
    config = optimize.OptimizationConfig(
        start_prompt="BASE",
        max_iterations=3,
        target_f1=0.999,
        plateau_n=2,
        token_budget=10_000_000,
    )

    path = optimize.run_optimization(
        backend, split, config, run_log_path=str(tmp_path / "run.jsonl")
    )
    summary = optimize.read_run_log(path)[-1]

    assert summary["type"] == "run_summary"
    assert summary["best_iteration"] == 1


# ---------------------------------------------------------------------------
# CLI (--dry-run and the live-path wiring), both offline
# ---------------------------------------------------------------------------


def test_cli_dry_run_never_constructs_a_client_and_writes_a_log(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "gold").mkdir(parents=True)
    _write_synth_csv(tmp_path / "data" / "synthetic_articles.csv", n=10)
    _write_gold_csv(tmp_path / "data" / "gold" / "gold.csv", n=4)

    def boom():
        raise AssertionError("make_client must not be called in --dry-run")

    monkeypatch.setattr(optimize, "make_client", boom)
    monkeypatch.setattr(
        sys,
        "argv",
        ["optimize.py", "--dry-run", "--max-iterations", "2", "--seed", "1"],
    )

    optimize.main()

    log_files = list((tmp_path / "evals" / "optimize").glob("run_*.jsonl"))
    assert len(log_files) == 1
    records = optimize.read_run_log(str(log_files[0]))
    assert records[0]["type"] == "run_metadata"
    assert records[-1]["type"] == "run_summary"


def test_cli_live_path_constructs_anthropic_backend_with_client_and_model(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "gold").mkdir(parents=True)
    _write_synth_csv(tmp_path / "data" / "synthetic_articles.csv", n=10)
    _write_gold_csv(tmp_path / "data" / "gold" / "gold.csv", n=4)

    monkeypatch.setattr(optimize, "make_client", lambda: "FAKE_CLIENT")
    captured = {}

    class _StubBackend:
        def __init__(self, client, model):
            captured["client"] = client
            captured["model"] = model

        def score(self, prompt, df):
            merged = df.assign(
                pred_category=df["category"],
                pred_operational_domain=df["operational_domain"],
            )
            return optimize.ScoreOutcome(merged=merged, tokens=0)

        def propose(self, current_prompt, feedback):
            return optimize.ProposeOutcome(
                revised_prompt=current_prompt,
                rationale="r",
                edit_summary="e",
                tokens=0,
            )

    monkeypatch.setattr(optimize, "AnthropicBackend", _StubBackend)
    monkeypatch.setattr(
        sys, "argv", ["optimize.py", "--max-iterations", "0", "--seed", "1"]
    )

    optimize.main()

    assert captured["client"] == "FAKE_CLIENT"
    assert captured["model"] == optimize.MODEL
