"""v2 eval: score the classifier on the human-labeled gold set, and validate the judge.

Each gold snippet is run through the same classify call on two models:

- the **workhorse** (claude-sonnet-4-6) -> the BASELINE, scored against the human
  labels. This is the classifier's accuracy on *real* news graded against *human*
  truth -- the honest number v1's circular eval (model grading model) couldn't give.
- the **judge** (claude-opus-4-8) -> scored against the human labels for AGREEMENT.
  High judge-vs-human agreement means the judge tracks human judgment, so it can serve
  as a trustworthy, scalable answer key where hand-labeling doesn't reach (Step 3+).

Reuses the metric functions from eval.py. Resume-safe: predictions are appended to
evals/gold_predictions.csv as they complete, so a crash costs at most one snippet.
Writes the report to evals/gold_eval.txt.

Run:
    uv run --env-file .env python src/gold_eval.py

Needs ANTHROPIC_API_KEY and a fully labeled data/gold/gold.csv.
"""

from __future__ import annotations

import os
import time

import anthropic
import pandas as pd

from classify import CATEGORIES, DOMAINS, classify, make_client
from eval import compute_metrics, macro_average

GOLD_PATH = "data/gold/gold.csv"
PREDS_PATH = "evals/gold_predictions.csv"
REPORT_PATH = "evals/gold_eval.txt"

WORKHORSE_MODEL = "claude-sonnet-4-6"
JUDGE_MODEL = "claude-opus-4-8"
SLEEP_BETWEEN_CALLS = 0.3


def load_gold(path: str = GOLD_PATH) -> pd.DataFrame:
    """Load the gold set and fail loudly if it is not fully, validly labeled.

    Args:
        path: Path to the gold CSV. Defaults to ``GOLD_PATH``.

    Returns:
        DataFrame with normalized (stripped, lowercased) ``category`` and
        ``domain`` columns.

    Raises:
        ValueError: If any row is missing a ``category``/``domain`` label, or
            a label falls outside the allowed ``CATEGORIES``/``DOMAINS`` sets.
    """
    df = pd.read_csv(path)
    for col in ("category", "domain"):
        df[col] = df[col].fillna("").astype(str).str.strip().str.lower()

    blank = df[(df["category"] == "") | (df["domain"] == "")]
    if len(blank):
        raise ValueError(
            f"{len(blank)} of {len(df)} gold rows are unlabeled. Finish labeling "
            f"{path} first. First unlabeled ids: {list(blank['id'][:5])}"
        )
    bad_cat = sorted(set(df["category"]) - set(CATEGORIES))
    bad_dom = sorted(set(df["domain"]) - set(DOMAINS))
    if bad_cat or bad_dom:
        raise ValueError(
            f"invalid labels in {path} -- category {bad_cat}, domain {bad_dom}"
        )
    return df


def classify_retry(
    client: anthropic.Anthropic, text: str, model: str, max_retries: int = 3
) -> dict:
    """classify() with exponential backoff on transient API errors.

    Args:
        client: Authenticated Anthropic client.
        text: Article snippet to classify.
        model: Which Claude model to classify with.
        max_retries: Maximum number of attempts before re-raising.

    Returns:
        Dict with keys ``category`` and ``operational_domain``.

    Raises:
        anthropic.InternalServerError: If all retries are exhausted on a 500.
        anthropic.RateLimitError: If all retries are exhausted on a 429.
    """
    for attempt in range(max_retries):
        try:
            return classify(client, text, model=model)
        except (anthropic.InternalServerError, anthropic.RateLimitError):
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise ValueError("max_retries must be >= 1")


def run_predictions(
    client: anthropic.Anthropic, df: pd.DataFrame, done_ids: set
) -> None:
    """Classify every not-yet-done snippet with both models, appending as we go.

    Args:
        client: Authenticated Anthropic client.
        df: Gold DataFrame with at least columns ``id`` and ``text``.
        done_ids: Set of article IDs that already have predictions and can
            be skipped.
    """
    todo = df[~df["id"].isin(done_ids)].reset_index(drop=True)
    write_header = not os.path.exists(PREDS_PATH)
    for i, (_, row) in enumerate(todo.iterrows()):
        print(f"[{i + 1:3d}/{len(todo)}] {row['id']}", flush=True)
        base = classify_retry(client, row["text"], WORKHORSE_MODEL)
        judge = classify_retry(client, row["text"], JUDGE_MODEL)
        result = {
            "id": row["id"],
            "pred_category": base["category"],
            "pred_operational_domain": base["operational_domain"],
            "judge_category": judge["category"],
            "judge_operational_domain": judge["operational_domain"],
        }
        pd.DataFrame([result]).to_csv(
            PREDS_PATH, mode="a", header=write_header, index=False
        )
        write_header = False
        time.sleep(SLEEP_BETWEEN_CALLS)


