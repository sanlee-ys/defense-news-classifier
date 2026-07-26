"""The published metrics artifact must match the committed predictions.

`evals/metrics.json` is what outward surfaces assert against instead of retyping
numbers by hand. Its one job is to never disagree with the run it claims to
describe — a stale artifact is worse than none, because a consumer would verify
against it and conclude the published figures are correct.

The failure this closes is documented rather than hypothetical: on 2026-07-18 the
public site was found quoting category 88.9% / domain 94.4% while the shipped
classifier measured 94.4% / 92.6%. Two prompt changes stale, on a résumé and a
live site, because a human retyped numbers out of a text report and nothing ever
compared the two again.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from gen_metrics_artifact import ARTIFACT_PATH, build_artifact  # noqa: E402

import classify  # noqa: E402
import gold_eval  # noqa: E402
import provenance  # noqa: E402


def _committed() -> dict:
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def test_artifact_exists():
    assert ARTIFACT_PATH.exists(), (
        "evals/metrics.json is missing. Outward surfaces assert against it; "
        "without it they fall back to hand-typed numbers, which is the failure "
        "this artifact exists to prevent. Run: "
        "uv run python scripts/gen_metrics_artifact.py"
    )


def test_artifact_is_not_stale():
    """Re-run the eval, forget to regenerate, and this fails."""
    rendered = json.dumps(build_artifact(), indent=2) + "\n"
    assert ARTIFACT_PATH.read_text(encoding="utf-8") == rendered, (
        "evals/metrics.json is stale relative to the committed predictions.\n"
        "Run: uv run python scripts/gen_metrics_artifact.py"
    )


def test_artifact_matches_the_committed_report():
    """Cross-check against the human-readable report, not just against itself.

    build_artifact() and gold_eval's printed report both call metrics(), so
    comparing the artifact to build_artifact() alone would be circular. Parsing
    the committed report is an independent path to the same numbers.
    """
    report = (REPO_ROOT / "evals" / "gold_eval_v3.txt").read_text(encoding="utf-8")
    gold = _committed()["gold"]

    for label, key in (
        ("Category accuracy", "category_accuracy"),
        ("Operational domain accuracy", "domain_accuracy"),
        ("Region accuracy", "region_accuracy"),
    ):
        line = next(ln for ln in report.splitlines() if ln.startswith(label))
        printed = float(line.split(":")[1].strip().split("%")[0])
        assert printed == gold[key], (
            f"{key}: artifact says {gold[key]}, the committed report says "
            f"{printed}. One of them is stale."
        )


def test_version_reflects_what_was_measured():
    """A number without the version it came from is a number you cannot place.

    The numbers themselves were measured at v3.0.0 and are unchanged here: v3.1.0
    added eval and experiment harnesses only, so the shipped prompt and the single
    classify call that produced these results are byte-for-byte the same.
    """
    assert _committed()["version"] == "3.1.0"


def test_region_keys_present_on_the_v3_snapshot():
    """metrics() omits region keys for the frozen v2 snapshot; v3 must carry them."""
    gold = _committed()["gold"]
    for key in ("region_accuracy", "region_macro_f1", "judge_region_agreement"):
        assert key in gold, f"{key} missing — is the artifact built from v2 preds?"


def test_artifact_is_marked_generated():
    """A hand-edit is the one way this drifts; say so in the file itself."""
    assert "do not hand-edit" in _committed()["$comment"]


def test_the_snapshot_still_matches_the_prompt_that_produced_it():
    """Edit SYSTEM_PROMPT without re-running the gold eval, and this fails.

    The version test above pins a literal, which catches nothing about the *inputs*:
    evals/gold_predictions_v3.csv is a frozen paid run, and until this existed
    nothing connected it to the prompt behind it. A prompt edit plus a version bump
    would have published the old classifier's numbers as the new version's.

    Backfilled on evidence, not assumption: the SYSTEM_PROMPT literal at ad449db
    (the commit that froze the snapshot) and at HEAD hash identically, so the
    recorded fingerprint states a verified fact.
    """
    ok, message = provenance.check(
        provenance.load(str(REPO_ROOT / provenance.PROVENANCE_PATH)),
        provenance.fingerprint(
            classify.SYSTEM_PROMPT,
            gold_eval.WORKHORSE_MODEL,
            gold_eval.JUDGE_MODEL,
        ),
    )
    assert ok, message


def test_artifact_publishes_the_recorded_fingerprint_not_a_live_one():
    """Recomputing this from the live prompt would make the guard self-satisfying.

    The artifact's job here is to say which prompt produced these numbers. If
    build_artifact() hashed classify.SYSTEM_PROMPT instead of reading the sidecar,
    the published value would silently re-stamp itself on every regeneration — the
    exact hole this closes, one file further along.
    """
    recorded = provenance.load(str(REPO_ROOT / provenance.PROVENANCE_PATH))["recorded"]
    assert _committed()["provenance"] == recorded
    for key in ("prompt_sha256", "workhorse_model", "judge_model"):
        assert key in recorded
