"""Tests for src/classify_rag.py (retrieval-grounded classification).

Offline: the LLM call is mocked via the tool_client fixture, and a tiny in-memory
Retriever stands in for the corpus.
"""

import classify
import classify_rag
from retrieve import Doc, Hit, Retriever


def _docs():
    return [
        Doc(
            "001-a",
            "Carrier ops",
            "naval carrier strike group operating at sea",
            "operations",
            "sea",
            "dvids",
            "http://example/1",
            "2024-01-01",
        ),
        Doc(
            "002-b",
            "Drone contract",
            "army awards a drone production contract",
            "procurement",
            "land",
            "dvids",
            "http://example/2",
            "2024-01-02",
        ),
    ]


def test_search_result_blocks_carry_source_title_and_label_tags():
    blocks = classify_rag._search_result_blocks([Hit(doc=_docs()[0], score=1.0)])

    assert len(blocks) == 1
    block = blocks[0]
    assert block["type"] == "search_result"
    # Source URL + title become the API's citation attribution.
    assert block["source"] == "http://example/1"
    assert block["title"] == "Carrier ops"
    # The label calibration tag rides along inside the block's text content.
    text = block["content"][0]["text"]
    assert "category=operations" in text
    assert "domain=sea" in text
    # Citations are enabled so the API can attribute cited passages.
    assert block["citations"] == {"enabled": True}


def test_search_result_blocks_fall_back_to_id_when_source_missing():
    doc = Doc(
        "003-c",
        "",  # no title
        "an air defense radar system fielded",
        "technology",
        "air",
        "dvids",
        "",  # no source_url
        "2024-01-03",
    )
    block = classify_rag._search_result_blocks([Hit(doc=doc, score=1.0)])[0]
    # `source` must never be empty (the API requires it); fall back to the doc id.
    assert block["source"] == "003-c"
    assert block["title"] == "003-c"


def test_classify_grounded_returns_labels_and_citations(tool_client):
    client = tool_client(
        {"category": "operations", "operational_domain": "sea", "region": "global"}
    )
    retriever = Retriever(_docs())

    result = classify_rag.classify_grounded(
        client, "a carrier strike group deployed to sea", retriever, k=2
    )

    assert result["category"] == "operations"
    assert result["operational_domain"] == "sea"
    # Both corpus docs are cited (k=2 over a 2-doc corpus), with their metadata.
    assert {c["id"] for c in result["citations"]} == {"001-a", "002-b"}
    assert all("source_url" in c and "score" in c for c in result["citations"])


def test_grounded_context_reaches_the_model_as_search_result_blocks(tool_client):
    """The retrieved excerpts must reach the API as search_result blocks, not plain text."""
    client = tool_client(
        {"category": "procurement", "operational_domain": "land", "region": "global"}
    )
    retriever = Retriever(_docs())

    classify_rag.classify_grounded(client, "drone production contract", retriever, k=2)

    content = client.messages.last_kwargs["messages"][0]["content"]
    # The user content is now a structured block list: instruction, k search_result
    # blocks, then the target article.
    assert isinstance(content, list)
    search_blocks = [b for b in content if b["type"] == "search_result"]
    assert len(search_blocks) == 2
    text_blocks = [b for b in content if b["type"] == "text"]
    assert any("retrieved for reference" in b["text"] for b in text_blocks)
    assert any("Now classify THIS article:" in b["text"] for b in text_blocks)


def test_rag_path_is_pinned_to_its_own_model_not_the_workhorse(tool_client):
    """The RAG path defaults to RAG_MODEL (4.6), decoupled from the workhorse.

    ``classify.MODEL`` is now claude-sonnet-5; the grounded path must stay on 4.6.
    Locks in ADR-010's transitional split: BM25 grounding regresses the domain field
    once the ungrounded Sonnet-5 baseline is already strong, so the grounded path stays
    on 4.6. If a future workhorse bump silently re-coupled these (e.g. by reintroducing
    ``from classify import MODEL``), this test fails instead of the RAG delta gate.
    """
    client = tool_client(
        {"category": "operations", "operational_domain": "sea", "region": "global"}
    )
    retriever = Retriever(_docs())

    classify_rag.classify_grounded(client, "a carrier strike group at sea", retriever)

    assert classify_rag.RAG_MODEL == "claude-sonnet-4-6"
    assert classify_rag.RAG_MODEL != classify.MODEL
    assert client.messages.last_kwargs["model"] == "claude-sonnet-4-6"