def _accuracy(a: pd.Series, b: pd.Series) -> float:
    """Fraction of positions where ``a`` and ``b`` are equal."""
    return float((a == b).mean())


def build_report(merged: pd.DataFrame) -> str:
    """Format the baseline metrics and the judge-vs-human agreement check.

    Args:
        merged: Gold DataFrame merged with both the workhorse and judge
            predictions (columns ``pred_*`` and ``judge_*``).

    Returns:
        Multi-line report string.
    """
    # Baseline: workhorse predictions vs human gold labels.
    cat_acc = _accuracy(merged["category"], merged["pred_category"])
    dom_acc = _accuracy(merged["operational_domain"], merged["pred_operational_domain"])
    cat_macro = macro_average(compute_metrics(merged, "category"))
    dom_macro = macro_average(compute_metrics(merged, "operational_domain"))
    cat_metrics = compute_metrics(merged, "category")
    dom_metrics = compute_metrics(merged, "operational_domain")

    # Judge vs human, and workhorse vs judge.
    j_cat = _accuracy(merged["category"], merged["judge_category"])
    j_dom = _accuracy(merged["operational_domain"], merged["judge_operational_domain"])
    wj_cat = _accuracy(merged["pred_category"], merged["judge_category"])
    wj_dom = _accuracy(
        merged["pred_operational_domain"], merged["judge_operational_domain"]
    )

    lines = [
        "=" * 62,
        "v2 GOLD-SET EVAL -- real text, human-labeled",
        "=" * 62,
        "",
        f"Snippets evaluated : {len(merged)}   ({GOLD_PATH})",
        "",
        f"Workhorse : {WORKHORSE_MODEL}",
        f"Judge     : {JUDGE_MODEL}",
        "",
        "-- Baseline: workhorse vs human labels --------------------",
        "The classifier's accuracy on REAL news, graded against human",
        "truth -- the honest number v1's circular eval couldn't give.",
        "",
        f"Category accuracy           : {cat_acc:.1%}   (macro-F1 {cat_macro['f1']:.3f})",
        f"Operational domain accuracy : {dom_acc:.1%}   (macro-F1 {dom_macro['f1']:.3f})",
        "",
        "Category per-label:",
        cat_metrics.to_string(float_format="{:.3f}".format),
        "",
        "Operational domain per-label:",
        dom_metrics.to_string(float_format="{:.3f}".format),
        "",
        "-- Judge validation: judge vs human labels ----------------",
        "High agreement => the judge tracks human judgment, so it can",
        "serve as a scalable answer key where hand-labeling doesn't reach.",
        "",
        f"Category agreement          : {j_cat:.1%}",
        f"Operational domain agreement : {j_dom:.1%}",
        "",
        "-- Workhorse vs judge (do the two models agree?) ----------",
        f"Category           : {wj_cat:.1%}",
        f"Operational domain : {wj_dom:.1%}",
        "=" * 62,
    ]
    return "\n".join(lines)


def main() -> None:
    """Run both models on the gold set (resuming if possible), then score + report.

    Raises:
        EnvironmentError: If ``ANTHROPIC_API_KEY`` is not set (via make_client).
    """
    os.makedirs("evals", exist_ok=True)
    gold = load_gold()
    print(f"Loaded {len(gold)} labeled gold snippets from {GOLD_PATH}\n")

    if os.path.exists(PREDS_PATH):
        done_ids = set(pd.read_csv(PREDS_PATH)["id"])
        print(f"Resuming: {len(done_ids)} already predicted.\n")
    else:
        done_ids = set()

    if set(gold["id"]) - done_ids:
        client = make_client()
        run_predictions(client, gold, done_ids)
    else:
        print("All predictions already present -- skipping API calls.\n")

    preds = pd.read_csv(PREDS_PATH)
    merged = gold.rename(columns={"domain": "operational_domain"}).merge(preds, on="id")

    report = build_report(merged)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report)
    print("\n" + report)


if __name__ == "__main__":
    main()
