"""
Shared test fixtures and helpers.

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
# `pytest --run-integration`. See docs/integration-testing.md.
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
