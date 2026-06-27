# Integration testing (with Testcontainers)

A practical guide to the integration test in this repo — what it is, why it exists,
how to run it, and the gotchas. Written for a Python developer coming back to
integration testing after a while.

> **Status note (2026-06-27):** the Kafka consumer this guide tests is now an
> **inactive historical reference** — notes-api was ported to Python/FastAPI and no
> longer publishes `NoteCreated` events; the classify-and-writeback loop moved to a
> FastAPI `BackgroundTask` in notes-api (see `system/SYS-005`). The test is kept
> green as a Testcontainers reference and a record of the event-driven design; it no
> longer guards a live wire contract. Read the rest in the past tense.

## Unit vs. integration — the one-line distinction

- **Unit test** — exercises *your code* in isolation; every external thing (the LLM,
  the broker, the HTTP API) is a fake. Fast, deterministic, no network, no Docker.
  Almost all of this repo's suite is unit tests (`tests/test_*.py`), and that's
  correct — they're the bulk of the pyramid.
- **Integration test** — exercises *your code against a real dependency*. Slower,
  needs that dependency running, but it catches the things a mock can't: wire
  formats, serialization, connection config, version mismatches.

The trap a mock leaves open: a unit test that fakes Kafka proves your code does the
right thing *given the message you imagined*. It can't prove the message notes-api
actually publishes deserializes the way you assumed. That gap is exactly why this
test exists.

## Why this repo has one

The event loop is: notes-api publishes a `NoteCreated` event → Kafka topic
`note-events` → this service's consumer (`src/consumer.py`) classifies the note and
writes tags back. The consumer's logic is thoroughly unit-tested in
`tests/test_consumer.py` — but every one of those tests *fakes* the broker. Nothing
proved that a message serialized by notes-api (plain JSON, string key, **no Kafka
type headers** — see `system/SYS-005`) actually round-trips through a real broker
and deserializes into the dict our consumer expects.

`tests/test_consumer_integration.py` closes that gap: it stands up a real Kafka
broker, publishes a `NoteCreated` the way notes-api does, and drives the consumer's
real consume → deserialize → process path against it.

## Testcontainers, briefly

[Testcontainers](https://testcontainers.com/) is a library that starts a real
dependency in a **throwaway Docker container** for the duration of a test, then
tears it down. You get a real Kafka/Postgres/Redis — not a mock, not a shared dev
instance someone else might be mutating — scoped to the test and cleaned up after.

In Python it's the `testcontainers` package (here, `testcontainers[kafka]`, declared
in the `dev` dependency group). The shape is:

```python
from testcontainers.kafka import KafkaContainer

with KafkaContainer() as kafka:          # pulls the image, starts a broker
    bootstrap = kafka.get_bootstrap_server()   # e.g. "localhost:53217" (random host port)
    ...                                  # talk to it with kafka-python
# container stopped + removed on block exit
```

Two things worth knowing:

- **It needs Docker.** Testcontainers talks to the local Docker daemon. No Docker →
  no test (ours *skips* rather than fails in that case).
- **Cleanup is automatic.** Testcontainers also starts a tiny sidecar container
  (Ryuk) that reaps the test containers even if the test process is killed, so you
  don't leak containers.

## What our test does (and deliberately doesn't)

`test_note_event_round_trip`:

1. Starts a Kafka broker via `KafkaContainer` (a module-scoped fixture, so the
   broker is started once and shared).
2. **Publishes** a `NoteCreated` event the way notes-api does — `KafkaProducer` with
   a string key (the note id) and a plain-JSON value, no type headers.
3. **Consumes** it with a `KafkaConsumer` configured exactly like `run()` (same
   deserializers, `enable_auto_commit=False`, `auto_offset_reset="earliest"`).
4. Asserts the **wire contract survived** the real round trip (`id`, `title`, `tags`
   come back intact, key is the note id).
5. Drives `process_event` on the broker-delivered event and asserts the right tags
   would be written back.

What it **stubs**: the LLM (`classify_fn`) and the notes-api writeback
(`writeback_fn`). Those are not what this test is about — they're covered by the unit
tests in `test_consumer.py` (and the writeback endpoint by the notes-api repo's own
tests). An integration test should add *one* real dependency and hold the rest
steady; piling in more just makes failures ambiguous and the test flakier.

## Running it

Integration tests are **deselected by default** so the everyday suite stays offline
and fast (Docker isn't always present, and pulling a Kafka image takes minutes).

```bash
# Default: unit suite only — no Docker needed. The IT shows as skipped.
uv run pytest

# Integration test (needs Docker running):
uv run pytest --run-integration -m integration

# Everything, unit + integration:
uv run pytest --run-integration
```

The first integration run pulls the Kafka image (hundreds of MB) and starts a
broker, so expect a few minutes; subsequent runs are faster (image cached).

## How the opt-in is wired

- `pytest.ini` registers the marker:
  ```ini
  markers =
      integration: end-to-end test needing Docker (Testcontainers). Deselected by default; run with --run-integration.
  ```
- `tests/conftest.py` adds the `--run-integration` flag and skips anything marked
  `integration` unless it's passed (`pytest_addoption` + `pytest_collection_modifyitems`).
- The test module opts in with `pytestmark = pytest.mark.integration`.

This keeps the coverage gate and the fast PR check (`uv run pytest --cov=src
--cov-fail-under=66`) untouched — they never need Docker.

## Gotchas / lessons (the stuff that bites)

- **Don't gate fast CI on it.** Integration tests are slow and need Docker; run them
  in a separate job (or on demand), not in the unit lane. Here they're simply absent
  from the default run.
- **Skip, don't fail, when Docker is missing.** The fixture catches a failed
  container start and calls `pytest.skip(...)` so a Docker-less machine degrades
  gracefully instead of going red.
- **Use timeouts, not `while True`.** The consumer is created with
  `consumer_timeout_ms=30_000` so a missing message fails the test in 30s instead of
  hanging forever.
- **Mind container scope.** `scope="module"` starts the broker once for the file; a
  function-scoped fixture would restart it per test (slow). Match the scope to how
  much you share.
- **Pin images for reproducibility** if exact broker behavior matters
  (`KafkaContainer("confluentinc/cp-kafka:7.6.0")`). We use the library default for
  now; pin it the moment a version difference could change a result.
- **Benign warning:** kafka-python warns that lambda (de)serializers "do not
  implement kafka.serializer.Serializer." It's cosmetic — the same lambda style the
  consumer uses — and can be ignored or filtered.

## Where to go deeper

Two natural next layers, both currently unwritten:

1. **Producer-side IT in notes-api (Java + Testcontainers-Kafka):** POST a note,
   assert a `NoteCreated` actually lands on `note-events`. That closes the *other*
   half of the round trip the program risk register tracks.
2. **Full `run()` end-to-end:** drive `run()` in a thread against a real broker with
   a stub notes-api HTTP server, asserting the offset is committed only after a
   successful writeback. Heavier to orchestrate; the current test covers the
   consume/deserialize/process contract, and `with_retry`/commit logic is unit-tested.
