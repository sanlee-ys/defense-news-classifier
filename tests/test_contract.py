"""
Contract test: pins the /classify wire contract so any drift fails CI.

This enforces the SYS-004 contract shared with kb-agent — kb-agent's
``classify_snippet`` tool POSTs to this service's ``/classify`` endpoint and
relies on the response shape and the label enums staying fixed. Changing the
categories/domains or adding a field (e.g. the planned v3.0.0 ``region``) is a
breaking change to that integration, so it must be a deliberate, versioned
move rather than an accidental edit. These assertions are the tripwire.

Follows the offline mocking pattern from tests/test_api.py: the Anthropic SDK
is faked and ``classify()`` is monkeypatched, so no real API calls or keys are
needed.
"""

import pytest
from fastapi.testclient import TestClient

import api
import classify as classify_mod
from api import ClassifyResponse

# The frozen contract. Spelled out as literals (not imported from the module)
# so this test fails if the source lists are edited — the whole point is to
# detect drift, which means the expected values must live here independently.
FROZEN_CATEGORIES = ["procurement", "operations", "policy", "technology", "industry"]
FROZEN_DOMAINS = ["air", "land", "sea", "cyber", "space", "multi"]
FROZEN_RESPONSE_FIELDS = {"category", "operational_domain"}


def test_categories_enum_is_frozen():
    # Exact equality (order included) guards against additions, removals, or
    # renames of the category labels.
    assert classify_mod.CATEGORIES == FROZEN_CATEGORIES


def test_domains_enum_is_frozen():
    assert classify_mod.DOMAINS == FROZEN_DOMAINS


def test_response_model_has_exactly_the_contract_fields():
    # Fails the moment someone adds a field like the planned v3.0.0 `region`
    # without a deliberate, versioned change to the output contract.
    assert set(ClassifyResponse.model_fields.keys()) == FROZEN_RESPONSE_FIELDS


@pytest.fixture
def client(monkeypatch):
    # Lifespan builds the Anthropic client at startup; stub it out so no key is
    # needed (same approach as tests/test_api.py).
    monkeypatch.setattr(api, "make_client", lambda: object())
    with TestClient(api.app) as c:
        yield c


def test_classify_response_body_matches_contract(client, monkeypatch):
    # classify() is mocked to return a valid dict; we assert the wire body has
    # exactly the two contract fields, both within the frozen enums.
    monkeypatch.setattr(
        api,
        "classify",
        lambda *_a, **_k: {"category": "technology", "operational_domain": "cyber"},
    )
    resp = client.post("/classify", json={"text": "A new autonomous drone program."})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == FROZEN_RESPONSE_FIELDS
    assert body["category"] in FROZEN_CATEGORIES
    assert body["operational_domain"] in FROZEN_DOMAINS


def test_classify_rejects_blank_text(client, monkeypatch):
    # Whitespace-only text must be rejected with 422 before reaching the LLM,
    # so the contract endpoint never spends a call on empty input.
    monkeypatch.setattr(
        api, "classify", lambda *_a, **_k: pytest.fail("blank text reached the LLM")
    )
    resp = client.post("/classify", json={"text": "   "})
    assert resp.status_code == 422
