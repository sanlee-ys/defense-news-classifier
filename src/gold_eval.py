"""v2 eval: score the classifier on the human-labeled gold set and validate the judge.

Each gold snippet is run through the same classify call on two models:

- The **workhorse** (claude-sonnet-5) -> the BASELINE, scored against the human
  labels. This is the classifier's accuracy on *real* news graded against *human*
  truth -- the honest number v1's circular eval (model grading model) couldn't give.
- The **judge** (claude-opus-4-8) -> scored against the human labels for AGREEMENT.
  High judge-vs-human agreement means the judge tracks human judgment, so it can serve
  as a trustworthy, scalable answer key where hand-labeling doesn't reach (Step 3+).

Reuses the metric functions from eval.py. Resume-safe: predictions are appended to
evals/gold_predictions.csv as they complete, so a crash costs at most one snippet.
Writes the report to evals/gold_eval.txt.

Run:
    uv run --env-file .env python src/gold_eval.py

Needs ANTHROPIC_API_KEY and a fully labeled data/gold/gold.csv.

Pass --batch to classify both the workhorse and judge passes via the Message
Batches API in a single submission instead of 2*N synchronous calls -- see
decisions/009 for when that tradeoff (cheaper, non-interactive) is worth it.
"""

from __future__ import annotations

import argparse
import os
import time

import anthropic
import pandas as pd

from classify import (
    CATEGORIES,
    DOMAINS,
    BatchItemError,
    InvalidLabelError,
    build_batch_request,
    classify,
    make_client,
    parse_batch_result,
)
from eval import compute_metrics, macro_average

GOLD_PATH = "data/gold/gold.csv"
PREDS_PATH = "evals/gold_predictions.csv"
REPORT_PATH = "evals/gold_eval.txt"

WORKHORSE_MODEL = "claude-sonnet-5"
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
    client: anthropic.Anthropic,
    df: pd.DataFrame,
    done_ids: set,
    preds_path: str = PREDS_PATH,
) -> None:
    """Classify every not-yet-done snippet with both models, appending as we go.

    Args:
        client: Authenticated Anthropic client.
        df: Gold DataFrame with at least columns ``id`` and ``text``.
        done_ids: Set of article IDs that already have predictions and can
            be skipped.
        preds_path: CSV the workhorse+judge predictions are appended to. Defaults
            to the gold-eval snapshot; the scaled eval (v2.1.0) passes its own path
            to reuse this exact loop over a larger, unlabeled snippet set.
    """
    todo = df[~df["id"].isin(done_ids)].reset_index(drop=True)
    write_header = not os.path.exists(preds_path)
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
            preds_path, mode="a", header=write_header, index=False
        )
        write_header = False
        time.sleep(SLEEP_BETWEEN_CALLS)


# custom_id separator for the batch path -- joins the gold row id and which
# model produced that request, so a single batch can carry both the workhorse
# and judge passes and still be regrouped back into one row per gold id.
_BATCH_ID_SEP = "::"


def run_predictions_batch(
    client: anthropic.Anthropic,
    df: pd.DataFrame,
    done_ids: set,
    poll_interval: float = 30.0,
    preds_path: str = PREDS_PATH,
) -> None:
    """Classify every not-yet-done snippet with both models via the Message Batches API.

    An alternative to run_predictions() for the gold-eval workhorse + judge
    pass: submits both models' requests for every not-yet-done row as ONE
    batch (2*N requests) instead of 2*N synchronous calls, at ~50% of the
    per-token cost. See decisions/009 for the full tradeoff -- in particular,
    results only land once the whole batch ends (usually within an hour), so
    this suits an unattended/cron run rather than an interactive one.

    Args:
        client: Authenticated Anthropic client.
        df: Gold DataFrame with at least columns ``id`` and ``text``.
        done_ids: Set of article IDs that already have predictions and can
            be skipped.
        poll_interval: Seconds to sleep between polling the batch's status.
        preds_path: CSV the workhorse+judge predictions are appended to. Defaults
            to the gold-eval snapshot; the scaled eval (v2.1.0) passes its own path.
    """
    todo = df[~df["id"].isin(done_ids)].reset_index(drop=True)
    if todo.empty:
        return

    requests = []
    for _, row in todo.iterrows():
        requests.append(
            build_batch_request(
                f"{row['id']}{_BATCH_ID_SEP}workhorse",
                row["text"],
                model=WORKHORSE_MODEL,
            )
        )
        requests.append(
            build_batch_request(
                f"{row['id']}{_BATCH_ID_SEP}judge", row["text"], model=JUDGE_MODEL
            )
        )
    print(
        f"Submitting a batch of {len(requests)} requests ({len(todo)} rows x 2 models)...",
        flush=True,
    )
    batch = client.messages.batches.create(requests=requests)
    print(
        f"Batch {batch.id} submitted; polling every {poll_interval:.0f}s...", flush=True
    )

    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        print(
            f"  status={batch.processing_status}  "
            f"processing={batch.request_counts.processing}",
            flush=True,
        )
        time.sleep(poll_interval)

    print("Batch ended; retrieving results...", flush=True)
    by_row: dict[str, dict] = {}
    for result in client.messages.batches.results(batch.id):
        row_id, _, which = result.custom_id.rpartition(_BATCH_ID_SEP)
        try:
            pred = parse_batch_result(result)
        except (BatchItemError, InvalidLabelError) as exc:
            # Skip this row entirely (both models) rather than write a
            # half-filled record -- it stays out of done_ids, so a later run
            # (sync or batch) picks it back up.
            print(f"  [skip] id={row_id} ({which}): {exc}", flush=True)
            by_row.pop(row_id, None)
            by_row[row_id] = {"_incomplete": True}
            continue
        entry = by_row.setdefault(row_id, {})
        if entry.get("_incomplete"):
            continue
        if which == "workhorse":
            entry["pred_category"] = pred["category"]
            entry["pred_operational_domain"] = pred["operational_domain"]
        else:
            entry["judge_category"] = pred["category"]
            entry["judge_operational_domain"] = pred["operational_domain"]

    write_header = not os.path.exists(preds_path)
    for row_id, entry in by_row.items():
        if entry.get("_incomplete") or len(entry) < 4:
            continue  # missing a model's result for this row -- leave it todo
        out = {"id": row_id, **entry}
        pd.DataFrame([out]).to_csv(
            preds_path, mode="a", header=write_header, index=False
        )
        write_header = False


