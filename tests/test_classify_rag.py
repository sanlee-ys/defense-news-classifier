"""Tests for src/classify_rag.py (retrieval-grounded classification).

Offline: the LLM call is mocked via the tool_client fixture, and a tiny in-memory
Retriever stands in for the corpus.
"""

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


def test_format_context_tags_each_doc_with_its_labels():
    ctx = classify_rag._format_context([Hit(doc=_docs()[0], score=1.0)])
    assert "category=operations" in ctx
    assert "domain=sea" in ctx
    assert "Carrier ops" in ctx


def test_classify_grounded_returns_labels_and_citations(tool_client):
    client = tool_client({"category": "operations", "operational_domain": "sea"})
    retriever = Retriever(_docs())

    result = classify_rag.classify_grounded(
        client, "a carrier strike group deployed to sea", retriever, k=2
    )

    assert result["category"] == "operations"
    assert result["operational_domain"] == "sea"
    # Both corpus docs are cited (k=2 over a 2-doc corpus), with their metadata.
    assert {c["id"] for c in result["citations"]} == {"001-a", "002-b"}
    assert all("source_url" in c and "score" in c for c in result["citations"])


def test_grounded_context_reaches_the_model(tool_client):
    """The retrieved excerpts must actually be sent to the API, not just computed."""
    client = tool_client({"category": "procurement", "operational_domain": "land"})
    retriever = Retriever(_docs())

    classify_rag.classify_grounded(client, "drone production contract", retriever, k=2)

    sent = client.messages.last_kwargs["messages"][0]["content"]
    assert "retrieved for reference" in sent
    assert "Now classify THIS article:" in sent
