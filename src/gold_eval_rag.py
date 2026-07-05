"""v2 Step 3 eval: does retrieval grounding beat the un-grounded baseline?

Runs the grounded classifier (``classify_grounded``) on the gold set and compares it to the
baseline predictions already produced by src/gold_eval.py (evals/gold_predictions.csv), both
graded against the human labels. Reports accuracy and macro-F1 for baseline vs grounded, the
delta, and a flip analysis: of the calls grounding *changed*, how many went wrong->right vs
right->wrong. That flip count is the honest verdict -- a positive delta from lucky lateral
moves is not the same as grounding actually fixing errors.

Resume-safe; writes evals/gold_rag_eval.txt. Needs ANTHROPIC_API_KEY, a labeled
data/gold/gold.csv, and the baseline predictions from a prior gold_eval.py run.

Run:
    uv run --env-file .env python src/gold_eval_rag.py
"""

from __future__ import annotations

import os
import time

import anthropic
import pandas as pd

from classify import make_client
from classify_rag import classify_grounded
from eval import compute_metrics, macro_average
from gold_eval import PREDS_PATH, load_gold
from retrieve import Retriever, load_corpus

RAG_PREDS_PATH = "evals/gold_rag_predictions.csv"
REPORT_PATH = "evals/gold_rag_eval.txt"
RETRIEVE_K = 3
SLEEP_BETWEEN_CALLS = 0.3


def classify_retry(
    client: anthropic.Anthropic, text: str, retriever: Retriever, max_retries: int = 3
) -> dict:
    """classify_grounded() with backoff on transient API errors.

    Args:
        client: Authenticated Anthropic client.
        text: Article snippet to classify.
        retriever: Retriever used to fetch grounding context.
        max_retries: Maximum number of attempts before re-raising.

    Returns:
        Dict with keys ``category``, ``operational_domain``, and ``citations``.

    Raises:
        anthropic.InternalServerError: If all retries are exhausted on a 500.
        anthropic.RateLimitError: If all retries are exhausted on a 429.
    """
    for attempt in range(max_retries):
        try:
            return classify_grounded(client, text, retriever, k=RETRIEVE_K)
        except (anthropic.InternalServerError, anthropic.RateLimitError):
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise ValueError("max_retries must be >= 1")


def run_grounded(
    client: anthropic.Anthropic,
    df: pd.DataFrame,
    retriever: Retriever,
    done_ids: set,
) -> None:
    """Grounded-classify every not-yet-done snippet, appending as we go.

    Args:
        client: Authenticated Anthropic client.
        df: Gold DataFrame with at least columns ``id`` and ``text``.
        retriever: Retriever used to fetch grounding context.
        done_ids: Set of article IDs that already have grounded predictions
            and can be skipped.
    """
    todo = df[~df["id"].isin(done_ids)].reset_index(drop=True)
    write_header = not os.path.exists(RAG_PREDS_PATH)
    for i, (_, row) in enumerate(todo.iterrows()):
        print(f"[{i + 1:3d}/{len(todo)}] {row['id']}", flush=True)
        result = classify_retry(client, row["text"], retriever)
        out = {
            "id": row["id"],
            "rag_category": result["category"],
            "rag_operational_domain": result["operational_domain"],
            "citations": ";".join(c["id"] for c in result["citations"]),
        }
        pd.DataFrame([out]).to_csv(
            RAG_PREDS_PATH, mode="a", header=write_header, index=False
        )
        write_header = False
        time.sleep(SLEEP_BETWEEN_CALLS)


def _acc(truth: pd.Series, pred: pd.Series) -> float:
    """Fraction of positions where ``truth`` and ``pred`` are equal."""
    return float((truth == pred).mean())


def _macro_f1(merged: pd.DataFrame, field: str, pred_col: str) -> float:
    """Macro-F1 for ``field`` using ``pred_col`` as the prediction column."""
    tmp = pd.DataFrame({field: merged[field], f"pred_{field}": merged[pred_col]})
    return float(macro_average(compute_metrics(tmp, field))["f1"])