def _accuracy(a: pd.Series, b: pd.Series) -> float:
    """Fraction of positions where ``a`` and ``b`` are equal."""
    return float((a == b).mean())


def metrics(merged: pd.DataFrame) -> dict:
    """Compute the workhorse-vs-human and judge-vs-human numbers.

    Single source of truth for the scored numbers: build_report() formats these
    for humans below, and src/eval_gate.py grades them against evals/thresholds.toml.
    Per-label tables and the workhorse-vs-judge agreement check are report-only
    detail and stay local to build_report(), since nothing gates on them.

    Args:
        merged: Gold DataFrame merged with both the workhorse and judge
            predictions (columns ``pred_*`` and ``judge_*``).

    Returns:
        Dict with ``n`` and the accuracy / macro-F1 numbers: ``category_accuracy``,
        ``category_macro_f1``, ``domain_accuracy``, ``domain_macro_f1``,
        ``judge_category_agreement``, ``judge_domain_agreement``.
    """
    cat_macro = macro_average(compute_metrics(merged, "category"))
    dom_macro = macro_average(compute_metrics(merged, "operational_domain"))
    return {
        "n": len(merged),
        "category_accuracy": _accuracy(merged["category"], merged["pred_category"]),
        "category_macro_f1": cat_macro["f1"],
        "domain_accuracy": _accuracy(
            merged["operational_domain"], merged["pred_operational_domain"]
        ),
        "domain_macro_f1": dom_macro["f1"],
        "judge_category_agreement": _accuracy(
            merged["category"], merged["judge_category"]
        ),
        "judge_domain_agreement": _accuracy(
            merged["operational_domain"], merged["judge_operational_domain"]
        ),
    }


def build_report(merged: pd.DataFrame) -> str:
    """Format the baseline metrics and the judge-vs-human agreement check.

    Args:
        merged: Gold DataFrame merged with both the workhorse and judge
            predictions (columns ``pred_*`` and ``judge_*``).

    Returns:
        Multi-line report string.
    """
    m = metrics(merged)

    # Per-label tables and workhorse-vs-judge agreement are report-only detail,
    # not part of metrics()'s gated numbers.
    cat_metrics = compute_metrics(merged, "category")
    dom_metrics = compute_metrics(merged, "operational_domain")
    wj_cat = _accuracy(merged["pred_category"], merged["judge_category"])
    wj_dom = _accuracy(
        merged["pred_operational_domain"], merged["judge_operational_domain"]
    )

    lines = [
        "=" * 62,
        "v2 GOLD-SET EVAL -- real text, human-labeled",
        "=" * 62,
        "",
        f"Snippets evaluated : {m['n']}   ({GOLD_PATH})",
        "",
        f"Workhorse : {WORKHORSE_MODEL}",
        f"Judge     : {JUDGE_MODEL}",
        "",
        "-- Baseline: workhorse vs human labels --------------------",
        "The classifier's accuracy on REAL news, graded against human",
        "truth -- the honest number v1's circular eval couldn't give.",
        "",
        f"Category accuracy           : {m['category_accuracy']:.1%}   (macro-F1 {m['category_macro_f1']:.3f})",
        f"Operational domain accuracy : {m['domain_accuracy']:.1%}   (macro-F1 {m['domain_macro_f1']:.3f})",
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
        f"Category agreement          : {m['judge_category_agreement']:.1%}",
        f"Operational domain agreement : {m['judge_domain_agreement']:.1%}",
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
    parser = argparse.ArgumentParser(description="v2 gold-set eval + judge validation.")
    parser.add_argument(
        "--batch",
        action="store_true",
        help=(
            "classify both the workhorse and judge passes via the Message "
            "Batches API in one submission instead of 2*N synchronous calls "
            "-- ~50%% cheaper, non-interactive (results land once the whole "
            "batch ends, usually within an hour)"
        ),
    )
    args = parser.parse_args()

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
        if args.batch:
            run_predictions_batch(client, gold, done_ids)
        else:
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
