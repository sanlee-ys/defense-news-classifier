"""Haiku eval arm: benchmark claude-haiku-4-5 against the committed workhorse.

Anthropic's classification use-case guide recommends *starting* with the
cheapest tier and escalating only if evals show a gap. The classifier has always
run the Sonnet workhorse; it has never measured the Haiku tier. This adds that
arm so the "which model" call is decided by the eval, not by default (the same
principle CLAUDE.md states for feature scope).

Design: this mirrors src/gold_eval_rag.py -- run one new arm on the gold set,
then compare it against the *already-committed* baseline (the Sonnet workhorse
in evals/gold_predictions.csv), both graded against the human labels. It does
NOT touch gold_predictions.csv's schema or the eval_gate floors: Haiku is a
benchmark to inform escalation, not a shipped capability with a floor, so
gating it would wrongly pin Haiku as the workhorse. Reuses the exact classify()
call shape (ungrounded, strict tool use) and the Message Batches path from the
already-merged batch work, so Haiku is apples-to-apples with the Sonnet
baseline.

The report leads with Haiku's absolute accuracy/macro-F1 and the delta vs the
Sonnet baseline, plus a flip analysis: of the calls where Haiku and Sonnet
disagree, how many did Haiku get right that Sonnet got wrong (Haiku better) vs
wrong that Sonnet got right (the escalation gap). That flip count is the honest
"is it worth paying for Sonnet" signal.

Resume-safe; writes evals/gold_haiku_eval.txt. Needs ANTHROPIC_API_KEY, a
labeled data/gold/gold.csv, and the committed Sonnet baseline from a prior
gold_eval.py run.

Run:
    uv run --env-file .env python src/gold_eval_haiku.py
    uv run --env-file .env python src/gold_eval_haiku.py --batch   # ~50% cheaper
"""

from __future__ import annotations

import argparse
import os
import time

import anthropic
import pandas as pd

from classify import (
    BatchItemError,
    InvalidLabelError,
    build_batch_request,
    make_client,
    parse_batch_result,
)
from eval import compute_metrics, macro_average
from gold_eval import WORKHORSE_MODEL, classify_retry, load_gold

# Frozen v2 workhorse snapshot -- the baseline this comparison was measured
# against. Deliberately NOT gold_eval.PREDS_PATH, which moved to the v3
# three-axis file (ADR-014); repointing would compare the stored Haiku arm
# against a different era's baseline.
PREDS_PATH = "evals/gold_predictions.csv"

HAIKU_MODEL = "claude-haiku-4-5"
HAIKU_PREDS_PATH = "evals/gold_haiku_predictions.csv"
REPORT_PATH = "evals/gold_haiku_eval.txt"
SLEEP_BETWEEN_CALLS = 0.3


def run_predictions(
    client: anthropic.Anthropic, df: pd.DataFrame, done_ids: set
) -> None:
    """Classify every not-yet-done snippet with Haiku, appending as we go.

    Args:
        client: Authenticated Anthropic client.
        df: Gold DataFrame with at least columns ``id`` and ``text``.
        done_ids: Set of article IDs that already have Haiku predictions and
            can be skipped.
    """
    todo = df[~df["id"].isin(done_ids)].reset_index(drop=True)
    write_header = not os.path.exists(HAIKU_PREDS_PATH)
    for i, (_, row) in enumerate(todo.iterrows()):
        print(f"[{i + 1:3d}/{len(todo)}] {row['id']}", flush=True)
        pred = classify_retry(client, row["text"], HAIKU_MODEL)
        out = {
            "id": row["id"],
            "haiku_category": pred["category"],
            "haiku_operational_domain": pred["operational_domain"],
        }
        pd.DataFrame([out]).to_csv(
            HAIKU_PREDS_PATH, mode="a", header=write_header, index=False
        )
        write_header = False
        time.sleep(SLEEP_BETWEEN_CALLS)


