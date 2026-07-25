"""Offline tests for the ML baseline bake-off (no API key, no network).

The three guarantees the spec calls out as most likely to silently invalidate the
experiment are each pinned here: the train join is correct, the labels come from
``judge_*`` and never ``pred_*``, and the gold set plays no part in fitting.
"""

import pandas as pd
import pytest

import baseline_ml
from baseline_ml import fit_baseline, load_train, mcnemar_exact


@pytest.fixture()
def train_df():
    return load_train()


def test_train_join_is_complete_and_labeled(train_df):
    assert len(train_df) == 300
    assert list(train_df.columns) == ["id", "text", "category", "operational_domain"]
    assert train_df["category"].notna().all()
    assert train_df["operational_domain"].notna().all()


def test_labels_come_from_judge_not_workhorse(train_df):
    # Rebuild the join by hand from the raw files and prove the loaded labels
    # equal judge_* everywhere -- and that on rows where the judge and the
    # workhorse disagree, the loader sided with the judge.
    raw = pd.read_csv(baseline_ml.TRAIN_LABEL_PATH)
    merged = train_df.merge(raw, on="id", validate="one_to_one")
    assert (merged["category"] == merged["judge_category"]).all()
    assert (merged["operational_domain"] == merged["judge_operational_domain"]).all()
    disagree = merged[merged["judge_category"] != merged["pred_category"]]
    assert len(disagree) > 0, "no judge/workhorse disagreement -- test is vacuous"
    assert (disagree["category"] == disagree["judge_category"]).all()
    # And no pred_* column survives into the training frame at all.
    assert not any(col.startswith("pred_") for col in train_df.columns)


def test_fitting_never_reads_the_gold_file(train_df, monkeypatch):
    # fit_baseline takes a frame, not a path; belt-and-braces, poison every
    # file read during fitting so any hidden gold access blows up.
    def _no_reads(*args, **kwargs):
        raise AssertionError(f"fit_baseline read a file: {args}")

    monkeypatch.setattr(pd, "read_csv", _no_reads)
    baseline = fit_baseline(train_df)
    preds = baseline.predict(train_df["text"].head(5))
    assert set(preds.columns) == {"pred_category", "pred_operational_domain"}


def test_predictions_are_valid_labels(train_df):
    baseline = fit_baseline(train_df)
    preds = baseline.predict(train_df["text"].head(20))
    assert set(preds["pred_category"]) <= set(train_df["category"])
    assert set(preds["pred_operational_domain"]) <= set(train_df["operational_domain"])


def test_mcnemar_exact_known_values():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(1, 1) == pytest.approx(1.0)
    # 0 vs 8 discordant: p = 2 * (1/2)^8 = 0.0078125
    assert mcnemar_exact(0, 8) == pytest.approx(0.0078125)
    # symmetry
    assert mcnemar_exact(3, 7) == pytest.approx(mcnemar_exact(7, 3))
