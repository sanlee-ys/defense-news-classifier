"""Tests for the ADR-028 domain-key corrections overlay."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import domain_key  # noqa: E402


def _key(rows):
    return pd.DataFrame(rows).astype(str)


def _corrections(rows):
    frame = pd.DataFrame(
        rows,
        columns=[
            "id",
            "judge_operational_domain_old",
            "judge_operational_domain_new",
            "rule",
            "reason",
        ],
    )
    return frame.astype(str)


def test_corrected_key_applies_a_flip_and_touches_nothing_else():
    key = _key(
        [
            {"id": "s1", "judge_operational_domain": "land", "judge_region": "europe"},
            {"id": "s2", "judge_operational_domain": "sea", "judge_region": "africa"},
        ]
    )
    overlay = _corrections([("s1", "land", "multi", "zero-domain-is-multi", "r")])
    out = domain_key.corrected_key(key, overlay)
    assert out.loc[out["id"] == "s1", "judge_operational_domain"].item() == "multi"
    assert out.loc[out["id"] == "s2", "judge_operational_domain"].item() == "sea"
    # No other column moves, and the input frame is not mutated.
    assert out.loc[out["id"] == "s1", "judge_region"].item() == "europe"
    assert key.loc[key["id"] == "s1", "judge_operational_domain"].item() == "land"


def test_corrected_key_refuses_an_unknown_id():
    key = _key([{"id": "s1", "judge_operational_domain": "land"}])
    overlay = _corrections([("s9", "land", "multi", "rule", "r")])
    with pytest.raises(ValueError, match="does not contain"):
        domain_key.corrected_key(key, overlay)


def test_corrected_key_refuses_a_stale_old_label():
    # The drift guard: if the key no longer holds the label the ruling was made
    # against, applying the overlay would relabel a row nobody adjudicated.
    key = _key([{"id": "s1", "judge_operational_domain": "air"}])
    overlay = _corrections([("s1", "land", "multi", "rule", "r")])
    with pytest.raises(ValueError, match="moved under the overlay"):
        domain_key.corrected_key(key, overlay)


def test_load_corrections_refuses_duplicates_noops_and_bad_labels(tmp_path):
    path = tmp_path / "overlay.csv"

    _corrections(
        [("s1", "land", "multi", "a", "r"), ("s1", "land", "sea", "b", "r")]
    ).to_csv(path, index=False)
    with pytest.raises(ValueError, match="more than one correction"):
        domain_key.load_corrections(str(path))

    _corrections([("s1", "land", "land", "a", "r")]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="no-op"):
        domain_key.load_corrections(str(path))

    _corrections([("s1", "land", "underwater", "a", "r")]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="outside the domain enum"):
        domain_key.load_corrections(str(path))


@pytest.mark.skipif(
    not Path(domain_key.CORRECTIONS_PATH).exists(), reason="overlay not present"
)
def test_committed_overlay_applies_cleanly_to_the_committed_key():
    # The integration pin: every committed correction must name a row the
    # committed key actually contains, with the old label the key actually
    # holds. This is what catches a key/overlay drift at CI time instead of
    # inside a future experiment.
    import paired_compare

    key = pd.concat(
        [
            paired_compare.read_predictions("evals/scale_predictions_v3.csv"),
            paired_compare.read_predictions("evals/scale_ext_predictions.csv"),
        ],
        ignore_index=True,
    )
    overlay = domain_key.load_corrections()
    out = domain_key.corrected_key(key, overlay)
    changed = (out["judge_operational_domain"] != key["judge_operational_domain"]).sum()
    assert changed == len(overlay)
    # The one-snippet-one-label property the audit found broken (s370/s371)
    # holds after correction.
    pair = out[out["id"].isin(["s370", "s371"])]["judge_operational_domain"]
    assert len(set(pair)) == 1