def run_predictions_batch(
    client: anthropic.Anthropic,
    df: pd.DataFrame,
    done_ids: set,
    poll_interval: float = 30.0,
) -> None:
    """Classify every not-yet-done snippet with Haiku via the Message Batches API.

    One batch of N requests instead of N synchronous calls, at ~50% of the
    per-token cost (see decisions/009). Results land once the whole batch ends
    (usually within an hour), so this suits an unattended run.

    Args:
        client: Authenticated Anthropic client.
        df: Gold DataFrame with at least columns ``id`` and ``text``.
        done_ids: Set of article IDs that already have Haiku predictions and
            can be skipped.
        poll_interval: Seconds to sleep between polling the batch's status.
    """
    todo = df[~df["id"].isin(done_ids)].reset_index(drop=True)
    if todo.empty:
        return

    requests = [
        build_batch_request(str(row["id"]), row["text"], model=HAIKU_MODEL)
        for _, row in todo.iterrows()
    ]
    print(f"Submitting a batch of {len(requests)} Haiku requests...", flush=True)
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
    write_header = not os.path.exists(HAIKU_PREDS_PATH)
    for result in client.messages.batches.results(batch.id):
        try:
            pred = parse_batch_result(result)
        except (BatchItemError, InvalidLabelError) as exc:
            # Skip, don't abort the whole batch -- the id stays out of the preds
            # file and is picked up as still-todo on the next run.
            print(f"  [skip] id={result.custom_id}: {exc}", flush=True)
            continue
        out = {
            "id": result.custom_id,
            "haiku_category": pred["category"],
            "haiku_operational_domain": pred["operational_domain"],
        }
        pd.DataFrame([out]).to_csv(
            HAIKU_PREDS_PATH, mode="a", header=write_header, index=False
        )
        write_header = False


def _acc(truth: pd.Series, pred: pd.Series) -> float:
    """Fraction of positions where ``truth`` and ``pred`` are equal."""
    return float((truth == pred).mean())


def _macro_f1(merged: pd.DataFrame, field: str, pred_col: str) -> float:
    """Macro-F1 for ``field`` using ``pred_col`` as the prediction column."""
    tmp = pd.DataFrame({field: merged[field], f"pred_{field}": merged[pred_col]})
    return float(macro_average(compute_metrics(tmp, field))["f1"])


def _flip_counts(merged: pd.DataFrame, field: str) -> dict:
    """Count how Haiku differs from the Sonnet baseline for one field.

    Args:
        merged: Gold frame merged with baseline (``pred_*``) and Haiku
            (``haiku_*``) predictions.
        field: ``"category"`` or ``"operational_domain"``.

    Returns:
        Dict with ``changed`` (Haiku disagreed with Sonnet), ``haiku_better``
        (Sonnet wrong -> Haiku right), ``haiku_worse`` (Sonnet right -> Haiku
        wrong -- the escalation gap), and ``lateral`` (both wrong, different).
    """
    base_right = merged[f"pred_{field}"] == merged[field]
    haiku_right = merged[f"haiku_{field}"] == merged[field]
    changed = merged[f"pred_{field}"] != merged[f"haiku_{field}"]
    better = int((changed & ~base_right & haiku_right).sum())
    worse = int((changed & base_right & ~haiku_right).sum())
    return {
        "changed": int(changed.sum()),
        "haiku_better": better,
        "haiku_worse": worse,
        "lateral": int(changed.sum()) - better - worse,
    }


def metrics(merged: pd.DataFrame) -> dict:
    """Compute Haiku vs human, the delta vs the Sonnet baseline, and flip counts.

    Args:
        merged: Gold frame merged with baseline (``pred_*``) and Haiku
            (``haiku_*``) predictions.

    Returns:
        Dict with ``n``, baseline/haiku/delta for category and domain accuracy
        and macro-F1, and ``category_flip`` / ``domain_flip`` count dicts.
    """
    out: dict = {"n": len(merged)}
    for field in ("category", "operational_domain"):
        short = "category" if field == "category" else "domain"
        base_acc = _acc(merged[field], merged[f"pred_{field}"])
        haiku_acc = _acc(merged[field], merged[f"haiku_{field}"])
        base_f1 = _macro_f1(merged, field, f"pred_{field}")
        haiku_f1 = _macro_f1(merged, field, f"haiku_{field}")
        out[f"{short}_accuracy_baseline"] = base_acc
        out[f"{short}_accuracy_haiku"] = haiku_acc
        out[f"{short}_accuracy_delta"] = haiku_acc - base_acc
        out[f"{short}_macro_f1_baseline"] = base_f1
        out[f"{short}_macro_f1_haiku"] = haiku_f1
        out[f"{short}_macro_f1_delta"] = haiku_f1 - base_f1
    out["category_flip"] = _flip_counts(merged, "category")
    out["domain_flip"] = _flip_counts(merged, "operational_domain")
    return out


