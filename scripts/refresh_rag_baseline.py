"""Regenerate the RAG grounding baseline under the CURRENT prompt.

The RAG grounding delta (``src/gold_eval_rag.py``) compares the grounded 4.6 classifier
against a *same-model, ungrounded* baseline, ``evals/gold_rag_baseline_predictions.csv``.
For that delta to isolate grounding, both arms must share the model **and** the prompt.

The baseline is a frozen fixture (ADR-010), which silently goes stale when
``src/classify.py``'s ``SYSTEM_PROMPT`` changes: the grounded arm moves to the new prompt
while the baseline stays on the old one, so the delta then double-counts the prompt change
instead of measuring grounding. ADR-010 flagged exactly this ("becomes stale only if 4.6's
ungrounded behavior drifts") but left nothing to catch it -- this script is that catch.

It re-runs the ungrounded ``RAG_MODEL`` classifier over the gold set under the current
prompt and rewrites the baseline, so ``gold_eval_rag.py`` measures grounding cleanly again.
Run it whenever ``SYSTEM_PROMPT`` changes, then re-run ``gold_eval_rag.py``.

Writes only the columns ``gold_eval_rag.py`` and ``eval_gate.py`` read from the baseline
(``id``, ``pred_category``, ``pred_operational_domain``); the Opus-judge columns the old
fixture carried are never consumed for the grounding comparison, so they are not spent.

Run (from the repo root):
    uv run --env-file .env python scripts/refresh_rag_baseline.py

Needs ``ANTHROPIC_API_KEY``. Diagnostic/maintenance tooling: it rewrites one committed
fixture and nothing else.
"""

from __future__ import annotations

import csv
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import anthropic  # noqa: E402

import classify  # noqa: E402
from classify_rag import RAG_MODEL  # noqa: E402
from gold_eval import load_gold  # noqa: E402

BASELINE_PATH = "evals/gold_rag_baseline_predictions.csv"
FIELDS = ["id", "pred_category", "pred_operational_domain"]
MAX_RETRIES = 5


def classify_with_backoff(
    client: anthropic.Anthropic, text: str, max_retries: int = MAX_RETRIES
) -> dict:
    """Classify ``text`` ungrounded on ``RAG_MODEL``, retrying transient API errors.

    Mirrors the backoff in ``gold_eval_rag.run_grounded`` so a flaky 429/500 does not
    abort the whole refresh.

    Args:
        client: Authenticated Anthropic client.
        text: Article snippet to classify.
        max_retries: Maximum attempts before re-raising.

    Returns:
        The classifier result dict (keys ``category``, ``operational_domain``).
    """
    for attempt in range(max_retries):
        try:
            return classify.classify(client, text, model=RAG_MODEL)
        except (anthropic.InternalServerError, anthropic.RateLimitError):
            if attempt == max_retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")  # loop either returns or re-raises


def main() -> None:
    """Rewrite the RAG baseline with fresh ungrounded ``RAG_MODEL`` predictions."""
    gold = load_gold().to_dict("records")
    client = classify.make_client()
    print(f"gold: {len(gold)} snippets | model: {RAG_MODEL} (ungrounded)\n")

    rows = []
    for i, row in enumerate(gold, 1):
        print(f"[{i:>3}/{len(gold)}] {row['id']}")
        result = classify_with_backoff(client, row["text"])
        rows.append(
            {
                "id": row["id"],
                "pred_category": result["category"],
                "pred_operational_domain": result["operational_domain"],
            }
        )

    with open(BASELINE_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"\nWrote {BASELINE_PATH} ({len(rows)} rows) under the current SYSTEM_PROMPT."
    )
    print(
        "Next: re-run `uv run --env-file .env python src/gold_eval_rag.py` to rescore."
    )


if __name__ == "__main__":
    main()
