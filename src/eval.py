"""
Eval harness for the defense-news classifier.

Runs the classifier on every article in data/synthetic_articles.csv,
then reports accuracy, per-label precision/recall/F1, confusion matrices,
and a misclassification log. All outputs are saved to evals/.

Resume support: if evals/predictions.csv already exists from a previous
run (or partial run), articles that already have predictions are skipped.
"""

import os
import time

import anthropic
import pandas as pd

from classify import classify, make_client

DATA_PATH = "data/synthetic_articles.csv"
PREDS_PATH = "evals/predictions.csv"
METRICS_PATH = "evals/metrics.txt"
CONFUSION_CAT_PATH = "evals/confusion_category.csv"
CONFUSION_DOM_PATH = "evals/confusion_domain.csv"
MISCLASS_PATH = "evals/misclassifications.csv"

SLEEP_BETWEEN_CALLS = 0.3  # seconds; small buffer to stay inside rate limits


# ---------------------------------------------------------------------------
# Metrics (plain Python + pandas — no sklearn dependency)
# ---------------------------------------------------------------------------

def compute_metrics(df: pd.DataFrame, field: str) -> pd.DataFrame:
    """
    Per-label precision, recall, F1, and support for one classification field.
    Rows = labels, columns = [precision, recall, f1, support].
    """
    true_col = field
    pred_col = f"pred_{field}"
    labels = sorted(df[true_col].unique())
    rows = []
    for label in labels:
        tp = int(((df[true_col] == label) & (df[pred_col] == label)).sum())
        fp = int(((df[true_col] != label) & (df[pred_col] == label)).sum())
        fn = int(((df[true_col] == label) & (df[pred_col] != label)).sum())
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) > 0 else 0.0)
        rows.append({
            "label": label,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support": tp + fn,
        })
    return pd.DataFrame(rows).set_index("label")


def confusion_matrix(df: pd.DataFrame, field: str) -> pd.DataFrame:
    """Rows = true label, columns = predicted label."""
    labels = sorted(df[field].unique())
    return pd.crosstab(
        df[field],
        df[f"pred_{field}"],
        rownames=["true"],
        colnames=["predicted"],
    ).reindex(index=labels, columns=labels, fill_value=0)


# ---------------------------------------------------------------------------
# Prediction loop
# ---------------------------------------------------------------------------

def classify_with_retry(client, text: str, max_retries: int = 3) -> dict:
    """Retry on transient 500 / rate-limit errors with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return classify(client, text)
        except (anthropic.InternalServerError, anthropic.RateLimitError) as exc:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** (attempt + 1)  # 2s then 4s
            print(f"  [{exc.__class__.__name__}] retrying in {wait}s...", flush=True)
            time.sleep(wait)


def run_predictions(client, df: pd.DataFrame, done_ids: set) -> None:
    """
    Classify every article whose id is not in done_ids.
    Each prediction is appended to PREDS_PATH immediately after the API call
    so a crash never loses more than one call's work.
    """
    todo = df[~df["id"].isin(done_ids)].reset_index(drop=True)
    total = len(todo)
    write_header = not os.path.exists(PREDS_PATH)

    for i, row in todo.iterrows():
        print(
            f"[{i + 1:3d}/{total}] id={row['id']:3d}  "
            f"{row['category']} × {row['operational_domain']}",
            flush=True,
        )
        pred = classify_with_retry(client, row["text"])
        result = {
            "id": row["id"],
            "pred_category": pred["category"],
            "pred_operational_domain": pred["operational_domain"],
        }
        pd.DataFrame([result]).to_csv(PREDS_PATH, mode="a", header=write_header, index=False)
        write_header = False

        if i + 1 < total:
            time.sleep(SLEEP_BETWEEN_CALLS)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(merged: pd.DataFrame) -> str:
    cat_acc = (merged["category"] == merged["pred_category"]).mean()
    dom_acc = (merged["operational_domain"] == merged["pred_operational_domain"]).mean()
    cat_metrics = compute_metrics(merged, "category")
    dom_metrics = compute_metrics(merged, "operational_domain")
    n_misc = int(
        ((merged["category"] != merged["pred_category"]) |
         (merged["operational_domain"] != merged["pred_operational_domain"])).sum()
    )

    lines = [
        "=" * 62,
        "DEFENSE NEWS CLASSIFIER — EVAL RESULTS",
        "=" * 62,
        "",
        f"Articles evaluated : {len(merged)}",
        "",
        f"Category accuracy           : {cat_acc:.1%}",
        f"Operational domain accuracy : {dom_acc:.1%}",
        "",
        "--- Category: per-label metrics ---",
        cat_metrics.to_string(float_format="{:.3f}".format),
        "",
        "--- Operational domain: per-label metrics ---",
        dom_metrics.to_string(float_format="{:.3f}".format),
        "",
        f"Misclassified : {n_misc} / {len(merged)} ({n_misc / len(merged):.1%})",
        f"  Full log    : {MISCLASS_PATH}",
        f"  Confusion   : {CONFUSION_CAT_PATH}, {CONFUSION_DOM_PATH}",
        "=" * 62,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    os.makedirs("evals", exist_ok=True)

    df = pd.read_csv(DATA_PATH)
    print(f"Loaded {len(df)} articles from {DATA_PATH}\n")

    # Resume: load any predictions from a previous (possibly partial) run.
    if os.path.exists(PREDS_PATH):
        existing_preds = pd.read_csv(PREDS_PATH)
        done_ids = set(existing_preds["id"])
        remaining = len(df) - len(done_ids)
        print(f"Resuming: {len(done_ids)} already predicted, {remaining} remaining.\n")
    else:
        existing_preds = pd.DataFrame(
            columns=["id", "pred_category", "pred_operational_domain"]
        )
        done_ids = set()

    # Run any missing predictions, writing each to PREDS_PATH as it completes.
    if done_ids < set(df["id"]):
        client = make_client()
        run_predictions(client, df, done_ids)
        print(f"\nPredictions saved to {PREDS_PATH}")
    else:
        print("All predictions already present — skipping API calls.\n")

    # Merge ground truth with predictions and compute everything.
    all_preds = pd.read_csv(PREDS_PATH)
    merged = df.merge(all_preds, on="id")

    confusion_matrix(merged, "category").to_csv(CONFUSION_CAT_PATH)
    confusion_matrix(merged, "operational_domain").to_csv(CONFUSION_DOM_PATH)

    misclassified = merged[
        (merged["category"] != merged["pred_category"]) |
        (merged["operational_domain"] != merged["pred_operational_domain"])
    ][["id", "text", "category", "pred_category",
       "operational_domain", "pred_operational_domain"]]
    misclassified.to_csv(MISCLASS_PATH, index=False)

    report = build_report(merged)
    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        f.write(report)

    print("\n" + report)


if __name__ == "__main__":
    main()
