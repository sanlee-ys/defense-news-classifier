"""Evals-as-CI capability gate: grade committed prediction CSVs against evals/thresholds.toml.

Pure and offline: this module never calls the Anthropic API and needs no
ANTHROPIC_API_KEY. It grades whatever prediction CSV already exists on disk
(evals/gold_predictions_v3.csv by default) using the same metrics() function
gold_eval.py uses to build its human-readable report, so there is one source of
truth for every gated number. (It
imports gold_eval as a module, which transitively pulls in the anthropic package for
exception-type references -- that is a library import, not an API call; no key is read
or required.)

Two callers wrap this same script around the same floors (see
.github/workflows/evals.yml and decisions/007-evals-as-ci-gate.md):

- The offline gate (every push/PR, no key) grades whatever is already committed --
  free, deterministic, and it proves the shipped numbers still clear the bar and that
  the scoring code itself still computes them correctly. It is not a live capability
  check.
- The live capability gate (workflow_dispatch + a weekly schedule only) deletes the
  cached prediction CSV and re-runs gold_eval.py against the real models first, then
  runs this exact script -- the "did the model or prompt actually get worse" check.

Because the offline gate grades a FROZEN snapshot, it also has to prove that snapshot
still describes the classifier on disk. Otherwise the gate's own claim -- "the shipped
numbers still clear the bar" -- silently stops being about the shipped classifier the
moment someone edits classify.SYSTEM_PROMPT without paying for a gold re-run: the floors
would be reported as met by predictions the current prompt never made. src/provenance.py
records that pairing at run time and main() refuses to grade when it no longer holds
(the same guard scripts/gen_metrics_artifact.py applies before publishing).

BM25 retrieval grounding was retired in decisions/012-retire-bm25-grounding.md (it
stopped paying under the improved prompt), so the gate grades only the ungrounded
baseline -- the classifier that actually ships.

Run:
    uv run python src/eval_gate.py

Needs a fully labeled data/gold/gold.csv and evals/gold_predictions_v3.csv already on
disk. Exits 0 if every gated metric clears its floor, 1 if any metric in
evals/thresholds.toml is breached.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

import pandas as pd

import classify
import gold_eval
import provenance

THRESHOLDS_PATH = "evals/thresholds.toml"

# The committed v3 three-axis snapshot (the transition condition is met: the
# 2026-07-18 live pass is committed and thresholds.toml carries measured region
# floors, per ADR-014's thresholds-after-measurement rule). The frozen v2
# snapshot (evals/gold_predictions.csv) remains on disk as the record behind
# the published two-axis numbers; nothing grades it any more.
PREDS_PATH = "evals/gold_predictions_v3.csv"


def load_thresholds(path: str = THRESHOLDS_PATH) -> dict:
    """Load the floor table gate checks are graded against.

    Args:
        path: Path to the thresholds TOML file. Defaults to ``THRESHOLDS_PATH``.

    Returns:
        Parsed TOML as a nested dict (the ``baseline`` table).
    """
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def _baseline_merged(gold: pd.DataFrame, preds_path: str = PREDS_PATH) -> pd.DataFrame:
    """Build the same merged frame gold_eval.main() scores, from committed CSVs only.

    Args:
        gold: Loaded, validated gold DataFrame (see ``gold_eval.load_gold``).
        preds_path: Predictions CSV to grade. Defaults to the committed v3
            snapshot; the CI live job passes its freshly regenerated file.

    Returns:
        Gold merged with the workhorse + judge predictions.
    """
    preds = pd.read_csv(preds_path)
    return gold.rename(columns={"domain": "operational_domain"}).merge(preds, on="id")


def _rows_for_baseline(m: dict, floors: dict) -> list[tuple[str, float, float]]:
    """Pair each baseline metric with its floor.

    Args:
        m: Output of ``gold_eval.metrics()``.
        floors: The ``[baseline]`` table from thresholds.toml.

    Returns:
        List of ``(name, value, floor)`` tuples, one per gated metric.
    """
    keys = [
        "category_accuracy",
        "category_macro_f1",
        "domain_accuracy",
        "domain_macro_f1",
        "judge_category_agreement",
        "judge_domain_agreement",
        # v3 region floors (measured 2026-07-18). region_macro_f1 is deliberately
        # ungated -- see thresholds.toml for why (europe support n=1).
        "region_accuracy",
        "judge_region_agreement",
    ]
    return [(key, m[key], floors[key]) for key in keys]


def _check_sample_size(label: str, n: int, expected: int) -> bool:
    """Fail loudly if a merge silently dropped gold rows.

    ``_baseline_merged`` inner-joins gold against the committed prediction CSV; a
    truncated or stale predictions file shrinks ``n`` without raising, and every floor
    can still clear on the smaller sample -- this is the only thing standing between a
    partial snapshot and a silent PASS.

    Args:
        label: Which check this is (``"baseline"``), for the message.
        n: Rows actually scored (the merged frame's ``metrics()['n']``).
        expected: Rows the gold set has (``len(gold)``).

    Returns:
        True if ``n == expected``. Prints a message to stderr and returns False
        otherwise.
    """
    if n == expected:
        return True
    print(
        f"FAIL -- {label} predictions cover {n} of {expected} gold rows "
        "(merge dropped ids -- truncated or stale predictions CSV?). Refusing "
        "to grade a partial snapshot.",
        file=sys.stderr,
    )
    return False


def _print_table(title: str, rows: list[tuple[str, float, float]]) -> bool:
    """Print a metric/value/floor/PASS|FAIL table.

    Args:
        title: Section heading (e.g. ``"baseline (workhorse + judge vs human)"``).
        rows: ``(name, value, floor)`` tuples to grade and print.

    Returns:
        True if every row cleared its floor, False if any breached.
    """
    print(f"\n-- {title} " + "-" * 10)
    print(f"{'metric':<28}{'value':>10}{'floor':>10}   result")
    all_pass = True
    for name, value, floor in rows:
        ok = value >= floor
        all_pass = all_pass and ok
        print(f"{name:<28}{value:>10.3f}{floor:>10.3f}   {'PASS' if ok else 'FAIL'}")
    return all_pass


def check_provenance(preds_path: str = PREDS_PATH) -> bool:
    """Refuse to grade the committed snapshot against a prompt that never produced it.

    Scoped deliberately to the default v3 snapshot. ``gold_eval.py`` writes exactly one
    sidecar, at ``provenance.PROVENANCE_PATH``, describing ``PREDS_PATH`` -- so that is
    the only file whose pairing is *knowable*. Deriving a per-preds sidecar path would
    invent a convention nothing produces, and the frozen v2 snapshot
    (``evals/gold_predictions.csv``) must never acquire a hand-written one: a fabricated
    fingerprint asserts a pairing nobody verified, which is worse than no record at all.

    Anything else passed via ``--preds`` is therefore reported as UNPINNED rather than
    failed -- an ad-hoc or experimental predictions file legitimately has no record, and
    hard-failing would make the flag unusable. The notice is loud because "no pairing was
    asserted" must not read like "the pairing was checked".

    A missing sidecar for ``PREDS_PATH`` itself IS a failure, not a skip. Treating absence
    as acceptable would make ``rm evals/gold_predictions_v3.provenance.json`` a one-command
    bypass of the whole guard.

    Note the CI live job is unaffected: it deletes the CSV *and* the sidecar, re-runs
    gold_eval.py (which rewrites both from the live prompt), and only then grades -- so it
    checks a fresh record against the code that just produced it and passes.

    Args:
        preds_path: The predictions CSV about to be graded (``--preds``).

    Returns:
        True if the snapshot may be graded. Prints the reason to stderr and returns
        False when the recorded pairing no longer holds.
    """
    if Path(preds_path).resolve() != Path(PREDS_PATH).resolve():
        print(
            f"UNPINNED -- grading {preds_path}, which is not the snapshot the "
            f"provenance sidecar describes ({PREDS_PATH}). No prompt/model pairing "
            "is asserted for these numbers."
        )
        return True

    try:
        record = provenance.load(provenance.PROVENANCE_PATH)
    except FileNotFoundError as exc:
        print(f"FAIL -- {exc}", file=sys.stderr)
        return False

    ok, message = provenance.check(
        record,
        provenance.fingerprint(
            classify.SYSTEM_PROMPT,
            gold_eval.WORKHORSE_MODEL,
            gold_eval.JUDGE_MODEL,
        ),
        consequence=(
            "Grading now would report the measured floors as met for a classifier "
            "that is not the one on disk."
        ),
    )
    if not ok:
        print(message, file=sys.stderr)
        return False
    if message:
        print(message)
    return True


def check_baseline(thresholds: dict, preds_path: str = PREDS_PATH) -> bool:
    """Grade baseline predictions against the ``[baseline]`` floors.

    Args:
        thresholds: Parsed evals/thresholds.toml (see ``load_thresholds``).
        preds_path: Predictions CSV to grade (see ``_baseline_merged``).

    Returns:
        True if every baseline metric clears its floor.
    """
    gold = gold_eval.load_gold()
    merged = _baseline_merged(gold, preds_path)
    m = gold_eval.metrics(merged)
    if not _check_sample_size("baseline", m["n"], len(gold)):
        return False
    if "region_accuracy" not in m:
        # metrics() omits region keys when the predictions carry no pred_region
        # column -- i.e. a two-axis (v2-shaped) file was passed. The gate grades
        # the three-axis contract now; refusing beats silently gating 6 of 8.
        print(
            f"FAIL -- {preds_path} is a two-axis predictions file (no pred_region "
            "column). The gate grades the v3 three-axis contract; point --preds "
            "at a v3 predictions CSV.",
            file=sys.stderr,
        )
        return False
    rows = _rows_for_baseline(m, thresholds["baseline"])
    return _print_table(f"baseline (workhorse + judge vs human, n={m['n']})", rows)


def main() -> None:
    """Grade predictions against evals/thresholds.toml; exit 1 on breach.

    ``--preds`` selects which predictions CSV is graded. The default is the
    committed v3 three-axis snapshot (the offline gate: proves the shipped
    numbers still clear the bar and the scoring code still computes them).
    The CI live job passes its freshly regenerated v3 file so the same eight
    measured floors grade a live run. All floors come from measured numbers
    (ADR-014: thresholds after measurement, never before).

    Exits 1 without grading if the default snapshot is no longer pinned to the
    prompt and models on disk (see ``check_provenance``).
    """
    parser = argparse.ArgumentParser(description="Grade eval outputs vs thresholds.")
    parser.add_argument(
        "--preds",
        default=PREDS_PATH,
        help="predictions CSV to grade (default: the committed v3 snapshot)",
    )
    args = parser.parse_args()

    # Before any grading: the floors only mean something if the snapshot was produced
    # by the classifier on disk. Its own exit path, not folded into the floor result,
    # so a stale snapshot never gets reported as "a metric is below its floor" -- that
    # would send the reader hunting a regression that did not happen.
    if not check_provenance(args.preds):
        print(
            "\nFAIL -- refusing to grade a snapshot that is not pinned to the "
            "classifier on disk.",
            file=sys.stderr,
        )
        sys.exit(1)

    thresholds = load_thresholds()
    if check_baseline(thresholds, preds_path=args.preds):
        print("\nPASS -- every gated metric cleared its floor.")
    else:
        print(
            "\nFAIL -- at least one gated metric is below its floor.", file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
