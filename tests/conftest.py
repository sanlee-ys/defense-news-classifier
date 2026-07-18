"""Shared test fixtures and helpers.

Puts src/ on the import path so tests can `import classify`, `import eval`,
`import generate` the same way the scripts import each other at runtime.
"""

import os
import sys
import types

import pytest
from anthropic.types import TextBlock, ToolUseBlock

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(SRC))


# ---------------------------------------------------------------------------
# Integration tests (marked `integration`) need Docker and are slow, so they are
# DESELECTED by default — the everyday suite stays offline and fast. Opt in with
# `pytest --run-integration`.
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests (require Docker; deselected by default)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="needs Docker; pass --run-integration to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# Fakes for the Anthropic SDK response shape.
#
# The real client returns an object whose `.content` is a list of blocks,
# each with a `.type` and (for tool calls) an `.input` dict. We only need
# that surface, so we build tiny stand-ins instead of importing the SDK.
# ---------------------------------------------------------------------------


def make_tool_block(payload: dict):
    """A content block that looks like a tool_use block."""
    return ToolUseBlock(id="toolu_fake", input=payload, name="tool", type="tool_use")


def make_text_block(text: str = ""):
    """A content block that looks like a plain text block."""
    return TextBlock(text=text, type="text")


class FakeMessages:
    """Stands in for client.messages; records the last create() call."""

    def __init__(self, content_blocks):
        self._content_blocks = content_blocks
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return types.SimpleNamespace(content=self._content_blocks)


class FakeClient:
    """Stands in for anthropic.Anthropic."""

    def __init__(self, content_blocks):
        self.messages = FakeMessages(content_blocks)


@pytest.fixture
def tool_client():
    """Factory: build a FakeClient that returns one tool_use block with `payload`."""

    def _make(payload, extra_blocks=None):
        blocks = list(extra_blocks or []) + [make_tool_block(payload)]
        return FakeClient(blocks)

    return _make


class FakeRefusalMessages:
    """client.messages stand-in that returns a refusal (stop_reason=='refusal').

    Mirrors the real SDK shape for a safety-classifier decline: an HTTP 200
    Message with an empty content list, ``stop_reason == "refusal"``, and a
    ``stop_details`` object carrying the refusal category/explanation. Records
    the last create() kwargs like the other fakes.
    """

    def __init__(self, stop_details):
        self._stop_details = stop_details
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return types.SimpleNamespace(
            content=[], stop_reason="refusal", stop_details=self._stop_details
        )


class FakeRefusalClient:
    """Stands in for anthropic.Anthropic, returning a refusal on create()."""

    def __init__(self, stop_details):
        self.messages = FakeRefusalMessages(stop_details)


@pytest.fixture
def refusal_client():
    """Factory: build a client whose create() returns a stop_reason=='refusal' response."""

    def _make(category=None, explanation=None):
        stop_details = None
        if category is not None or explanation is not None:
            stop_details = types.SimpleNamespace(
                category=category, explanation=explanation
            )
        return FakeRefusalClient(stop_details)

    return _make


class FakeCountTokensMessages:
    """client.messages stand-in exposing count_tokens(); records the last call."""

    def __init__(self, input_tokens):
        self._input_tokens = input_tokens
        self.last_kwargs = None

    def count_tokens(self, **kwargs):
        self.last_kwargs = kwargs
        return types.SimpleNamespace(input_tokens=self._input_tokens)


class FakeCountTokensClient:
    """Stands in for anthropic.Anthropic for the count_tokens path."""

    def __init__(self, input_tokens):
        self.messages = FakeCountTokensMessages(input_tokens)


@pytest.fixture
def count_tokens_client():
    """Factory: build a client whose messages.count_tokens() returns `input_tokens`."""

    def _make(input_tokens):
        return FakeCountTokensClient(input_tokens)

    return _make


