"""v2.1.0 scaled eval: grade 300+ real snippets with the validated Opus judge.

The gold eval (``src/gold_eval.py``) is honest but small -- n=54 hand-labeled snippets,
so a headline like "94.4%" carries a ~13-point-wide 95% CI. This scales the answer key
without scaling the hand-labeling: the Opus judge, already validated against the human
labels on the gold set (94.4% category / 94.4% domain agreement), grades a larger set of
real DVIDS snippets, and the workhorse is measured against it with Wilson confidence
intervals. At n=300 the same accuracy carries a ~5-point CI -- that shrink is the point.

What it is NOT: a second human answer key. Accuracy here is the workhorse agreeing with
the *judge*, which inherits the judge's ~5-6% disagreement-with-human ceiling. Read it
alongside the human-graded gold numbers in ``evals/gold_eval.txt``, not instead of them.

Reuses gold_eval's workhorse+judge prediction loop (via its ``preds_path`` parameter) and
eval.py's metric + Wilson-interval helpers, so every number is computed the same way as the
rest of the harness. Resume-safe: predictions append to evals/scale_predictions.csv as they
complete, so a crash costs at most one snippet.

Run:
    uv run --env-file .env python src/scale_eval.py            # ~2*N synchronous calls
    uv run --env-file .env python src/scale_eval.py --batch    # one Message Batch, ~50% cheaper

Needs ANTHROPIC_API_KEY and a snippet set at data/scale/scale_set.csv (build it with
scripts/build_scale_set.py). Writes the report to evals/scale_eval.txt.
"""

from __future__ import annotations

import argparse
import os

import pandas as pd

from classify import make_client
from eval import compute_metrics, macro_average, wilson_interval
from gold_eval import (
    JUDGE_MODEL,
    WORKHORSE_MODEL,
    run_predictions,
    run_predictions_batch,
)

SCALE_SET_PATH = "data/scale/scale_set.csv"
SCALE_PREDS_PATH = "evals/scale_predictions.csv"
REPORT_PATH = "evals/scale_eval.txt"

# The judge's agreement with the human labels on the n=54 gold set -- the validation that
# earns it the answer-key role here. Sourced from evals/gold_eval.txt; update together.
JUDGE_HUMAN_AGREEMENT = {"category": 0.944, "domain": 0.944}

# (axis label, workhorse column, judge/answer-key column).
AXES = [
    ("category", "pred_category", "judge_category"),
    ("operational_domain", "pred_operational_domain", "judge_operational_domain"),
]


def load_scale_set(path: str = SCALE_SET_PATH) -> pd.DataFrame:
    """Load the unlabeled scaled-eval snippet set.

    Args:
        path: Path to the scale-set CSV. Must have at least ``id`` and ``text``.

    Returns:
        DataFrame with the snippet ``id`` and ``text`` columns.

    Raises:
        ValueError: If required columns are missing.
    """
    df = pd.read_csv(path)
    missing = {"id", "text"} - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
    return df


def _accuracy_row(preds: pd.DataFrame, pred_col: str, judge_col: str) -> dict:
    """Accuracy of the workhorse vs the judge answer key, with a 95% Wilson CI.

    Args:
        preds: Predictions frame with the workhorse + judge columns.
        pred_col: Workhorse column (e.g. ``pred_category``).
        judge_col: Judge (answer-key) column (e.g. ``judge_category``).

    Returns:
        Dict with ``n``, ``correct``, ``accuracy``, ``ci_low``, ``ci_high``.
    """
    correct = int((preds[pred_col] == preds[judge_col]).sum())
    n = len(preds)
    low, high = wilson_interval(correct, n)
    return {
        "n": n,
        "correct": correct,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "ci_low": low,
        "ci_high": high,
    }


def _per_label(preds: pd.DataFrame, pred_col: str, judge_col: str) -> pd.DataFrame:
    """Per-label precision/recall/F1 of the workhorse against the judge answer key.

    Reuses ``eval.compute_metrics`` by aliasing the judge column to the ground-truth
    name it expects and the workhorse column to ``pred_<field>``.

    Args:
        preds: Predictions frame.
        pred_col: Workhorse column.
        judge_col: Judge (answer-key) column.

    Returns:
        Per-label metrics DataFrame indexed by label.
    """
    frame = pd.DataFrame(
        {"label": preds[judge_col].to_numpy(), "pred_label": preds[pred_col].to_numpy()}
    )
    return compute_metrics(frame, "label")


def metrics(preds: pd.DataFrame) -> dict:
    """Compute the scaled eval's headline numbers from a predictions frame.

    Args:
        preds: Frame with ``pred_*`` (workhorse) and ``judge_*`` (answer key) columns.

    Returns:
        Dict keyed by axis (``category``/``operational_domain``), each holding the
        accuracy row (with Wilson CI), per-label metrics, macro-F1, and the judge
        answer-key label distribution.
    """
    out: dict = {"n": len(preds)}
    for axis, pred_col, judge_col in AXES:
        acc = _accuracy_row(preds, pred_col, judge_col)
        per_label = _per_label(preds, pred_col, judge_col)
        out[axis] = {
            **acc,
            "macro_f1": macro_average(per_label)["f1"],
            "per_label": per_label,
            "distribution": preds[judge_col].value_counts().to_dict(),
        }
    return out


