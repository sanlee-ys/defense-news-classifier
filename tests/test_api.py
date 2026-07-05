"""Tests for src/api.py — the FastAPI wrapper around classify().

Uses FastAPI's TestClient. The Anthropic client and the classify() call are
both mocked, so no network or API key is needed. The TestClient context
manager runs the lifespan handler, which is where make_client() is called —
hence the patch on api.make_client in the fixture.
"""

import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture
def client(monkeypatch):
    # Lifespan builds the Anthropic client at startup; stub it out.
    monkeypatch.setattr(api, "make_client", lambda: object())
    with TestClient(api.app) as c:
        yield c


def test_health_does_not_touch_the_llm(client, monkeypatch):
    # If /health called classify, this would blow up.
    monkeypatch.setattr(
        api, "classify", lambda *_a, **_k: pytest.fail("health hit the LLM")
    )
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_classify_happy_path(client, monkeypatch):
    seen = {}

    def fake_classify(_client, text):
        seen["text"] = text
        return {"category": "operations", "operational_domain": "sea"}

    monkeypatch.setattr(api, "classify", fake_classify)
    resp = client.post("/classify", json={"text": "  Carrier strike group deploys.  "})

    assert resp.status_code == 200
    assert resp.json() == {"category": "operations", "operational_domain": "sea"}
    # The endpoint strips whitespace before calling the classifier.
    assert seen["text"] == "Carrier strike group deploys."


def test_classify_rejects_empty_text(client):
    # Empty string fails pydantic's min_length=1 before the handler runs.
    resp = client.post("/classify", json={"text": ""})
    assert resp.status_code == 422


def test_classify_rejects_whitespace_only(client, monkeypatch):
    # A space passes min_length but is blank after strip() — handler returns 422.
    monkeypatch.setattr(
        api, "classify", lambda *_a, **_k: pytest.fail("blank text reached the LLM")
    )
    resp = client.post("/classify", json={"text": "   "})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "text must not be blank."


def test_classify_rejects_overlong_text(client):
    resp = client.post("/classify", json={"text": "x" * 10_001})
    assert resp.status_code == 422


def test_classify_maps_upstream_failure_to_502(client, monkeypatch):
    def boom(_client, _text):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(api, "classify", boom)
    resp = client.post("/classify", json={"text": "Some defense news."})
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "Classification failed" in detail
    # The raw upstream exception text must not leak to the caller (only logged
    # server-side); the response stays generic.
    assert "rate limited" not in detail
