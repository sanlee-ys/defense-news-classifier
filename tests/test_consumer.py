"""
Tests for src/consumer.py — the Kafka consumer that tags notes.

Fully offline: the decision logic (process_event and its helpers) is exercised with
injected fakes, and the HTTP writeback shell is tested with httpx's MockTransport.
No broker, no LLM, no network, no API key — matching the suite's existing style.
"""

import httpx
import pytest

import consumer
from classify import InvalidLabelError


def _event(**overrides) -> dict:
    """A NoteCreated event with sensible defaults, like notes-api emits."""
    event = {
        "id": 1,
        "title": "New drone contract",
        "content": "The Navy awarded a UAV maintenance contract.",
        "tags": [],
        "createdAt": "2026-06-23T12:00:00Z",
    }
    event.update(overrides)
    return event


# --- pure helpers ---------------------------------------------------------------


def test_note_text_combines_title_and_content():
    text = consumer.note_text({"title": "Title", "content": "Body"})
    assert text == "Title\n\nBody"


def test_note_text_is_empty_when_blank():
    assert consumer.note_text({"title": "  ", "content": ""}) == ""


def test_note_text_truncates_to_cap():
    long_body = "x" * (consumer.MAX_TEXT_CHARS + 500)
    assert (
        len(consumer.note_text({"title": "", "content": long_body}))
        == consumer.MAX_TEXT_CHARS
    )


def test_classifier_tags_uses_the_frozen_contract_fields():
    tags = consumer.classifier_tags(
        {"category": "technology", "operational_domain": "air"}
    )
    assert tags == ["category:technology", "domain:air"]


def test_merge_tags_preserves_user_tags_and_adds_labels():
    merged = consumer.merge_tags(
        ["home", "urgent"], {"category": "operations", "operational_domain": "sea"}
    )
    assert merged == ["home", "urgent", "category:operations", "domain:sea"]


def test_merge_tags_is_idempotent():
    result = {"category": "policy", "operational_domain": "cyber"}
    once = consumer.merge_tags(["keep"], result)
    twice = consumer.merge_tags(once, result)
    assert once == twice


def test_merge_tags_replaces_stale_classifier_tags():
    # A re-classification that lands on different labels must not leave the old ones.
    existing = ["keep", "category:industry", "domain:space"]
    merged = consumer.merge_tags(
        existing, {"category": "operations", "operational_domain": "sea"}
    )
    assert merged == ["keep", "category:operations", "domain:sea"]


# --- process_event --------------------------------------------------------------


def test_process_event_tags_note():
    written = {}

    def classify_fn(text):
        assert "drone contract" in text
        return {"category": "procurement", "operational_domain": "air"}

    def writeback_fn(note_id, tags):
        written["id"] = note_id
        written["tags"] = tags

    status = consumer.process_event(
        _event(tags=["mine"]), classify_fn=classify_fn, writeback_fn=writeback_fn
    )

    assert status == "tagged"
    assert written["id"] == 1
    assert written["tags"] == ["mine", "category:procurement", "domain:air"]


def test_process_event_skips_event_without_id():
    status = consumer.process_event(
        _event(id=None),
        classify_fn=lambda _t: pytest.fail("should not classify an id-less event"),
        writeback_fn=lambda _i, _t: pytest.fail("should not write back"),
    )
    assert status == "skipped"


def test_process_event_skips_blank_note():
    status = consumer.process_event(
        _event(title="", content="   "),
        classify_fn=lambda _t: pytest.fail("blank note reached the classifier"),
        writeback_fn=lambda _i, _t: pytest.fail("should not write back"),
    )
    assert status == "skipped"


def test_process_event_skips_unclassifiable_note():
    def classify_fn(_text):
        raise InvalidLabelError("model returned an out-of-enum label twice")

    status = consumer.process_event(
        _event(),
        classify_fn=classify_fn,
        writeback_fn=lambda _i, _t: pytest.fail("poison note must not be written back"),
    )
    assert status == "skipped"


def test_process_event_skips_permanently_rejected_writeback():
    def writeback_fn(_id, _tags):
        raise consumer.NotePermanentlyRejected("404: note was deleted")

    status = consumer.process_event(
        _event(),
        classify_fn=lambda _t: {"category": "operations", "operational_domain": "land"},
        writeback_fn=writeback_fn,
    )
    assert status == "skipped"


def test_process_event_propagates_transient_failure():
    # A transient writeback error must propagate so the caller leaves the offset
    # uncommitted and the message is redelivered.
    def writeback_fn(_id, _tags):
        raise httpx.ConnectError("notes-api is down")

    with pytest.raises(httpx.ConnectError):
        consumer.process_event(
            _event(),
            classify_fn=lambda _t: {
                "category": "operations",
                "operational_domain": "land",
            },
            writeback_fn=writeback_fn,
        )