def _flip_line(merged: pd.DataFrame, field: str, label: str) -> str:
    """Summarize how grounding changed calls for one field: wrong->right vs. right->wrong vs. lateral."""
    base_right = merged[f"pred_{field}"] == merged[field]
    rag_right = merged[f"rag_{field}"] == merged[field]
    changed = merged[f"pred_{field}"] != merged[f"rag_{field}"]
    w2r = int((changed & ~base_right & rag_right).sum())
    r2w = int((changed & base_right & ~rag_right).sum())
    lateral = int(changed.sum()) - w2r - r2w
    return (
        f"{label}: grounding changed {int(changed.sum())} calls "
        f"-> {w2r} wrong->right, {r2w} right->wrong, {lateral} lateral"
    )


def build_report(merged: pd.DataFrame) -> str:
    """Compare baseline (pred_*) vs grounded (rag_*) against the human labels.

    Args:
        merged: Gold DataFrame merged with both baseline (``pred_*``) and
            grounded (``rag_*``) predictions.

    Returns:
        Multi-line report string with accuracy/macro-F1 deltas and flip counts.
    """
    rows = [
        (
            "Category accuracy",
            _acc(merged["category"], merged["pred_category"]),
            _acc(merged["category"], merged["rag_category"]),
            "{:.1%}",
        ),
        (
            "Category macro-F1",
            _macro_f1(merged, "category", "pred_category"),
            _macro_f1(merged, "category", "rag_category"),
            "{:.3f}",
        ),
        (
            "Domain accuracy",
            _acc(merged["operational_domain"], merged["pred_operational_domain"]),
            _acc(merged["operational_domain"], merged["rag_operational_domain"]),
            "{:.1%}",
        ),
        (
            "Domain macro-F1",
            _macro_f1(merged, "operational_domain", "pred_operational_domain"),
            _macro_f1(merged, "operational_domain", "rag_operational_domain"),
            "{:.3f}",
        ),
    ]

    lines = [
        "=" * 62,
        "v2 STEP 3 -- RETRIEVAL-GROUNDED vs BASELINE",
        "=" * 62,
        "",
        f"Snippets : {len(merged)}    retrieve k={RETRIEVE_K}",
        "Baseline = src/classify.py (no retrieval); Grounded = + top-k corpus context.",
        "",
        f"{'':<20}{'baseline':>10}{'grounded':>10}{'delta':>10}",
    ]
    for name, base, rag, fmt in rows:
        delta = rag - base
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"{name:<20}{fmt.format(base):>10}{fmt.format(rag):>10}"
            f"{sign + fmt.format(delta):>10}"
        )
    lines += [
        "",
        _flip_line(merged, "category", "Category"),
        _flip_line(merged, "operational_domain", "Domain"),
        "=" * 62,
    ]
    return "\n".join(lines)


def main() -> None:
    """Run grounded classification on the gold set, then score the lift vs baseline.

    Raises:
        EnvironmentError: If ``ANTHROPIC_API_KEY`` is not set (via make_client).
    """
    os.makedirs("evals", exist_ok=True)
    gold = load_gold()
    retriever = Retriever(load_corpus())
    print(f"gold: {len(gold)} snippets | corpus: {len(retriever.docs)} docs\n")

    done_ids = (
        set(pd.read_csv(RAG_PREDS_PATH)["id"])
        if os.path.exists(RAG_PREDS_PATH)
        else set()
    )
    if set(gold["id"]) - done_ids:
        run_grounded(make_client(), gold, retriever, done_ids)
    else:
        print("All grounded predictions already present -- skipping API calls.\n")

    base = pd.read_csv(PREDS_PATH)[["id", "pred_category", "pred_operational_domain"]]
    rag = pd.read_csv(RAG_PREDS_PATH)
    merged = (
        gold.rename(columns={"domain": "operational_domain"})
        .merge(base, on="id")
        .merge(rag, on="id")
    )

    report = build_report(merged)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report)
    print("\n" + report)


if __name__ == "__main__":
    main()
