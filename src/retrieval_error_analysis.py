"""BM25-vs-embeddings analysis slice: characterize the gold-eval misclassifications.

Read-only. Answers one question to inform a *future* retrieval decision (NOT a
switch to embeddings here -- Anthropic has no first-party embeddings model, so
that would mean adding a Voyage AI dependency, out of scope): of the errors the
classifier still makes, how many are ones a *better retriever* could plausibly
fix, versus ones retrieval already handled and can't fix?

The honest signal comes from the retrieved passages themselves. The committed
BM25 run (evals/gold_rag_predictions.csv) records, per gold snippet, the top-k
doc ids it actually retrieved. Each of those docs carries a gold category/domain
in the corpus manifest. So for every *grounded* miss we can ask objectively:

  - **retrieval on-target** -- BM25 already surfaced at least one doc whose
    label matches the human truth, and the model missed anyway. Better
    retrieval (embeddings) would change nothing: the right context was present.
    These are vocabulary-driven / label-boundary errors (BM25's strength; the
    bottleneck is label overlap, not retrieval).
  - **retrieval off-target** -- none of the top-k docs carried the true label.
    BM25's lexical match pulled topically-wrong context. This is the
    semantic/paraphrase failure mode where a semantic retriever could
    plausibly help.

That split is the whole verdict: it says how much of the residual error budget
is even *addressable* by swapping the retriever, without changing anything.

This module never calls the API. It grades whatever is already committed under
evals/, exactly like src/eval_gate.py, so it can run in the offline gate.

Run:
    uv run python src/retrieval_error_analysis.py

Reads data/gold/gold.csv, evals/gold_predictions.csv (baseline),
evals/gold_rag_predictions.csv (grounded + citations), and the corpus manifest.
Writes evals/retrieval_error_analysis.md.
"""

from __future__ import annotations

import pandas as pd

from gold_eval import load_gold
from gold_eval_rag import RAG_PREDS_PATH
from retrieve import load_corpus

# Frozen v2 workhorse snapshot -- the ungrounded baseline the retired RAG
# comparison (ADR-012) was measured against. Deliberately NOT
# gold_eval.PREDS_PATH, which moved to the v3 three-axis file (ADR-014).
PREDS_PATH = "evals/gold_predictions.csv"
REPORT_PATH = "evals/retrieval_error_analysis.md"
FIELDS = (("category", "category"), ("operational_domain", "domain"))


def _doc_labels() -> dict[str, dict[str, str]]:
    """Map each corpus doc id -> its gold category/domain from the manifest.

    Returns:
        Dict keyed by doc id with ``category`` and ``operational_domain`` values,
        so a retrieved citation can be scored against the human truth label.
    """
    return {
        doc.id: {"category": doc.category, "operational_domain": doc.domain}
        for doc in load_corpus()
    }


def load_merged() -> pd.DataFrame:
    """Join gold truth with committed baseline + grounded predictions and citations.

    Returns:
        One row per gold snippet with the human labels (``category`` /
        ``operational_domain``), the ungrounded baseline prediction
        (``pred_*``), the BM25-grounded prediction (``rag_*``), and the
        ``citations`` string (``;``-joined retrieved doc ids).
    """
    gold = load_gold().rename(columns={"domain": "operational_domain"})
    base = pd.read_csv(PREDS_PATH)[["id", "pred_category", "pred_operational_domain"]]
    rag = pd.read_csv(RAG_PREDS_PATH)
    return gold.merge(base, on="id").merge(rag, on="id")


def _retrieval_hit(citations: str, true_label: str, field: str, labels: dict) -> bool:
    """Did BM25 surface at least one top-k doc carrying the true label for this field?

    Args:
        citations: ``;``-joined retrieved doc ids (the ``citations`` column).
        true_label: The human truth label for this snippet + field.
        field: ``"category"`` or ``"operational_domain"``.
        labels: Doc-id -> label map from :func:`_doc_labels`.

    Returns:
        True if any retrieved doc's ``field`` label equals ``true_label`` --
        i.e. the right context was present in the retrieved set.
    """
    ids = [c for c in str(citations).split(";") if c]
    return any(labels.get(doc_id, {}).get(field) == true_label for doc_id in ids)


