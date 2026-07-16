"""Per-cell confusion breakdown for the gold set -- the mechanical view.

``gold_eval.py`` reports the gold-set numbers as aggregates (accuracy, macro-F1,
per-label precision/recall, and headline agreement rates). This module drills one
level down: for each classification axis it builds the full confusion matrix and,
crucially, lists **which article ids fall in every off-diagonal cell** -- so a
disagreement like "technology graded as operations" is a named, inspectable set of
snippets (g007, g036, g040), not just a count.

It reads the two CSVs ``gold_eval.py`` already writes and joins them on ``id`` --
no API key, no network, nothing to re-run. It surfaces three comparisons per axis:

- **workhorse vs human** -- the classifier's real accuracy against human truth.
- **judge vs human** -- whether the Opus judge tracks human judgment well enough to
  serve as a scalable answer key (the check that gates scaling the eval past the
  hand-labeled set).
- **workhorse vs judge** -- whether the two models agree, usable where no human
  label exists.

Reuses ``eval.py``'s metric functions so the numbers match the rest of the harness.

Run:
    uv run python src/eval_confusion.py

Reads ``data/gold/gold.csv`` and ``evals/gold_predictions.csv``; writes a Markdown
report to ``evals/gold_confusion.md`` and the two judge-vs-human matrices to
``evals/gold_confusion_{category,domain}.csv``.
"""

from __future__ import annotations

import os

import pandas as pd

from eval import compute_metrics, confusion_matrix, macro_average

GOLD_PATH = "data/gold/gold.csv"
PREDS_PATH = "evals/gold_predictions.csv"
REPORT_PATH = "evals/gold_confusion.md"
CONFUSION_CSV = {
    "category": "evals/gold_confusion_category.csv",
    "operational_domain": "evals/gold_confusion_domain.csv",
}

# (axis field on the merged frame, human-facing heading).
AXES = [("category", "Category"), ("operational_domain", "Operational domain")]


def load_merged(
    gold_path: str = GOLD_PATH, preds_path: str = PREDS_PATH
) -> pd.DataFrame:
    """Join human gold labels with the workhorse + judge predictions on ``id``.

    Mirrors the merge in ``gold_eval.main`` so the two stay consistent: gold's
    ``domain`` column is renamed to ``operational_domain`` to match the prediction
    columns and the rest of the harness.

    Args:
        gold_path: Path to the human-labeled gold CSV.
        preds_path: Path to the predictions CSV (``pred_*`` + ``judge_*`` columns).

    Returns:
        Merged DataFrame with human truth (``category``, ``operational_domain``),
        the workhorse (``pred_*``) and the judge (``judge_*``) columns, plus ``id``.
    """
    gold = pd.read_csv(gold_path).rename(columns={"domain": "operational_domain"})
    preds = pd.read_csv(preds_path)
    return gold.merge(preds, on="id")


def _view(
    merged: pd.DataFrame, truth_col: str, pred_col: str, field: str
) -> pd.DataFrame:
    """Reshape any (truth, prediction) pair into the shape ``eval.py`` expects.

    ``eval.py``'s ``compute_metrics``/``confusion_matrix`` score ``field`` against
    ``pred_{field}``. Aliasing an arbitrary column pair into those two names lets us
    reuse them for judge-vs-human and workhorse-vs-judge, not just workhorse-vs-human.

    Args:
        merged: The joined frame from :func:`load_merged`.
        truth_col: Column to treat as ground truth.
        pred_col: Column to treat as the prediction.
        field: Axis name to expose (``"category"`` or ``"operational_domain"``).

    Returns:
        A two-column frame with columns ``field`` and ``pred_{field}``.
    """
    return pd.DataFrame(
        {
            field: merged[truth_col].to_numpy(),
            f"pred_{field}": merged[pred_col].to_numpy(),
        }
    )


def disagreement_cells(
    merged: pd.DataFrame, truth_col: str, pred_col: str, id_col: str = "id"
) -> list[tuple[str, str, list[str]]]:
    """List every off-diagonal confusion cell together with the ids it contains.

    Args:
        merged: The joined frame from :func:`load_merged`.
        truth_col: Column treated as ground truth.
        pred_col: Column treated as the prediction.
        id_col: Column holding the snippet identifier.

    Returns:
        ``(truth_label, pred_label, [ids])`` tuples for each cell where truth and
        prediction differ, sorted by descending cell size then by label.
    """
    wrong = merged[merged[truth_col] != merged[pred_col]]
    cells: dict[tuple[str, str], list[str]] = {}
    for _, row in wrong.iterrows():
        cells.setdefault((row[truth_col], row[pred_col]), []).append(str(row[id_col]))
    return sorted(
        ((t, p, ids) for (t, p), ids in cells.items()),
        key=lambda c: (-len(c[2]), c[0], c[1]),
    )