def _gold_reference() -> dict | None:
    """The n=54 human-graded accuracy + CI, for the noise-floor-shrink comparison.

    Computed from the committed gold snapshot so the report can show the CI narrowing
    from n=54 to n=300 side by side. Returns None if the gold files aren't present.

    Returns:
        Dict of ``{axis: {accuracy, ci_low, ci_high, n}}`` vs human labels, or None.
    """
    import gold_eval

    if not (
        os.path.exists(gold_eval.GOLD_PATH) and os.path.exists(gold_eval.PREDS_PATH)
    ):
        return None
    gold = gold_eval.load_gold().rename(columns={"domain": "operational_domain"})
    preds = pd.read_csv(gold_eval.PREDS_PATH)
    merged = gold.merge(preds, on="id")
    ref = {}
    for axis, truth in (
        ("category", "category"),
        ("operational_domain", "operational_domain"),
    ):
        correct = int((merged[truth] == merged[f"pred_{axis}"]).sum())
        n = len(merged)
        low, high = wilson_interval(correct, n)
        ref[axis] = {"accuracy": correct / n, "ci_low": low, "ci_high": high, "n": n}
    return ref


def build_report(preds: pd.DataFrame) -> str:
    """Assemble the human-readable scaled-eval report.

    Args:
        preds: Predictions frame (workhorse + judge columns).

    Returns:
        The report as a string.
    """
    m = metrics(preds)
    ref = _gold_reference()
    lines = [
        "=" * 62,
        "v2.1.0 SCALED EVAL -- workhorse vs validated Opus judge",
        "=" * 62,
        "",
        f"Snippets evaluated : {m['n']}   ({SCALE_SET_PATH})",
        f"Workhorse : {WORKHORSE_MODEL}",
        f"Answer key: {JUDGE_MODEL} judge -- validated vs human on the n=54 gold set",
        f"            ({JUDGE_HUMAN_AGREEMENT['category']:.1%} category / "
        f"{JUDGE_HUMAN_AGREEMENT['domain']:.1%} domain agreement).",
        "",
        "Hand-labeling doesn't scale, so the judge is the answer key here. Accuracy",
        "below is the workhorse agreeing with the judge; it inherits the judge's",
        "~5-6% disagreement-with-human ceiling. Read it ALONGSIDE the human-graded",
        "gold numbers in evals/gold_eval.txt, not instead of them.",
        "",
        "-- Workhorse vs judge, with 95% Wilson CIs ----------------",
    ]
    label = {"category": "Category accuracy", "operational_domain": "Domain accuracy  "}
    for axis in ("category", "operational_domain"):
        a = m[axis]
        lines.append(
            f"{label[axis]} : {a['accuracy']:.1%}   "
            f"95% CI [{a['ci_low']:.1%}, {a['ci_high']:.1%}]   "
            f"({a['correct']}/{a['n']})   macro-F1 {a['macro_f1']:.3f}"
        )

    if ref is not None:
        lines += [
            "",
            "-- The noise-floor shrink (why this eval exists) ----------",
            f"Same metric, human-graded on n={ref['category']['n']} (evals/gold_eval.txt):",
        ]
        for axis in ("category", "operational_domain"):
            r, a = ref[axis], m[axis]
            r_w = (r["ci_high"] - r["ci_low"]) * 100
            a_w = (a["ci_high"] - a["ci_low"]) * 100
            lines.append(
                f"  {label[axis].strip()}: {r['accuracy']:.1%} "
                f"CI [{r['ci_low']:.1%}, {r['ci_high']:.1%}] "
                f"(width {r_w:.0f}pts) -> at n={a['n']} width {a_w:.0f}pts"
            )

    for axis, heading in (
        ("category", "Category"),
        ("operational_domain", "Operational domain"),
    ):
        a = m[axis]
        lines += [
            "",
            f"{heading} per-label (workhorse vs judge):",
            a["per_label"].to_string(),
            "",
            "Answer-key label distribution (judge): "
            + ", ".join(f"{k} {v}" for k, v in sorted(a["distribution"].items())),
        ]
    lines.append("=" * 62)
    return "\n".join(lines)


def main() -> None:
    """Run the workhorse+judge pass over the scale set (resume-safe) and report."""
    parser = argparse.ArgumentParser(
        description="v2.1.0 scaled eval with the Opus judge."
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="submit via the Message Batches API (~50%% cheaper, non-interactive).",
    )
    args = parser.parse_args()

    os.makedirs("evals", exist_ok=True)
    scale = load_scale_set()
    print(f"Loaded {len(scale)} snippets from {SCALE_SET_PATH}\n")

    if os.path.exists(SCALE_PREDS_PATH):
        done_ids = set(pd.read_csv(SCALE_PREDS_PATH)["id"])
        print(f"Resuming: {len(done_ids)} already predicted.\n")
    else:
        done_ids = set()

    if set(scale["id"]) - done_ids:
        client = make_client()
        if args.batch:
            run_predictions_batch(client, scale, done_ids, preds_path=SCALE_PREDS_PATH)
        else:
            run_predictions(client, scale, done_ids, preds_path=SCALE_PREDS_PATH)
    else:
        print("All predictions already present -- skipping API calls.\n")

    preds = pd.read_csv(SCALE_PREDS_PATH)
    report = build_report(preds)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report + "\n")
    print("\n" + report)


if __name__ == "__main__":
    main()