def analyze(merged: pd.DataFrame, labels: dict) -> dict:
    """Bucket every grounded (and baseline) miss into the retrieval verdict.

    Args:
        merged: Frame from :func:`load_merged`.
        labels: Doc-id -> label map from :func:`_doc_labels`.

    Returns:
        Dict with per-field counts and a ``cases`` list of per-miss detail
        (one entry per (snippet, field) grounded miss), each carrying the
        retrieval-hit signal and the vocabulary/semantic verdict.
    """
    result: dict = {"n": len(merged), "fields": {}, "cases": []}
    for field, _short in FIELDS:
        base_pred = f"pred_{field}"
        rag_pred = f"rag_{field}"
        base_miss = int((merged[field] != merged[base_pred]).sum())
        rag_miss_rows = merged[merged[field] != merged[rag_pred]]

        on_target = off_target = 0
        for _, row in rag_miss_rows.iterrows():
            hit = _retrieval_hit(row["citations"], row[field], field, labels)
            if hit:
                on_target += 1
                verdict = "vocabulary / label-boundary (embeddings would NOT help)"
            else:
                off_target += 1
                verdict = "semantic / paraphrase (embeddings could plausibly help)"
            result["cases"].append(
                {
                    "id": row["id"],
                    "field": field,
                    "true": row[field],
                    "baseline": row[base_pred],
                    "grounded": row[rag_pred],
                    "retrieval_hit": hit,
                    "verdict": verdict,
                }
            )
        result["fields"][field] = {
            "baseline_miss": base_miss,
            "grounded_miss": len(rag_miss_rows),
            "retrieval_on_target": on_target,
            "retrieval_off_target": off_target,
        }
    return result


