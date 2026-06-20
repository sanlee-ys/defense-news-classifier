"""
Stability harness: run the full eval N times and report the spread.

The single-run eval gives one number (e.g. category accuracy 79.0%). But the
classifier is a sampling LLM, so that number has run-to-run variance. This
script runs the whole eval several times and reports mean / std / min / max for
each headline metric, which answers the obvious objection to the v1 prompt
experiment: "is a 2-point difference real, or just noise?"

Rule of thumb it lets you apply: a difference between two configs is only
meaningful if it clears roughly 2x the run-to-run standard deviation measured
here. Below that, treat it as noise.

Usage:
    uv run python src/stability.py --runs 5                 # 5 passes, API default temp
    uv run python src/stability.py --runs 5 --temperature 0 # pin temperature to 0

Each run's raw predictions are saved to evals/runs/predictions_run{k}.csv, and
the summary is written to evals/stability.txt. Needs ANTHROPIC_API_KEY.
"""

import argparse
import os
import statistics

import pandas as pd

from classify import make_client
from eval import (
    DATA_PATH,
    classify_with_retry,
    compute_metrics,
    macro_average,
)

RUNS_DIR = "evals/runs"
STABILITY_PATH = "evals/stability.txt"

# The four numbers we track across runs, in display order.
METRIC_KEYS = [
    "category_accuracy",
    "category_macro_f1",
    "domain_accuracy",
    "domain_macro_f1",
]


# ---------------------------------------------------------------------------
# Pure functions (no API, no I/O) — unit-tested offline
# ---------------------------------------------------------------------------


def headline_metrics(merged: pd.DataFrame) -> dict:
    """Compute the four headline numbers for one completed run.

    Args:
        merged: DataFrame with ground-truth and prediction columns for both
            ``category`` and ``operational_domain``.

    Returns:
        Dict with keys ``category_accuracy``, ``category_macro_f1``,
        ``domain_accuracy``, ``domain_macro_f1``.
    """
    cat_acc = (merged["category"] == merged["pred_category"]).mean()
    dom_acc = (merged["operational_domain"] == merged["pred_operational_domain"]).mean()
    cat_macro = macro_average(compute_metrics(merged, "category"))
    dom_macro = macro_average(compute_metrics(merged, "operational_domain"))
    return {
        "category_accuracy": round(float(cat_acc), 4),
        "category_macro_f1": cat_macro["f1"],
        "domain_accuracy": round(float(dom_acc), 4),
        "domain_macro_f1": dom_macro["f1"],
    }


def summarize_runs(per_run: list[dict]) -> dict:
    """Aggregate per-run metric dicts into mean / std / min / max per metric.

    Standard deviation uses the sample formula (ddof=1) and is 0.0 when there
    is only a single run — you can't estimate spread from one point.

    Args:
        per_run: List of metric dicts, one per run (as from ``headline_metrics``).

    Returns:
        Dict mapping each metric key to a dict with ``mean``, ``std``,
        ``min``, ``max``.
    """
    if not per_run:
        raise ValueError("per_run must contain at least one run")
    summary = {}
    for key in per_run[0]:
        vals = [r[key] for r in per_run]
        summary[key] = {
            "mean": round(statistics.fmean(vals), 4),
            "std": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
            "min": min(vals),
            "max": max(vals),
        }
    return summary


def build_stability_report(
    per_run: list[dict], summary: dict, temperature: float | None
) -> str:
    """Format a human-readable stability report.

    Args:
        per_run: Per-run metric dicts.
        summary: Aggregated stats from ``summarize_runs``.
        temperature: Temperature used for the runs (``None`` = API default).

    Returns:
        Multi-line report string.
    """
    n = len(per_run)
    temp_label = "API default" if temperature is None else str(temperature)
    lines = [
        "=" * 70,
        "DEFENSE NEWS CLASSIFIER — STABILITY (multi-run) REPORT",
        "=" * 70,
        "",
        f"Runs        : {n}",
        f"Temperature : {temp_label}",
        "",
        f"{'metric':<22}{'mean':>8}{'std':>8}{'min':>8}{'max':>8}{'spread':>8}",
        "-" * 62,
    ]
    for key in METRIC_KEYS:
        s = summary[key]
        spread = round(s["max"] - s["min"], 4)
        lines.append(
            f"{key:<22}{s['mean']:>8.4f}{s['std']:>8.4f}"
            f"{s['min']:>8.4f}{s['max']:>8.4f}{spread:>8.4f}"
        )
    lines += [
        "",
        "Reading this: 'std' is the run-to-run noise floor. A difference between",
        "two prompt/config variants is only meaningful if it clears about 2x the",
        "std for that metric; smaller gaps are indistinguishable from sampling noise.",
        "",
        "Per-run values:",
    ]
    for i, r in enumerate(per_run, 1):
        vals = "  ".join(f"{k}={r[k]:.4f}" for k in METRIC_KEYS)
        lines.append(f"  run {i}: {vals}")
    lines.append("=" * 70)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner (hits the API)
# ---------------------------------------------------------------------------


def run_one_pass(client, df: pd.DataFrame, temperature: float | None) -> pd.DataFrame:
    """Classify every article once and return a predictions DataFrame.

    Args:
        client: Authenticated Anthropic client.
        df: Dataset with columns ``id`` and ``text``.
        temperature: Sampling temperature to pass through to the classifier.

    Returns:
        DataFrame with columns ``id``, ``pred_category``,
        ``pred_operational_domain``.
    """
    rows = []
    total = len(df)
    for i, (_, row) in enumerate(df.iterrows()):
        pred = classify_with_retry(client, row["text"], temperature=temperature)
        rows.append(
            {
                "id": row["id"],
                "pred_category": pred["category"],
                "pred_operational_domain": pred["operational_domain"],
            }
        )
        if (i + 1) % 25 == 0 or i + 1 == total:
            print(f"    {i + 1:3d}/{total}", flush=True)
    return pd.DataFrame(rows)


def main() -> None:
    """Run the eval N times and write a stability report.

    Raises:
        EnvironmentError: If ``ANTHROPIC_API_KEY`` is not set (via make_client).
    """
    parser = argparse.ArgumentParser(description="Multi-run eval stability harness.")
    parser.add_argument("--runs", type=int, default=5, help="number of full passes")
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="sampling temperature (default: API default)",
    )
    args = parser.parse_args()

    os.makedirs(RUNS_DIR, exist_ok=True)
    df = pd.read_csv(DATA_PATH)
    n_calls = args.runs * len(df)
    print(
        f"Running {args.runs} passes over {len(df)} articles "
        f"= {n_calls} API calls (temperature: "
        f"{'default' if args.temperature is None else args.temperature}).\n"
    )

    client = make_client()
    per_run = []
    for k in range(1, args.runs + 1):
        print(f"Run {k}/{args.runs}:", flush=True)
        preds = run_one_pass(client, df, args.temperature)
        preds.to_csv(f"{RUNS_DIR}/predictions_run{k}.csv", index=False)
        merged = df.merge(preds, on="id")
        per_run.append(headline_metrics(merged))

    summary = summarize_runs(per_run)
    report = build_stability_report(per_run, summary, args.temperature)
    with open(STABILITY_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + report)
    print(f"\nSaved to {STABILITY_PATH}")


if __name__ == "__main__":
    main()
