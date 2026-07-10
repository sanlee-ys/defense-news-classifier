"""Evals-as-CI capability gate: grade committed prediction CSVs against evals/thresholds.toml.

Pure and offline: this module never calls the Anthropic API and needs no
ANTHROPIC_API_KEY. It grades whatever prediction CSVs already exist on disk
(evals/gold_predictions.csv and evals/gold_rag_predictions.csv) using the same
metrics() functions gold_eval.py and gold_eval_rag.py use to build their human-readable
reports, so there is one source of truth for every gated number. (It imports gold_eval
and gold_eval_rag as modules, which transitively pulls in the anthropic package for
exception-type references -- that is a library import, not an API call; no key is read
or required.)

Two callers wrap this same script around the same floors (see
.github/workflows/evals.yml and decisions/007-evals-as-ci-gate.md):

- The offline gate (every push/PR, no key) grades whatever is already committed --
  free, deterministic, and it proves the shipped numbers still clear the bar and that
  the scoring code itself still computes them correctly. It is not a live capability
  check.
- The live capability gate (workflow_dispatch + a weekly schedule only) deletes the
  cached prediction CSVs and re-runs gold_eval.py / gold_eval_rag.py against the real
  models first, then runs this exact script -- the "did the model/prompt/retrieval
  actually get worse" check.

Run:
    uv run python src/eval_gate.py                    # grade both baseline and rag
    uv run python src/eval_gate.py --check baseline    # grade baseline only
    uv run python src/eval_gate.py --check rag         # grade rag only

Needs a fully labeled data/gold/gold.csv and both prediction CSVs already on disk. Exits
0 if every gated metric clears its floor, 1 if any metric in evals/thresholds.toml is
breached.
"""

from __future__ import annotations

import argparse
import sys
import tomllib

import pandas as pd

import gold_eval
import gold_eval_rag

THRESHOLDS_PATH = "evals/thresholds.toml"


def load_thresholds(path: str = THRESHOLDS_PATH) -> dict:
    """Load the floor table gate checks are graded against.

    Args:
        path: Path to the thresholds TOML file. Defaults to ``THRESHOLDS_PATH``.

    Returns:
        Parsed TOML as a nested dict, one table per check (``baseline``, ``rag``).
    """
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def _baseline_merged(gold: pd.DataFrame) -> pd.DataFrame:
    """Build the same merged frame gold_eval.main() scores, from committed CSVs only.

    Args:
        gold: Loaded, validated gold DataFrame (see ``gold_eval.load_gold``).

    Returns:
        Gold merged with the workhorse + judge predictions.
    """
    preds = pd.read_csv(gold_eval.PREDS_PATH)
    return gold.rename(columns={"domain": "operational_domain"}).merge(preds, on="id")


def _rag_merged(gold: pd.DataFrame) -> pd.DataFrame:
    """Build the same merged frame gold_eval_rag.main() scores, from committed CSVs only.

    Args:
        gold: Loaded, validated gold DataFrame (see ``gold_eval.load_gold``).

    Returns:
        Gold merged with both baseline (``pred_*``) and grounded (``rag_*``) predictions.
    """
    base = pd.read_csv(gold_eval.PREDS_PATH)[
        ["id", "pred_category", "pred_operational_domain"]
    ]
    rag = pd.read_csv(gold_eval_rag.RAG_PREDS_PATH)
    return (
        gold.rename(columns={"domain": "operational_domain"})
        .merge(base, on="id")
        .merge(rag, on="id")
    )


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
    ]
    return [(key, m[key], floors[key]) for key in keys]


def _rows_for_rag(m: dict, floors: dict) -> list[tuple[str, float, float]]:
    """Pair each rag metric/delta with its floor.

    Args:
        m: Output of ``gold_eval_rag.metrics()``.
        floors: The ``[rag]`` table from thresholds.toml.

    Returns:
        List of ``(name, value, floor)`` tuples: absolute floors on the grounded
        category numbers, plus the two grounding-must-not-regress delta floors.
    """
    return [
        (
            "category_accuracy",
            m["category_accuracy_grounded"],
            floors["category_accuracy"],
        ),
        (
            "category_macro_f1",
            m["category_macro_f1_grounded"],
            floors["category_macro_f1"],
        ),
        (
            "category_delta_min",
            m["category_accuracy_delta"],
            floors["category_delta_min"],
        ),
        ("domain_delta_min", m["domain_accuracy_delta"], floors["domain_delta_min"]),
    ]


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


def check_baseline(thresholds: dict) -> bool:
    """Grade the committed baseline predictions against the ``[baseline]`` floors.

    Args:
        thresholds: Parsed evals/thresholds.toml (see ``load_thresholds``).

    Returns:
        True if every baseline metric clears its floor.
    """
    gold = gold_eval.load_gold()
    merged = _baseline_merged(gold)
    m = gold_eval.metrics(merged)
    rows = _rows_for_baseline(m, thresholds["baseline"])
    return _print_table("baseline (workhorse + judge vs human)", rows)


def check_rag(thresholds: dict) -> bool:
    """Grade the committed grounded predictions against the ``[rag]`` floors.

    Args:
        thresholds: Parsed evals/thresholds.toml (see ``load_thresholds``).

    Returns:
        True if every rag metric/delta clears its floor.
    """
    gold = gold_eval.load_gold()
    merged = _rag_merged(gold)
    m = gold_eval_rag.metrics(merged)
    rows = _rows_for_rag(m, thresholds["rag"])
    return _print_table("rag (grounded vs baseline)", rows)


def main() -> None:
    """Grade committed prediction CSVs against evals/thresholds.toml; exit 1 on breach."""
    parser = argparse.ArgumentParser(
        description="Grade committed gold-eval prediction CSVs against evals/thresholds.toml."
    )
    parser.add_argument(
        "--check",
        choices=["baseline", "rag", "all"],
        default="all",
        help="Which gate(s) to run (default: all).",
    )
    args = parser.parse_args()

    thresholds = load_thresholds()
    results = []
    if args.check in ("baseline", "all"):
        results.append(check_baseline(thresholds))
    if args.check in ("rag", "all"):
        results.append(check_rag(thresholds))

    if all(results):
        print("\nPASS -- every gated metric cleared its floor.")
    else:
        print(
            "\nFAIL -- at least one gated metric is below its floor.", file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
