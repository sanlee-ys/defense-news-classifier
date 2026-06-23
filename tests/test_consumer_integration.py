"""
Integration test: a real ``note-events`` round trip through Kafka.

Where ``test_consumer.py`` fakes the broker, this spins up a REAL Kafka broker in
Docker (Testcontainers), publishes a ``NoteCreated`` event exactly the way notes-api
does — plain JSON value, string key, no Kafka type headers — and drives the
consumer's real consume → deserialize → process path against it. It proves the
SYS-005 wire contract survives an actual broker, which a mock cannot.

The classifier (``classify``) and the notes-api writeback are stubbed so the test
isolates the *Kafka* round trip; both have their own coverage (unit tests here and
the notes-api repo's tests).

Marked ``integration`` and deselected by default (see ``conftest.py``). Run with::

    uv run pytest --run-integration -m integration

Requires Docker. See ``docs/integration-testing.md``.
"""

import json
import uuid

import pytest

import consumer

pytestmark = pytest.mark.integration

TOPIC = "note-events"


@pytest.fixture(scope="module")
def kafka_bootstrap():
    """Start a throwaway Kafka broker in Docker; yield its bootstrap server.

    Skips (rather than fails) when Docker or the image is unavailable, so the
    suite degrades gracefully on a machine without Docker.
    """
    try:
        from testcontainers.kafka import KafkaContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers not installed")

    try:
        container = KafkaContainer()
        container.start()
    except Exception as exc:  # pragma: no cover - Docker daemon/image unavailable
        pytest.skip(f"could not start Kafka container: {exc}")

    try:
        yield container.get_bootstrap_server()
    finally:
        container.stop()


def test_note_event_round_trip(kafka_bootstrap):
    from kafka import KafkaConsumer, KafkaProducer

    group_id = f"it-{uuid.uuid4().hex[:8]}"
    event = {
        "id": 42,
        "title": "Navy awards UAV contract",
        "content": "The Navy awarded a maintenance contract for carrier-based drones.",
        "tags": ["mine"],
        "createdAt": "2026-06-23T12:00:00Z",
    }

    # Publish exactly as notes-api serializes: string key = note id, plain JSON
    # value, no type headers.
    producer = KafkaProducer(
        bootstrap_servers=kafka_bootstrap.split(","),
        key_serializer=lambda k: k.encode("utf-8"),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    producer.send(TOPIC, key=str(event["id"]), value=event)
    producer.flush()
    producer.close()

    # Consume with the SAME deserializers and offset settings run() uses.
    kc = KafkaConsumer(
        TOPIC,
        bootstrap_servers=kafka_bootstrap.split(","),
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        key_deserializer=lambda b: b.decode("utf-8") if b else None,
        consumer_timeout_ms=30_000,
    )
    try:
        received = next(iter(kc), None)
        assert received is not None, "no message consumed from the broker"

        # The JSON wire contract survived a real broker round trip.
        assert received.key == "42"
        assert received.value["id"] == 42
        assert received.value["title"] == event["title"]
        assert received.value["tags"] == ["mine"]

        # Drive the real decision path on the broker-delivered event; stub only the
        # LLM and the notes-api writeback.
        written = {}
        status = consumer.process_event(
            received.value,
            classify_fn=lambda text: {
                "category": "procurement",
                "operational_domain": "sea",
            },
            writeback_fn=lambda note_id, tags: written.update(id=note_id, tags=tags),
        )
        kc.commit()
    finally:
        kc.close()

    assert status == "tagged"
    assert written == {
        "id": 42,
        "tags": ["mine", "category:procurement", "domain:sea"],
    }
