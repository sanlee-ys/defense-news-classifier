"""Contract test: pins classify() span-name prefixes so a rename fails CI.

``contracts/otel-spans.json`` lists the required OpenTelemetry span-name
prefixes. Architecture SYS-023 cites this file. A ``classify()`` call that
emits no span whose name starts with a listed prefix turns this suite
red. The test uses the in-memory exporter and the ``tool_client`` fake, so
it stays offline and spends no API key.
"""

from __future__ import annotations

import json
from pathlib import Path

import classify

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = REPO_ROOT / "contracts" / "otel-spans.json"

# Frozen independently of the source so a silent rename of the live span
# (or a silent edit of the contract) fails this suite.
FROZEN_PREFIXES = ["chat "]


def _load_prefixes() -> list[str]:
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(
        raw, list
    ), f"{CONTRACT_PATH} must be a JSON array of span-name prefixes"
    assert raw, f"{CONTRACT_PATH} must list at least one prefix"
    assert all(
        isinstance(prefix, str) and prefix for prefix in raw
    ), f"{CONTRACT_PATH} entries must be non-empty strings"
    return raw


def test_contract_lists_frozen_prefixes():
    assert _load_prefixes() == FROZEN_PREFIXES


def test_classify_emits_required_span_name_prefixes(monkeypatch, tool_client):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    monkeypatch.setattr(classify, "get_tracer", lambda: tracer)

    client = tool_client(
        {"category": "technology", "operational_domain": "air", "region": "global"}
    )
    result = classify.classify(client, "a drone swarm demo")
    assert result["category"] == "technology"

    names = [span.name for span in exporter.get_finished_spans()]
    assert names, "classify() emitted no spans"
    for prefix in _load_prefixes():
        assert any(
            name.startswith(prefix) for name in names
        ), f"no span name starts with {prefix!r}; emitted {names!r}"
