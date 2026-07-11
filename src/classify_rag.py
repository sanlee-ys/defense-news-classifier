"""Retrieval-grounded classification (v2 Step 3).

For a target article, retrieve the top-k most similar real corpus docs with BM25 and pass
them into the classify call as labeled reference excerpts, then return the
{category, operational_domain} plus the citations that grounded it. Whether this grounding
beats the un-grounded baseline (src/gold_eval.py) is the open question Step 3 *measures* --
lexical neighbors might help, do nothing, or mislead.

Only the user-message content changes: the system prompt, tool schema, label validation,
and retry all come from ``classify.classify()``, so baseline vs grounded differ by exactly
the retrieved context. The gold set is disjoint from the corpus, so grounding a gold snippet
never retrieves the snippet itself.

Retrieved passages are presented to the model as the API's first-class ``search_result``
content blocks (rather than hand-formatted plain text), so each passage carries its own
source + title and the API attaches proper citation attribution -- the same citation
quality Claude's web search produces, with no embeddings dependency and no change to the
BM25 retrieval itself. The BM25 relevance-score citations we return in ``result["citations"]``
are our own retrieval metadata and are unaffected by that API feature.
"""

from __future__ import annotations

import anthropic
from anthropic.types import SearchResultBlockParam, TextBlockParam

from classify import MODEL, classify
from retrieve import Hit, Retriever

GROUNDING_INSTRUCTION = (
    "Below are excerpts from related real defense-news articles, retrieved for reference. "
    "Each is tagged with how a similar article was categorized. They may or may not share "
    "the target article's labels -- use them as calibration, not as the answer."
)


def _search_result_blocks(
    hits: list[Hit], snippet_chars: int = 240
) -> list[SearchResultBlockParam]:
    """Render retrieved docs as ``search_result`` blocks with source/title attribution.

    Each hit becomes one ``search_result`` block: the corpus doc's URL is the
    ``source`` and its title the ``title`` (so the API can cite it), while the
    label calibration tag -- how this similar article was categorized -- is kept
    as a prefix inside the block's text content, since that signal is the whole
    point of the grounding. ``source``/``title`` fall back to the doc id when a
    corpus row is missing a URL or title, so ``source`` is never empty (the API
    requires it) and every block stays traceable.

    Citations are enabled on every block (all-or-nothing per the API: a request
    may not mix citation-enabled and citation-disabled search results). The
    classify call forces the ``classify_article`` tool, so the response is a
    tool_use block and no cited text is surfaced -- enabling citations here is
    the semantically correct RAG presentation and future-proofs any non-forced
    use, not a change to the returned labels.

    Args:
        hits: Retrieved corpus documents, in rank order.
        snippet_chars: Max characters of each doc's (whitespace-flattened) text
            to include in its block.

    Returns:
        One ``search_result`` block per hit, in the same order.
    """
    blocks: list[SearchResultBlockParam] = []
    for hit in hits:
        snippet = " ".join(hit.doc.text.split())[:snippet_chars]
        text = f"[category={hit.doc.category}, domain={hit.doc.domain}] {snippet}"
        blocks.append(
            SearchResultBlockParam(
                type="search_result",
                source=hit.doc.source_url or hit.doc.id,
                title=hit.doc.title or hit.doc.id,
                content=[TextBlockParam(type="text", text=text)],
                citations={"enabled": True},
            )
        )
    return blocks


def classify_grounded(
    client: anthropic.Anthropic,
    text: str,
    retriever: Retriever,
    k: int = 3,
    model: str = MODEL,
) -> dict:
    """Classify ``text`` grounded in the top-k retrieved corpus docs; attach their citations.

    Reuses ``classify.classify()`` verbatim, passing a user-message content list that
    brackets the retrieved passages (as ``search_result`` blocks) between an instruction
    block and the target article, so baseline vs. grounded differ by exactly the retrieved
    context.

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
    content: list[TextBlockParam | SearchResultBlockParam] = [
        TextBlockParam(type="text", text=GROUNDING_INSTRUCTION),
        *_search_result_blocks(hits),
        TextBlockParam(type="text", text=f"Now classify THIS article:\n{text}"),
    ]
    result = dict(classify(client, content, model=model))
    result["citations"] = [
        {
            "id": hit.doc.id,
            "source_url": hit.doc.source_url,
            "score": round(hit.score, 2),
        }
        for hit in hits
    ]
    return result