class FakeSequenceMessages:
    """client.messages stand-in that returns a different payload per create() call.

    Lets a test exercise re-sampling: the first call can return an out-of-enum
    payload and the second a valid one. The final payload repeats if create()
    is called more times than there are payloads.
    """

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        i = min(self.calls, len(self._payloads) - 1)
        self.calls += 1
        return types.SimpleNamespace(content=[make_tool_block(self._payloads[i])])


class FakeSequenceClient:
    """FakeClient whose successive create() calls return successive payloads."""

    def __init__(self, payloads):
        self.messages = FakeSequenceMessages(payloads)


@pytest.fixture
def tool_client_seq():
    """Factory: build a client that returns each payload in turn on create()."""

    def _make(payloads):
        return FakeSequenceClient(payloads)

    return _make


# ---------------------------------------------------------------------------
# Fakes for the Message Batches API (client.messages.batches.*).
#
# A real batch takes time to reach processing_status "ended"; these fakes
# resolve instantly and yield one result per submitted request, so
# run_predictions_batch()-style code can be exercised without polling or
# network access.
# ---------------------------------------------------------------------------


class FakeBatchResultItem:
    """Stands in for one item yielded by client.messages.batches.results().

    `spec` is a payload dict (-> a "succeeded" item wrapping that tool_use
    input), the string "refusal" (-> a "succeeded" item whose message carries
    stop_reason="refusal" and NO tool_use block, matching the real API shape
    for a safety-layer decline), or a bare result-type string like "errored" /
    "canceled" / "expired" (-> an item with no `.message`, matching the real
    SDK shape for a non-succeeded result).
    """

    def __init__(self, custom_id: str, spec):
        self.custom_id = custom_id
        if isinstance(spec, dict):
            message = types.SimpleNamespace(content=[make_tool_block(spec)])
            self.result = types.SimpleNamespace(type="succeeded", message=message)
        elif spec == "refusal":
            message = types.SimpleNamespace(content=[], stop_reason="refusal")
            self.result = types.SimpleNamespace(type="succeeded", message=message)
        else:
            self.result = types.SimpleNamespace(type=spec)


class FakeBatch:
    """Stands in for the Batch object returned by create()/retrieve()."""

    def __init__(self, batch_id: str, processing_status: str, processing: int = 0):
        self.id = batch_id
        self.processing_status = processing_status
        self.request_counts = types.SimpleNamespace(processing=processing)


class FakeBatches:
    """Stands in for client.messages.batches.

    Every batch "ends" on the very first retrieve() (no polling needed in
    tests). results() looks up each submitted request's custom_id in the
    caller-supplied `results_by_custom_id` map and yields the matching
    FakeBatchResultItem -- so results are produced from whatever custom_ids
    the code under test actually generated, not a hardcoded order.
    """

    def __init__(self, results_by_custom_id: dict, batch_id: str = "msgbatch_fake"):
        self.results_by_custom_id = results_by_custom_id
        self.batch_id = batch_id
        self.created_requests = None

    def create(self, requests):
        self.created_requests = requests
        return FakeBatch(self.batch_id, processing_status="ended")

    def retrieve(self, batch_id):
        return FakeBatch(batch_id, processing_status="ended")

    def results(self, batch_id):
        for req in self.created_requests:
            custom_id = req["custom_id"]
            yield FakeBatchResultItem(custom_id, self.results_by_custom_id[custom_id])


class FakeBatchClient:
    """Stands in for anthropic.Anthropic for the Message Batches API path."""

    def __init__(self, results_by_custom_id: dict):
        self.messages = types.SimpleNamespace(batches=FakeBatches(results_by_custom_id))


@pytest.fixture
def batch_client():
    """Factory: build a FakeBatchClient keyed by custom_id -> payload dict | result-type str.

    The map is looked up by whatever custom_id the code under test builds
    (e.g. str(article id), or "g001::workhorse") -- it does not need to be
    populated until after you know that scheme, so tests typically build it
    inline per case.
    """

    def _make(results_by_custom_id):
        return FakeBatchClient(results_by_custom_id)

    return _make