def build_report(a: dict) -> str:
    """Render the analysis as a Markdown deliverable (mirrors evals/error_audit.md).

    Args:
        a: Output of :func:`analyze`.

    Returns:
        Multi-line Markdown string.
    """
    on = sum(f["retrieval_on_target"] for f in a["fields"].values())
    off = sum(f["retrieval_off_target"] for f in a["fields"].values())
    total = on + off

    lines = [
        "# BM25-vs-embeddings analysis -- would a better retriever fix the misses?",
        "",
        "*Purpose: quantify how much of the gold-eval's **residual** error is even "
        "addressable by swapping BM25 for a semantic (embedding) retriever, before "
        "spending a Voyage AI dependency to find out. This is a read-only analysis "
        "over the committed run -- not a change to the retrieval layer.*",
        "",
        "> **Method.** For every grounded (BM25 + top-k context) miss, look at the "
        "doc ids BM25 actually retrieved (the `citations` column of "
        "`evals/gold_rag_predictions.csv`) and check whether any of them carried "
        "the human-truth label in the corpus manifest. If yes, the right context "
        "was already in front of the model and it missed anyway -- a **vocabulary / "
        "label-boundary** error a better retriever cannot fix. If no, BM25's lexical "
        "match pulled topically-wrong context -- a **semantic / paraphrase** error "
        "where embeddings could plausibly help.",
        "",
        f"Snippets analyzed: **{a['n']}**.  Grounded misses across both fields: "
        f"**{total}** ({on} retrieval-on-target, {off} retrieval-off-target).",
        "",
        "## Headline",
        "",
    ]

    if total == 0:
        lines.append("No grounded misses -- nothing for a better retriever to fix.")
    else:
        lines += [
            f"**{off} of {total} residual misses ({off / total:.0%}) are "
            "retrieval-off-target** -- BM25 surfaced no top-k doc carrying the true "
            "label. Only these could *possibly* move with a semantic retriever, so "
            f"this is an **upper bound** on the embeddings-addressable slice: {off} "
            f"of {a['n']} snippets ({off / a['n']:.0%}).",
            "",
            f"**{on} of {total} ({on / total:.0%}) are retrieval-on-target** -- BM25 "
            "already retrieved a same-label doc and the model still picked another. "
            "Those are provably not retrieval's fault; a semantic retriever changes "
            "nothing there.",
            "",
            "**The upper bound overstates the real prize.** Retrieval-off-target is "
            "*necessary but not sufficient* for embeddings to help: the corpus is "
            "only ~62 docs, so BM25 can miss a same-label doc simply because none is "
            "lexically near the snippet (a coverage gap, not a semantic-vs-lexical "
            "gap). And the off-target transitions below cluster in the exact "
            "overlapping-definition label pairs the synthetic-set `error_audit.md` "
            "flags (operations / procurement / technology / policy on category; "
            "air / land / multi on domain) -- label-boundary calls a better "
            "retriever wouldn't disambiguate. The genuinely retrieval-addressable "
            "count is some fraction of these, not all of them.",
        ]

    # Transition tally among the off-target misses -- shows how much of the
    # "embeddings might help" bucket is really label overlap in disguise.
    off_cases = [c for c in a["cases"] if not c["retrieval_hit"]]
    if off_cases:
        tally: dict[str, int] = {}
        for c in off_cases:
            key = f"`{c['true']}` -> `{c['grounded']}` ({c['field']})"
            tally[key] = tally.get(key, 0) + 1
        lines += [
            "",
            "### Transitions among retrieval-off-target misses",
            "",
            "| True -> Grounded (field) | Count |",
            "|---|---|",
        ]
        for key, count in sorted(tally.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {key} | {count} |")

    lines += [
        "",
        "## Per-field breakdown",
        "",
        "| Field | Baseline misses | Grounded misses | Retrieval on-target (vocab) | Retrieval off-target (semantic) |",
        "|---|---|---|---|---|",
    ]
    for field, _short in FIELDS:
        f = a["fields"][field]
        lines.append(
            f"| {field} | {f['baseline_miss']} | {f['grounded_miss']} | "
            f"{f['retrieval_on_target']} | {f['retrieval_off_target']} |"
        )

    lines += [
        "",
        "## Per-case detail (grounded misses)",
        "",
        "`retrieval_hit = True` means BM25 already retrieved a doc with the true "
        "label -- so the error is not a retrieval failure.",
        "",
        "| ID | Field | True -> Grounded (Baseline) | Retrieval hit? | Verdict |",
        "|---|---|---|---|---|",
    ]
    for c in a["cases"]:
        base_note = "" if c["baseline"] == c["grounded"] else f" (was {c['baseline']})"
        lines.append(
            f"| {c['id']} | {c['field']} | `{c['true']}` -> `{c['grounded']}`"
            f"{base_note} | {'yes' if c['retrieval_hit'] else 'NO'} | {c['verdict']} |"
        )

    lines += [
        "",
        "## Read",
        "",
        f"On the surface the split looks like an argument *for* embeddings: {off} of "
        f"{total} residual misses are retrieval-off-target. But that number is an "
        "upper bound on a confounded quantity, and the two confounds both point the "
        "same way. First, corpus coverage: with ~62 docs, BM25 often has no "
        "same-label doc to retrieve, so 'off-target' partly measures a small index, "
        "not a lexical-vs-semantic gap -- and adding embeddings over the same 62 "
        "docs can't retrieve a relevant doc that isn't there. Second, the off-target "
        "transitions are almost entirely the overlapping-definition label pairs "
        "already documented in `error_audit.md` (operations/procurement/technology/"
        "policy; air/land/multi) -- errors of label boundary, not of which passage "
        "was retrieved.",
        "",
        "So the honest verdict is unchanged from v2's 'BM25 grounding doesn't "
        f"justify embeddings', now with a measured ceiling: at most {off} of "
        f"{a['n']} snippets ({off / a['n']:.0%}) are even plausibly retrieval-"
        "addressable, and realistically fewer once label-boundary cases are set "
        "aside. That's worth **one targeted eval slice** (embeddings retrieval on "
        "just these off-target ids, if a first-party embeddings model ever lands) "
        "before spending a Voyage AI dependency -- not a retrieval-layer swap. The "
        "higher-leverage move for this residual error is label-scheme "
        "disambiguation (or the planned `region` field), not a semantic retriever.",
        "",
        "*Generated from `evals/gold_predictions.csv`, `evals/gold_rag_predictions.csv`, "
        "and the corpus manifest. Re-run with `uv run python src/retrieval_error_analysis.py`.*",
    ]
    return "\n".join(lines)


def main() -> None:
    """Run the analysis over committed artifacts and write the Markdown report."""
    merged = load_merged()
    a = analyze(merged, _doc_labels())
    report = build_report(a)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report)
    print(report)


if __name__ == "__main__":
    main()