def _flip_line(counts: dict, label: str) -> str:
    """One-line summary of how Haiku diverged from the Sonnet baseline."""
    return (
        f"{label}: Haiku disagreed with Sonnet on {counts['changed']} calls "
        f"-> {counts['haiku_better']} Haiku-better (Sonnet wrong->Haiku right), "
        f"{counts['haiku_worse']} Haiku-worse (Sonnet right->Haiku wrong), "
        f"{counts['lateral']} lateral"
    )


def build_report(merged: pd.DataFrame) -> str:
    """Format the Haiku-vs-Sonnet comparison against the human labels.

    Args:
        merged: Gold frame merged with baseline (``pred_*``) and Haiku
            (``haiku_*``) predictions.

    Returns:
        Multi-line report string.
    """
    m = metrics(merged)
    rows = [
        ("Category accuracy", "category_accuracy", "{:.1%}"),
        ("Category macro-F1", "category_macro_f1", "{:.3f}"),
        ("Domain accuracy", "domain_accuracy", "{:.1%}"),
        ("Domain macro-F1", "domain_macro_f1", "{:.3f}"),
    ]
    lines = [
        "=" * 62,
        "HAIKU EVAL ARM -- claude-haiku-4-5 vs the Sonnet workhorse",
        "=" * 62,
        "",
        f"Snippets : {m['n']}   ({PREDS_PATH} baseline)",
        f"Baseline (workhorse) : {WORKHORSE_MODEL}",
        f"New arm              : {HAIKU_MODEL}",
        "Both un-grounded classify(), graded against human labels.",
        "",
        f"{'':<20}{'baseline':>10}{'haiku':>10}{'delta':>10}",
    ]
    for name, key, fmt in rows:
        base = m[f"{key}_baseline"]
        haiku = m[f"{key}_haiku"]
        delta = m[f"{key}_delta"]
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"{name:<20}{fmt.format(base):>10}{fmt.format(haiku):>10}"
            f"{sign + fmt.format(delta):>10}"
        )
    lines += [
        "",
        "-- Does escalating from Haiku to Sonnet pay? --------------",
        _flip_line(m["category_flip"], "Category"),
        _flip_line(m["domain_flip"], "Domain"),
        "=" * 62,
    ]
    return "\n".join(lines)


def main() -> None:
    """Run Haiku on the gold set (resuming if possible), then score vs the baseline.

    Raises:
        EnvironmentError: If ``ANTHROPIC_API_KEY`` is not set (via make_client).
    """
    parser = argparse.ArgumentParser(
        description="Benchmark the Haiku tier against the committed Sonnet baseline."
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help=(
            "classify via the Message Batches API instead of N synchronous "
            "calls -- ~50%% cheaper, non-interactive (results land once the "
            "whole batch ends, usually within an hour)"
        ),
    )
    args = parser.parse_args()

    os.makedirs("evals", exist_ok=True)
    gold = load_gold()
    print(f"Loaded {len(gold)} labeled gold snippets\n")

    done_ids = (
        set(pd.read_csv(HAIKU_PREDS_PATH)["id"])
        if os.path.exists(HAIKU_PREDS_PATH)
        else set()
    )
    if set(gold["id"]) - done_ids:
        client = make_client()
        if args.batch:
            run_predictions_batch(client, gold, done_ids)
        else:
            run_predictions(client, gold, done_ids)
    else:
        print("All Haiku predictions already present -- skipping API calls.\n")

    base = pd.read_csv(PREDS_PATH)[["id", "pred_category", "pred_operational_domain"]]
    haiku = pd.read_csv(HAIKU_PREDS_PATH)
    merged = (
        gold.rename(columns={"domain": "operational_domain"})
        .merge(base, on="id")
        .merge(haiku, on="id")
    )

    report = build_report(merged)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report)
    print("\n" + report)


if __name__ == "__main__":
    main()
