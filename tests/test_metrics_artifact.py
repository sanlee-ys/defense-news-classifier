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
    """A number without the version it came from is a number you cannot place."""
    assert _committed()["version"] == "3.0.0"


def test_region_keys_present_on_the_v3_snapshot():
    """metrics() omits region keys for the frozen v2 snapshot; v3 must carry them."""
    gold = _committed()["gold"]
    for key in ("region_accuracy", "region_macro_f1", "judge_region_agreement"):
        assert key in gold, f"{key} missing — is the artifact built from v2 preds?"


def test_artifact_is_marked_generated():
    """A hand-edit is the one way this drifts; say so in the file itself."""
    assert "do not hand-edit" in _committed()["$comment"]
