"""Stability harness: run the full eval N times and report the spread.

The single-run eval gives one number (e.g. category accuracy 79.0%). But the
classifier is a sampling LLM, so that number has run-to-run variance. This
script runs the whole eval several times and reports mean / std / min / max for
each headline metric, which answers the obvious objection to the v1 prompt
experiment: "is a 2-point difference real, or just noise?"

Rule of thumb it lets you apply: a difference between two configs is only
meaningful if it clears roughly 2x the run-to-run standard deviation measured
here. Below that, treat it as noise.

It also reports a direct **label-consistency** number: the fraction of items
whose predicted label is identical across *every* run. This replaces the old
``temperature=0`` determinism knob -- current models (Sonnet 5+) reject any
non-default sampling value with a 400, and ``strict: true`` already guarantees a
schema-valid label, so run-to-run stability is now *measured* empirically here
rather than *forced* via temperature.

Usage:
    uv run python src/stability.py --runs 5   # 5 passes at the API-default sampling

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


def label_consistency(pred_frames: list[pd.DataFrame]) -> dict:
    """Fraction of items whose predicted label is identical across every run.

    This is the direct empirical replacement for the old ``temperature=0``
    determinism check: rather than *forcing* repeatability with a sampling
    parameter (which current models reject), it *measures* it. For each item id,
    it asks whether all N runs produced the same ``category`` (and the same
    ``operational_domain``); the reported number is the fraction that did. A
    single run is trivially self-consistent, so this is only meaningful for N>=2.

    Args:
        pred_frames: One predictions DataFrame per run, each with columns
            ``id``, ``pred_category``, ``pred_operational_domain``.

    Returns:
        Dict with keys ``category_consistency`` and ``domain_consistency``,
        each a fraction in ``[0, 1]``.
    """
    if not pred_frames:
        raise ValueError("pred_frames must contain at least one run")
    cat = pd.concat([f.set_index("id")["pred_category"] for f in pred_frames], axis=1)
    dom = pd.concat(
        [f.set_index("id")["pred_operational_domain"] for f in pred_frames], axis=1
    )
    return {
        "category_consistency": round(float((cat.nunique(axis=1) == 1).mean()), 4),
        "domain_consistency": round(float((dom.nunique(axis=1) == 1).mean()), 4),
    }


def build_stability_report(
    per_run: list[dict], summary: dict, consistency: dict
) -> str:
    """Format a human-readable stability report.

    Args:
        per_run: Per-run metric dicts.
        summary: Aggregated stats from ``summarize_runs``.
        consistency: Per-item label-agreement fractions from ``label_consistency``.

    Returns:
        Multi-line report string.
    """
    n = len(per_run)
    lines = [
        "=" * 70,
        "DEFENSE NEWS CLASSIFIER — STABILITY (multi-run) REPORT",
        "=" * 70,
        "",
        f"Runs     : {n}",
        "Sampling : API default (no temperature -- current models reject it; "
        "strict:true guarantees a valid label)",
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
        "Label consistency (fraction of items with the SAME label across all runs):",
        f"  category : {consistency['category_consistency']:.4f}",
        f"  domain   : {consistency['domain_consistency']:.4f}",
        "",
        "Reading this: 'std' is the run-to-run noise floor. A difference between",
        "two prompt/config variants is only meaningful if it clears about 2x the",
        "std for that metric; smaller gaps are indistinguishable from sampling noise.",
        "Label consistency is the direct determinism measure that replaces the old",
        "temperature=0 knob: 1.000 means every item got the same label every run.",
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


def run_one_pass(client, df: pd.DataFrame) -> pd.DataFrame:
    """Classify every article once and return a predictions DataFrame.

    Args:
        client: Authenticated Anthropic client.
        df: Dataset with columns ``id`` and ``text``.

    Returns:
        DataFrame with columns ``id``, ``pred_category``,
        ``pred_operational_domain``.
    """
    rows = []
    total = len(df)
    for i, (_, row) in enumerate(df.iterrows()):
        pred = classify_with_retry(client, row["text"])
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
    args = parser.parse_args()

    os.makedirs(RUNS_DIR, exist_ok=True)
    df = pd.read_csv(DATA_PATH)
    n_calls = args.runs * len(df)
    print(
        f"Running {args.runs} passes over {len(df)} articles "
        f"= {n_calls} API calls (API-default sampling).\n"
    )

    client = make_client()
    per_run = []
    pred_frames = []
    for k in range(1, args.runs + 1):
        print(f"Run {k}/{args.runs}:", flush=True)
        preds = run_one_pass(client, df)
        preds.to_csv(f"{RUNS_DIR}/predictions_run{k}.csv", index=False)
        pred_frames.append(preds)
        merged = df.merge(preds, on="id")
        per_run.append(headline_metrics(merged))

    summary = summarize_runs(per_run)
    consistency = label_consistency(pred_frames)
    report = build_stability_report(per_run, summary, consistency)
    with open(STABILITY_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + report)
    print(f"\nSaved to {STABILITY_PATH}")


if __name__ == "__main__":
    main()