# --- I/O shells -----------------------------------------------------------------


def test_make_classify_fn_calls_core_classify(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        consumer,
        "classify",
        lambda client, text: seen.update(client=client, text=text) or {},
    )
    consumer.make_classify_fn("the-client")("hello")
    assert seen == {"client": "the-client", "text": "hello"}


def _writeback_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://notes")


def test_writeback_puts_tags_and_succeeds():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"id": 1, "tags": ["category:operations"]})

    with _writeback_client(handler) as http:
        consumer.make_writeback_fn(http)(1, ["category:operations", "domain:sea"])

    assert captured["method"] == "PUT"
    assert captured["path"] == "/notes/1/tags"
    assert '"tags"' in captured["body"]


def test_writeback_4xx_raises_permanent():
    with _writeback_client(lambda _r: httpx.Response(404, text="not found")) as http:
        with pytest.raises(consumer.NotePermanentlyRejected):
            consumer.make_writeback_fn(http)(99, ["category:policy"])


def test_writeback_5xx_raises_transient():
    with _writeback_client(lambda _r: httpx.Response(503, text="unavailable")) as http:
        with pytest.raises(httpx.HTTPStatusError):
            consumer.make_writeback_fn(http)(1, ["category:policy"])


def test_writeback_429_is_transient_not_permanent():
    # A rate-limit (429) must be retried, not skipped — it is not in the permanent set.
    with _writeback_client(lambda _r: httpx.Response(429, text="slow down")) as http:
        with pytest.raises(httpx.HTTPStatusError):
            consumer.make_writeback_fn(http)(1, ["category:policy"])


# --- tag cap --------------------------------------------------------------------


def test_merge_tags_respects_note_tag_cap():
    # A note already at the 20-tag cap must not push the merged set over it (which
    # notes-api would 400), and the two classifier tags must still land.
    existing = [f"t{i}" for i in range(consumer.MAX_NOTE_TAGS)]
    merged = consumer.merge_tags(
        existing, {"category": "policy", "operational_domain": "land"}
    )
    assert len(merged) == consumer.MAX_NOTE_TAGS
    assert "category:policy" in merged
    assert "domain:land" in merged
    # The oldest user tags are dropped to make room; the classifier tags are kept.
    assert merged[: consumer.MAX_NOTE_TAGS - 2] == [f"t{i}" for i in range(18)]


# --- plan_tags ------------------------------------------------------------------


def test_plan_tags_returns_tags_for_a_valid_note():
    tags = consumer.plan_tags(
        _event(tags=["mine"]),
        classify_fn=lambda _t: {"category": "procurement", "operational_domain": "air"},
    )
    assert tags == ["mine", "category:procurement", "domain:air"]


def test_plan_tags_skips_without_id():
    assert (
        consumer.plan_tags(
            _event(id=None), classify_fn=lambda _t: pytest.fail("should not classify")
        )
        is None
    )


def test_plan_tags_skips_blank_note():
    assert (
        consumer.plan_tags(
            _event(title="", content="  "),
            classify_fn=lambda _t: pytest.fail("should not classify"),
        )
        is None
    )


def test_plan_tags_skips_unclassifiable_note():
    def boom(_text):
        raise InvalidLabelError("out of enum twice")

    assert consumer.plan_tags(_event(), classify_fn=boom) is None


def test_plan_tags_propagates_transient_classify_failure():
    def boom(_text):
        raise RuntimeError("LLM 503")

    with pytest.raises(RuntimeError):
        consumer.plan_tags(_event(), classify_fn=boom)


# --- with_retry -----------------------------------------------------------------


def test_with_retry_retries_transient_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    slept = []
    result = consumer.with_retry(
        flaky, what="thing", base_backoff=0.1, sleep=slept.append
    )

    assert result == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2  # backed off before each retry


def test_with_retry_caps_backoff():
    delays = []

    def flaky():
        if len(delays) < 6:
            raise RuntimeError("transient")
        return "ok"

    consumer.with_retry(
        flaky, what="thing", base_backoff=1.0, max_backoff=4.0, sleep=delays.append
    )
    # 1, 2, 4, then capped at 4 — never exceeds max_backoff.
    assert max(delays) == 4.0
    assert delays[:3] == [1.0, 2.0, 4.0]


def test_with_retry_skips_on_permanent_rejection():
    def perm():
        raise consumer.NotePermanentlyRejected("404 deleted")

    assert consumer.with_retry(perm, what="thing", sleep=lambda _s: None) is None
