"""
Kafka consumer: tag notes by classifying NoteCreated events.

This closes the event loop in the program's knowledge-base pipeline. ``notes-api``
publishes a ``NoteCreated`` event to the ``note-events`` topic whenever a note is
created (see notes-api ``ADR-001``); this consumer reads each event, classifies the
note's text with the same core ``classify()`` the HTTP service uses, and writes the
predicted labels back onto the note as tags via notes-api's HTTP API. The contract
for this seam is frozen in ``system/SYS-005``.

Design notes
------------
- **Reuses the core classifier, not the HTTP endpoint.** It calls
  ``classify(client, text)`` in-process. The ``/classify`` HTTP wrapper (``api.py``)
  adds nothing this path needs except input validation, which is replicated here.
- **Idempotent, non-destructive writeback (program risk R1).** Delivery is
  at-least-once, so the same ``NoteCreated`` may arrive more than once. The two
  predicted labels are written as *prefixed* tags (``category:<c>``, ``domain:<d>``);
  for each event the consumer keeps the note's own (unprefixed) tags, drops any stale
  classifier-owned tags, and adds the fresh ones — then PUTs the full set with replace
  semantics. Reprocessing the same note therefore converges to the same tags instead
  of accumulating them, and a user's own tags are never clobbered.
- **At-least-once via manual commit.** The offset is committed only after both
  classification and writeback succeed; a transient failure leaves the offset
  uncommitted so the message is redelivered. A *poison* message — one the model can't
  classify, or one notes-api permanently rejects (e.g. the note was deleted) — is
  logged and skipped so it can't wedge the partition.
- **I/O is separated from the decision logic** so the path is unit-testable without a
  broker or network: :func:`process_event` takes injected ``classify``/``writeback``
  callables; the Kafka loop and the HTTP call are thin shells around it.

Run it as its own long-lived process::

    uv run --env-file .env python src/consumer.py
"""

import json
import logging
import os
import time
from collections.abc import Callable, Iterable

import httpx

# Flat import works when run with `--app-dir src` or from src/ (same as api.py).
from classify import InvalidLabelError, classify, make_client

logger = logging.getLogger("consumer")

# Predicted labels are written as namespaced tags so they never collide with a
# user's own tags and can be recognised (and replaced) on reprocessing. The two
# label fields are the frozen /classify contract (system/SYS-004).
CATEGORY_TAG_PREFIX = "category:"
DOMAIN_TAG_PREFIX = "domain:"

# Mirror the HTTP layer's input cap (api.py ClassifyRequest max_length). A note body
# is capped at 10k chars by notes-api anyway; truncate rather than reject so an
# oversized note still gets classified.
MAX_TEXT_CHARS = 10_000

# notes-api caps a note at 20 tags (TagsRequest/NoteRequest @Size(max=20)). The merge
# must stay within it or the writeback 400s and the note silently loses its labels.
MAX_NOTE_TAGS = 20

# Writeback responses that retrying cannot fix — skip and commit. Everything else in
# the 4xx/5xx range (notably 408/425/429 rate-limit/timeout, 409 conflict, and all
# 5xx) is treated as transient and retried, so a momentary notes-api hiccup never
# drops a classification.
PERMANENT_WRITEBACK_CODES = frozenset({400, 404, 410, 422})


class NotePermanentlyRejected(Exception):
    """notes-api rejected a writeback for a reason that retrying won't fix.

    Raised for a *permanent* 4xx (see ``PERMANENT_WRITEBACK_CODES`` — e.g. 404
    because the note was deleted, or 422/400 validation). The consumer logs and
    skips these. Transient statuses (429/408 rate-limit/timeout, 5xx) instead raise
    an ``HTTPStatusError`` so the message is retried.
    """


def note_text(event: dict) -> str:
    """Build the text to classify from a NoteCreated event.

    Combines the note's title and content (title first, for a bit more signal) and
    caps the length. Returns an empty string when there is nothing to classify.
    """
    title = (event.get("title") or "").strip()
    content = (event.get("content") or "").strip()
    text = f"{title}\n\n{content}".strip() if title else content
    return text[:MAX_TEXT_CHARS]


def is_classifier_tag(tag: str) -> bool:
    """True if ``tag`` is one this consumer owns (so it can be safely replaced)."""
    return tag.startswith(CATEGORY_TAG_PREFIX) or tag.startswith(DOMAIN_TAG_PREFIX)


