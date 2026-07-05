"""Retrieval-grounded classification (v2 Step 3).

For a target article, retrieve the top-k most similar real corpus docs with BM25 and pass
them into the classify call as labeled reference excerpts, then return the
{category, operational_domain} plus the citations that grounded it. Whether this grounding
beats the un-grounded baseline (src/gold_eval.py) is the open question Step 3 *measures* --
lexical neighbors might help, do nothing, or mislead.

Only the user prompt changes: the system prompt, tool schema, label validation, and retry
all come from ``classify.classify()``, so baseline vs grounded differ by exactly the
retrieved context. The gold set is disjoint from the corpus, so grounding a gold snippet
never retrieves the snippet itself.
"""

from __future__ import annotations

import anthropic

from classify import MODEL, classify
from retrieve import Hit, Retriever

GROUNDING_INSTRUCTION = (
    "Below are excerpts from related real defense-news articles, retrieved for reference. "
    "Each is tagged with how a similar article was categorized. They may or may not share "
    "the target article's labels -- use them as calibration, not as the answer."
)


def _format_context(hits: list[Hit], snippet_chars: int = 240) -> str:
    """Render retrieved docs as numbered, label-tagged reference lines."""
    lines = []
    for i, hit in enumerate(hits, start=1):
        snippet = " ".join(hit.doc.text.split())[:snippet_chars]
        lines.append(
            f"{i}. [category={hit.doc.category}, domain={hit.doc.domain}] "
            f"{hit.doc.title}: {snippet}"
        )
    return "\n".join(lines)


def classify_grounded(
    client: anthropic.Anthropic,
    text: str,
    retriever: Retriever,
    k: int = 3,
    model: str = MODEL,
) -> dict:
    """Classify ``text`` grounded in the top-k retrieved corpus docs; attach their citations.

    Reuses ``classify.classify()`` verbatim, passing a prompt that prepends the retrieved
    reference excerpts to the target article, so baseline vs. grounded differ by exactly
    the retrieved context.

    Args:
        client: Authenticated Anthropic client.
        text: Article snippet to classify.
        retriever: Retriever used to fetch the top-k grounding docs.
        k: Number of retrieved docs to include as context.
        model: Which Claude model classifies.

    Returns:
        Dict with keys ``category``, ``operational_domain``, and ``citations``
        (a list of ``{id, source_url, score}`` for each retrieved doc).
    """
    hits = retriever.retrieve(text, k=k)
    prompt = (
        f"{GROUNDING_INSTRUCTION}\n\n{_format_context(hits)}\n\n"
        f"Now classify THIS article:\n{text}"
    )
    result = dict(classify(client, prompt, model=model))
    result["citations"] = [
        {
            "id": hit.doc.id,
            "source_url": hit.doc.source_url,
            "score": round(hit.score, 2),
        }
        for hit in hits
    ]
    return result
