"""Tests for the optional OpenTelemetry tracing layer (src/telemetry.py).

Offline (no API key, no network, no collector): (1) the SDK only activates when
CLASSIFIER_TRACING is set, so the eval hot path and the rest of the suite stay
no-op; (2) a classify() call emits a `chat <model>` span with GenAI token and
result attributes, captured through an in-memory exporter with the existing
tool_client fake — proving the instrumentation without touching the network.
"""

import types

import pytest

import classify
from telemetry import _enabled, setup_tracing


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_enabled_true_for_truthy_values(monkeypatch, value):
    monkeypatch.setenv("CLASSIFIER_TRACING", value)
    assert _enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "  "])
def test_enabled_false_for_off_values(monkeypatch, value):
    monkeypatch.setenv("CLASSIFIER_TRACING", value)
    assert _enabled() is False


def test_setup_tracing_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("CLASSIFIER_TRACING", raising=False)
    import telemetry

    # Reset the idempotency latch so a prior enabled run can't mask this.
    monkeypatch.setattr(telemetry, "_CONFIGURED", False)
    assert setup_tracing() is False


def test_classify_emits_chat_span_with_attributes(monkeypatch, tool_client):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    # A local provider + in-memory exporter injected via the tracer accessor —
    # the global provider is never touched, so this test stays isolated.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    monkeypatch.setattr(classify, "get_tracer", lambda: tracer)

    # The tool_client fake returns one tool_use block; give the response object a
    # usage + stop_reason so the recording path has something to read.
    client = tool_client({"category": "technology", "operational_domain": "air"})
    original_create = client.messages.create

    def create_with_usage(**kwargs):
        resp = original_create(**kwargs)
        resp.usage = types.SimpleNamespace(
            input_tokens=42,
            output_tokens=6,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=30,
        )
        resp.stop_reason = "tool_use"
        return resp

    monkeypatch.setattr(client.messages, "create", create_with_usage)

    result = classify.classify(client, "a drone swarm demo")
    assert result == {"category": "technology", "operational_domain": "air"}

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == f"chat {classify.MODEL}"
    assert span.attributes["gen_ai.operation.name"] == "chat"
    assert span.attributes["gen_ai.usage.input_tokens"] == 42
    assert span.attributes["gen_ai.usage.cache_creation_input_tokens"] == 30
    assert span.attributes["gen_ai.response.finish_reasons"] == ("tool_use",)
    assert span.attributes["classifier.category"] == "technology"
    assert span.attributes["classifier.operational_domain"] == "air"