def classifier_tags(result: dict) -> list[str]:
    """The two namespaced tags for a classification result, sorted for determinism."""
    return sorted(
        {
            f"{CATEGORY_TAG_PREFIX}{result['category']}",
            f"{DOMAIN_TAG_PREFIX}{result['operational_domain']}",
        }
    )


def merge_tags(existing: Iterable[str], result: dict) -> list[str]:
    """Merge predicted labels into a note's existing tags, idempotently.

    The note's own tags are preserved; any *previous* classifier-owned tags are
    dropped and replaced by the fresh ones. Applying the same result repeatedly
    yields the same list, so an at-least-once redelivery is a no-op (risk R1).

    Args:
        existing: the note's current tags (from the event's ``tags`` snapshot).
        result: a ``{category, operational_domain}`` classification result.

    Returns:
        The full tag set to write back: the note's own tags (de-duplicated, order
        preserved) followed by the two namespaced classifier tags. The classifier
        tags always make it in; if the note is near notes-api's ``MAX_NOTE_TAGS``
        cap, the oldest user tags are dropped from this writeback to make room, so
        the set never exceeds the cap and triggers a 400. (User tags are only
        dropped from this tag snapshot, never from the note body.)
    """
    classifier = classifier_tags(result)
    user_budget = MAX_NOTE_TAGS - len(classifier)
    user_tags = [t for t in dict.fromkeys(existing) if not is_classifier_tag(t)]
    return user_tags[:user_budget] + classifier


def plan_tags(event: dict, *, classify_fn) -> list[str] | None:
    """Decide the tags to write for one event, or ``None`` to skip it.

    The classification side effect (``classify_fn(text) -> dict``) happens here and
    here only, so a caller can retry the *writeback* without re-paying for the LLM.

    Returns:
        The tag list to write back, or ``None`` to skip the event (no id, no text,
        or a note the model can't classify after its internal re-sample). A skip is
        safe to commit.

    Raises:
        Exception: a *transient* classify failure (LLM/network error) propagates so
            the caller can retry rather than dropping the note.
    """
    note_id = event.get("id")
    if note_id is None:
        logger.warning("event has no id; skipping: %r", event)
        return None

    text = note_text(event)
    if not text:
        logger.info("note %s has no text to classify; skipping", note_id)
        return None

    try:
        result = classify_fn(text)
    except InvalidLabelError as exc:
        # The model twice returned an out-of-enum label. Treat as poison: skip so one
        # bad note can't block the partition. The offset is still committed.
        logger.warning("note %s is unclassifiable (%s); skipping", note_id, exc)
        return None

    tags = merge_tags(event.get("tags") or [], result)
    logger.info("note %s classified %s -> tags %s", note_id, result, tags)
    return tags


def process_event(event: dict, *, classify_fn, writeback_fn) -> str:
    """Plan an event's tags and write them back once (no retry).

    The un-retried decision path, used directly in tests: :func:`run` drives its own
    retry/backoff around :func:`plan_tags` and the writeback so it can retry each
    independently. ``classify_fn(text) -> dict`` and ``writeback_fn(note_id, tags)``
    carry the side effects.

    Returns:
        ``"tagged"`` on success, or ``"skipped"`` for an event :func:`plan_tags`
        skips or one notes-api permanently rejects.

    Raises:
        Exception: any *transient* failure (LLM/network error, notes-api 5xx) is
            propagated.
    """
    tags = plan_tags(event, classify_fn=classify_fn)
    if tags is None:
        return "skipped"

    note_id = event.get("id")
    try:
        writeback_fn(note_id, tags)
    except NotePermanentlyRejected as exc:
        logger.warning(
            "note %s writeback permanently rejected (%s); skipping", note_id, exc
        )
        return "skipped"

    return "tagged"


def make_classify_fn(client):
    """Bind the core classifier to a single Anthropic client."""

    def _classify(text: str) -> dict:
        return classify(client, text)

    return _classify