def _accuracy(truth: pd.Series, pred: pd.Series) -> float:
    """Fraction of rows where prediction equals truth."""
    return float((truth == pred).mean())


def render_comparison(
    merged: pd.DataFrame,
    field: str,
    truth_col: str,
    pred_col: str,
    title: str,
    with_per_label: bool,
) -> str:
    """Render one comparison: agreement, confusion matrix, and disagreement cells.

    Args:
        merged: The joined frame from :func:`load_merged`.
        field: Axis name (``"category"`` or ``"operational_domain"``).
        truth_col: Column treated as ground truth.
        pred_col: Column treated as the prediction.
        title: Heading for this comparison (e.g. ``"judge vs human"``).
        with_per_label: Whether to include per-label precision/recall/F1 and
            macro-F1 (meaningful only when the truth column is a human label).

    Returns:
        A Markdown section as a string.
    """
    view = _view(merged, truth_col, pred_col, field)
    n = len(view)
    correct = int((view[field] == view[f"pred_{field}"]).sum())
    matrix = confusion_matrix(view, field)

    lines = [f"### {title} -- {correct / n:.1%} ({correct}/{n})", ""]
    lines += [
        "```",
        "rows = truth, columns = prediction",
        matrix.to_string(),
        "```",
        "",
    ]

    if with_per_label:
        metrics = compute_metrics(view, field)
        macro = macro_average(metrics)
        lines += ["per-label (precision / recall / f1 / support):", "", "```"]
        lines += [metrics.to_string(), "```", f"macro-F1: {macro['f1']:.3f}", ""]

    cells = disagreement_cells(merged, truth_col, pred_col)
    lines.append(f"disagreements ({n - correct}):")
    if cells:
        for truth_label, pred_label, ids in cells:
            lines.append(
                f"- true={truth_label} pred={pred_label} "
                f"x{len(ids)} [{', '.join(ids)}]"
            )
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def build_report(merged: pd.DataFrame) -> str:
    """Assemble the full Markdown report over both axes and all three comparisons.

    Args:
        merged: The joined frame from :func:`load_merged`.

    Returns:
        The complete report as a Markdown string.
    """
    header = [
        "# Gold-set confusion report",
        "",
        f"Generated from `{GOLD_PATH}` (human truth) x `{PREDS_PATH}` "
        "(workhorse `pred_*`, judge `judge_*`), joined on `id`. "
        f"n={len(merged)}.",
        "",
        "Three comparisons per axis:",
        "",
        "- **workhorse vs human** -- the classifier's real accuracy (the product number).",
        "- **judge vs human** -- can the judge stand in for a human labeler? "
        "(gates scaling the eval past the hand-labeled set).",
        "- **workhorse vs judge** -- do the two models agree, where no human label exists?",
        "",
        "Read a matrix: rows = truth, columns = prediction, the diagonal is correct. "
        "A row reads as recall (of the truly-X, how many were caught); a column reads "
        "as precision (of those called X, how many were right).",
        "",
    ]

    sections: list[str] = []
    for field, heading in AXES:
        sections.append(f"## {heading}\n")
        comparisons = [
            ("workhorse vs human", field, f"pred_{field}", True),
            ("judge vs human", field, f"judge_{field}", True),
            ("workhorse vs judge", f"pred_{field}", f"judge_{field}", False),
        ]
        for title, truth_col, pred_col, with_per_label in comparisons:
            sections.append(
                render_comparison(
                    merged, field, truth_col, pred_col, title, with_per_label
                )
            )
    return "\n".join(header + sections)


def main() -> None:
    """Build the report, write it and the judge-vs-human matrices, print it."""
    os.makedirs("evals", exist_ok=True)
    merged = load_merged()

    report = build_report(merged)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report)

    # Persist the judge-vs-human matrices as CSV -- the decision-critical
    # comparison for scaling the eval -- so they are machine-readable too.
    for field, path in CONFUSION_CSV.items():
        view = _view(merged, field, f"judge_{field}", field)
        confusion_matrix(view, field).to_csv(path)

    print(report)
    print(f"\nWrote {REPORT_PATH} and {', '.join(CONFUSION_CSV.values())}")


if __name__ == "__main__":
    main()
