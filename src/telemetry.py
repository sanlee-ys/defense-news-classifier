"""Optional OpenTelemetry tracing for the classifier's LLM call.

``classify()`` is instrumented against the OpenTelemetry **API**, whose default
tracer is a no-op that records nothing and costs nothing. The **SDK** that
actually records and exports spans is configured only when ``CLASSIFIER_TRACING``
is set — so the eval hot path (hundreds of ``classify()`` calls per optimize
iteration), the offline test suite, and a plain run are all unaffected unless you
opt in.

This mirrors the tracing added to the ``kb-agent`` tool-use loop, so the two
services speak the same observability language: one LLM call becomes a span
carrying OpenTelemetry GenAI semantic-convention attributes (``gen_ai.*`` —
model, token usage, finish reason).

Enable it::

    CLASSIFIER_TRACING=1 uvicorn api:app --app-dir src        # spans to stderr
    CLASSIFIER_TRACING=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
        uvicorn api:app --app-dir src                          # also to a collector

The OTLP exporter is an optional extra (``uv sync --extra otlp``); the console
exporter needs no infrastructure and is always available.
"""

import os
import sys

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer

_TRACER_NAME = "defense-news-classifier"
_CONFIGURED = False


def _enabled() -> bool:
    """Return whether tracing is switched on via ``CLASSIFIER_TRACING``.

    Anything but an obvious off value counts as on, so ``1`` / ``true`` enable it
    while ``0`` / ``false`` / ``no`` / empty leave it off.
    """
    return os.environ.get("CLASSIFIER_TRACING", "").strip().lower() not in (
        "",
        "0",
        "false",
        "no",
    )


def setup_tracing() -> bool:
    """Configure the OpenTelemetry SDK if tracing is enabled. Idempotent.

    When enabled, installs a console span exporter (to stderr, so it never
    pollutes stdout) and, if ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set and the OTLP
    extra is installed, an OTLP exporter alongside it. When disabled, leaves the
    API's global no-op provider in place and does nothing.

    Returns:
        True if the SDK is now active, False if tracing was left as the no-op
        default. Safe to call repeatedly; only the first enabled call configures
        the provider.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return True
    if not _enabled():
        return False

    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: _TRACER_NAME}))
    provider.add_span_processor(
        SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr))
    )

    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        except ImportError:
            print(
                "classifier: OTEL_EXPORTER_OTLP_ENDPOINT is set but the OTLP "
                "exporter is not installed (uv sync --extra otlp). Using the "
                "console exporter only.",
                file=sys.stderr,
            )

    trace.set_tracer_provider(provider)
    _CONFIGURED = True
    return True


def get_tracer() -> Tracer:
    """Return the classifier tracer from whatever provider is installed.

    Resolves against the global provider at call time, so it is the no-op tracer
    until :func:`setup_tracing` installs a real SDK provider.
    """
    return trace.get_tracer(_TRACER_NAME)


def set_usage_attributes(span: Span, usage: object) -> None:
    """Copy Anthropic token-usage counts onto ``span`` as GenAI attributes.

    Reads fields defensively (``getattr``), so a usage object missing the cache
    fields — or missing entirely — contributes fewer attributes rather than
    raising. Callers should guard on ``span.is_recording()`` so nothing is read
    when tracing is off.

    Args:
        span: The span to annotate.
        usage: An Anthropic response ``usage`` object, or None.
    """
    if usage is None:
        return
    fields = (
        ("input_tokens", "gen_ai.usage.input_tokens"),
        ("output_tokens", "gen_ai.usage.output_tokens"),
        ("cache_read_input_tokens", "gen_ai.usage.cache_read_input_tokens"),
        ("cache_creation_input_tokens", "gen_ai.usage.cache_creation_input_tokens"),
    )
    for field, key in fields:
        value = getattr(usage, field, None)
        if value is not None:
            span.set_attribute(key, value)