def make_writeback_fn(http: httpx.Client):
    """Build a writeback callable that PUTs tags to notes-api.

    Replace semantics on the notes-api side make repeated writes idempotent. A
    *permanent* status (``PERMANENT_WRITEBACK_CODES``: 400/404/410/422) is surfaced
    as :class:`NotePermanentlyRejected` (skip). A *transient* status — a 429/408
    rate-limit/timeout, a 409 conflict, any 5xx — raises an ``HTTPStatusError``, and
    a network fault raises an ``httpx.RequestError``; both propagate so the message
    is retried rather than silently dropped.
    """

    def _writeback(note_id, tags: list[str]) -> None:
        resp = http.put(f"/notes/{note_id}/tags", json={"tags": tags})
        if resp.status_code in PERMANENT_WRITEBACK_CODES:
            raise NotePermanentlyRejected(
                f"notes-api {resp.status_code} for note {note_id}: {resp.text}"
            )
        # Any other 4xx (429/408/409/…) or 5xx raises HTTPStatusError → transient.
        resp.raise_for_status()

    return _writeback


def with_retry(
    fn: Callable[[], object],
    *,
    what: str,
    base_backoff: float = 1.0,
    max_backoff: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> object:
    """Call ``fn`` until it succeeds or skips, backing off on transient failure.

    Used by :func:`run` to retry classification and writeback *independently* so a
    writeback retry never re-runs (re-pays for) classification.

    - On success, returns ``fn()``'s value.
    - On :class:`NotePermanentlyRejected`, logs and returns ``None`` (skip — safe to
      commit).
    - On any other exception (transient: LLM/network error, notes-api 5xx/429),
      logs and retries after an exponential backoff capped at ``max_backoff``. This
      blocks the partition until the dependency recovers — the at-least-once trade —
      rather than dropping the note.
    """
    backoff = base_backoff
    while True:
        try:
            return fn()
        except NotePermanentlyRejected as exc:
            logger.warning("%s permanently rejected (%s); skipping", what, exc)
            return None
        except Exception:
            logger.exception("%s failed; retrying in %.1fs", what, backoff)
            sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


def run(
    *,
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    notes_api_base_url: str,
    request_timeout: float = 30.0,
    max_backoff: float = 30.0,
    max_messages: int | None = None,
) -> None:  # pragma: no cover - thin broker/HTTP shell, exercised in integration only
    """Consume ``topic``, tagging each note and committing on success.

    Wires the real collaborators (Kafka consumer, Anthropic client, httpx client).
    Classification and writeback are retried *independently* via :func:`with_retry`
    so a writeback retry never re-runs the LLM, and a transient outage backs off
    instead of hot-looping. The offset is committed only after the event is fully
    handled (tagged or skipped); an unhandled crash leaves it uncommitted, so the
    message is redelivered on restart (at-least-once).

    Runs forever by default. ``max_messages`` bounds it to that many messages and
    then returns — used by the end-to-end integration test to drive the loop once,
    and usable as a "drain N and exit" mode.
    """
    from kafka import KafkaConsumer

    client = make_client()
    classify_fn = make_classify_fn(client)

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers.split(","),
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        key_deserializer=lambda b: b.decode("utf-8") if b else None,
    )
    logger.info(
        "consuming %r from %s as group %r, writing back to %s",
        topic,
        bootstrap_servers,
        group_id,
        notes_api_base_url,
    )

    processed = 0
    try:
        with httpx.Client(base_url=notes_api_base_url, timeout=request_timeout) as http:
            writeback_fn = make_writeback_fn(http)
            for message in consumer:
                event = message.value
                note_id = event.get("id")
                # Classify once (retried on transient failure), then write back
                # (retried independently, so an outage never re-pays for classify).
                tags = with_retry(
                    lambda: plan_tags(event, classify_fn=classify_fn),
                    what=f"classify note {note_id}",
                    max_backoff=max_backoff,
                )
                if tags is not None:
                    with_retry(
                        lambda: writeback_fn(note_id, tags),
                        what=f"writeback note {note_id}",
                        max_backoff=max_backoff,
                    )
                consumer.commit()
                processed += 1
                if max_messages is not None and processed >= max_messages:
                    break
    finally:
        consumer.close()


def main() -> None:  # pragma: no cover - process entry point
    """Read config from the environment and run the consumer."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run(
        bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        topic=os.environ.get("NOTE_EVENTS_TOPIC", "note-events"),
        group_id=os.environ.get("KAFKA_GROUP_ID", "defense-news-classifier"),
        notes_api_base_url=os.environ.get(
            "NOTES_API_BASE_URL", "http://localhost:8081"
        ),
    )


if __name__ == "__main__":
    main()
