"""Re-measure ADR-010's Sonnet-5 grounding regression under the extended-rubric prompt.

ADR-010 pinned the RAG path to claude-sonnet-4-6 after grounding regressed Sonnet 5's
domain accuracy by -9.3 points (94.4% ungrounded -> 85.2% grounded, reproduced 3x) --
measured with the PRE-rubric prompt. The extended rubric (PR #73) changed both arms,
and on the 4.6 pin it flipped grounding from break-even to clearly positive, so the
pin's premise is due for a re-run rather than an assumption in either direction.

This mirrors the original experiment's shape: N independent grounded passes over the
gold set on claude-sonnet-5, each compared field-by-field against the same-model
ungrounded baseline (the freshly committed evals/gold_predictions.csv, which IS the
current Sonnet-5 snapshot), with per-pass accuracies and wrong->right / right->wrong
flip counts. Diagnostic only: writes evals/runs/adr010_remeasure.txt, touches no
gated snapshot file and no gate floor.

Run (from the repo root):
    uv run python scripts/adr010_remeasure.py            # 3 passes (the original's standard)
    uv run python scripts/adr010_remeasure.py --passes 1
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import classify  # noqa: E402
from classify_rag import classify_grounded  # noqa: E402
from gold_eval import load_gold  # noqa: E402
from retrieve import Retriever, load_corpus  # noqa: E402

MODEL = "claude-sonnet-5"
BASELINE_PATH = "evals/gold_predictions.csv"
REPORT_PATH = "evals/runs/adr010_remeasure.txt"


def load_baseline() -> dict[str, dict]:
    """Load the committed Sonnet-5 ungrounded predictions, keyed by gold id."""
    with open(BASELINE_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {r["id"]: r for r in rows}


def main() -> None:
    """Run N grounded Sonnet-5 passes and report accuracy + flips vs the baseline."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--passes", type=int, default=3)
    args = parser.parse_args()

    gold = load_gold().to_dict("records")
    baseline = load_baseline()
    retriever = Retriever(load_corpus())
    client = classify.make_client()
    n = len(gold)
    print(f"gold: {n} snippets | model: {MODEL} | passes: {args.passes}\n")

    lines = [
        f"ADR-010 re-measurement: grounded {MODEL} under the extended-rubric prompt",
        f"baseline: {BASELINE_PATH} (same-model ungrounded snapshot)",
        "",
    ]
    for p in range(1, args.passes + 1):
        cat_ok = dom_ok = 0
        cat_fix = cat_break = dom_fix = dom_break = 0
        for i, row in enumerate(gold, 1):
            pred = classify_grounded(client, row["text"], retriever, model=MODEL)
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
            f"pass {p}: category {cat_ok / n:.1%} (fix {cat_fix}/break {cat_break})   "
            f"domain {dom_ok / n:.1%} (fix {dom_fix}/break {dom_break})"
        )
        print("\n" + line)
        lines.append(line)

    base_cat = (
        sum(baseline[r["id"]]["pred_category"] == r["category"] for r in gold) / n
    )
    base_dom = (
        sum(baseline[r["id"]]["pred_operational_domain"] == r["domain"] for r in gold)
        / n
    )
    lines.append("")
    lines.append(
        f"ungrounded baseline: category {base_cat:.1%}   domain {base_dom:.1%}"
    )
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\nwrote", REPORT_PATH)


if __name__ == "__main__":
    main()
