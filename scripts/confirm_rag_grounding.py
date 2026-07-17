"""Confirm (or refute) the RAG grounding regression with N independent passes.

The one-shot RAG re-measure under the #79 prompt showed grounding gone neutral-to-harmful
on the 4.6 pin: category delta ~+0.0, domain delta -3.7 (breaching the -0.03 gate floor).
But that domain regression is only 2 snippets on n=54, so it could be run-to-run noise --
ADR-010 ran its regression 3x before trusting it. This mirrors that: N independent grounded
passes over the gold set on RAG_MODEL, each scored against the SAME refreshed ungrounded
baseline, reporting per-pass accuracy and wrong->right / right->wrong flip counts.

Diagnostic only: writes evals/runs/confirm_rag_grounding.txt (gitignored run-log territory),
touches no gated snapshot and no floor. Uses the same k and baseline file as the gate, so its
numbers are comparable to gold_eval_rag.py's.

IMPORTANT -- ordering: the baseline it reads (``RAG_BASELINE_PREDS_PATH``) must already be
refreshed under the CURRENT prompt, or the comparison conflates the prompt with grounding.
Run ``scripts/refresh_rag_baseline.py`` first, then this.

Run (from the repo root):
    uv run --env-file .env python scripts/confirm_rag_grounding.py            # 3 passes
    uv run --env-file .env python scripts/confirm_rag_grounding.py --passes 5

Needs ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import anthropic  # noqa: E402

import classify  # noqa: E402
from classify_rag import RAG_MODEL, classify_grounded  # noqa: E402
from gold_eval import load_gold  # noqa: E402
from gold_eval_rag import RAG_BASELINE_PREDS_PATH, RETRIEVE_K  # noqa: E402
from retrieve import Retriever, load_corpus  # noqa: E402

REPORT_PATH = "evals/runs/confirm_rag_grounding.txt"
MAX_RETRIES = 5


def load_baseline() -> dict[str, dict]:
    """Load the refreshed ungrounded RAG baseline, keyed by gold id."""
    with open(RAG_BASELINE_PREDS_PATH, encoding="utf-8") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def grounded_with_backoff(
    client: anthropic.Anthropic, text: str, retriever: Retriever
) -> dict:
    """classify_grounded() at the gate's k, retrying transient API errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return classify_grounded(client, text, retriever, k=RETRIEVE_K)
        except (anthropic.InternalServerError, anthropic.RateLimitError):
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")  # loop either returns or re-raises


def main() -> None:
    """Run N grounded passes and report accuracy + flips vs the refreshed baseline."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--passes", type=int, default=3)
    args = parser.parse_args()

    gold = load_gold().to_dict("records")
    baseline = load_baseline()
    retriever = Retriever(load_corpus())
    client = classify.make_client()
    n = len(gold)
    print(
        f"gold: {n} snippets | model: {RAG_MODEL} | k={RETRIEVE_K} | passes: {args.passes}\n"
    )

    base_cat = (
        sum(baseline[r["id"]]["pred_category"] == r["category"] for r in gold) / n
    )
    base_dom = (
        sum(baseline[r["id"]]["pred_operational_domain"] == r["domain"] for r in gold)
        / n
    )

    lines = [
        f"Confirm RAG grounding: {args.passes} grounded {RAG_MODEL} passes (k={RETRIEVE_K})",
        f"baseline: {RAG_BASELINE_PREDS_PATH} (refreshed, same-model ungrounded)",
        f"ungrounded baseline: category {base_cat:.1%}   domain {base_dom:.1%}",
        "",
    ]
    for p in range(1, args.passes + 1):
        cat_ok = dom_ok = 0
        cat_fix = cat_break = dom_fix = dom_break = 0
        for i, row in enumerate(gold, 1):
            pred = grounded_with_backoff(client, row["text"], retriever)
            print(f"[pass {p}] [{i:3d}/{n}] {row['id']}", end="\r")
            base = baseline[row["id"]]
            for field, gold_key, base_key in (
                ("category", "category", "pred_category"),
                ("operational_domain", "domain", "pred_operational_domain"),
            ):
                truth = row[gold_key]
                grounded_right = pred[field] == truth
                baseline_right = base[base_key] == truth
                if field == "category":
                    cat_ok += grounded_right
                    cat_fix += (not baseline_right) and grounded_right
                    cat_break += baseline_right and not grounded_right
                else:
                    dom_ok += grounded_right
                    dom_fix += (not baseline_right) and grounded_right
                    dom_break += baseline_right and not grounded_right
        line = (
            f"pass {p}: category {cat_ok / n:.1%} (delta {cat_ok / n - base_cat:+.1%}, "
            f"fix {cat_fix}/break {cat_break})   "
            f"domain {dom_ok / n:.1%} (delta {dom_ok / n - base_dom:+.1%}, "
            f"fix {dom_fix}/break {dom_break})"
        )
        print("\n" + line)
        lines.append(line)

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\nwrote", REPORT_PATH)


if __name__ == "__main__":
    main()
