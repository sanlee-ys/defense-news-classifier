"""The retry taxonomy: what backs off, what stops immediately, and how long it waits."""

import httpx
import pytest

import api_retry
from api_retry import ErrorClass, backoff_seconds, call_with_retry, classify_error


def _status_error(cls, message: str):
    """Build a real SDK status error so isinstance-based classification is exercised."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(cls.status_code or 500, request=request)
    return cls(message, response=response, body=None)


# --- classification -------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Overloaded",
        "rate limit exceeded, please slow down",
        "internal server error",
        "the request timed out",
        "connection error while reading response",
    ],
)
def test_transient_wordings_are_retryable(message):
    assert classify_error(RuntimeError(message)) is ErrorClass.RETRY


@pytest.mark.parametrize(
    "message",
    [
        "insufficient_quota: you have run out",
        "Your credit balance is too low to access the API",
        "billing error: payment method declined",
        "invalid x-api-key",
        "organization spend limit reached",
    ],
)
def test_account_state_wordings_fail_fast(message):
    assert classify_error(RuntimeError(message)) is ErrorClass.FAIL_FAST


def test_overloaded_529_is_retryable():
    # The concrete gap the hand-rolled loops had: OverloadedError is a sibling
    # of InternalServerError, not a subclass, so `except InternalServerError`
    # never caught a 529.
    import anthropic

    assert not issubclass(anthropic.OverloadedError, anthropic.InternalServerError)
    assert classify_error(_status_error(anthropic.OverloadedError, "Overloaded"))


def test_rate_limit_that_is_really_a_billing_failure_fails_fast():
    # A 429 whose body names billing must NOT be slept on: the pattern check
    # runs before the type check for exactly this case.
    import anthropic

    exc = _status_error(anthropic.RateLimitError, "429: your credit balance is too low")
    assert classify_error(exc) is ErrorClass.FAIL_FAST


def test_plain_rate_limit_is_retryable():
    import anthropic

    exc = _status_error(anthropic.RateLimitError, "429 too many requests")
    assert classify_error(exc) is ErrorClass.RETRY


def test_bad_request_fails_fast():
    import anthropic

    exc = _status_error(anthropic.BadRequestError, "invalid tool schema")
    assert classify_error(exc) is ErrorClass.FAIL_FAST


def test_unrecognized_error_fails_fast():
    # An unknown failure is not assumed transient -- retrying a bug triples spend.
    assert classify_error(ValueError("something nobody anticipated")) is (
        ErrorClass.FAIL_FAST
    )


# --- backoff --------------------------------------------------------------


def test_backoff_matches_the_loops_it_replaces():
    assert backoff_seconds(1) == 2.0
    assert backoff_seconds(2) == 4.0
    assert backoff_seconds(3) == 8.0


# --- the loop -------------------------------------------------------------


def test_returns_first_success_without_sleeping():
    slept: list[float] = []
    assert call_with_retry(lambda: "ok", sleep=slept.append) == "ok"
    assert slept == []


def test_retries_transient_then_succeeds():
    attempts = {"n": 0}
    slept: list[float] = []

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("Overloaded")
        return "ok"

    assert call_with_retry(flaky, max_retries=3, sleep=slept.append) == "ok"
    assert attempts["n"] == 3
    assert slept == [2.0, 4.0]


def test_fail_fast_error_is_not_retried():
    attempts = {"n": 0}
    slept: list[float] = []

    def always():
        attempts["n"] += 1
        raise RuntimeError("insufficient_quota")

    with pytest.raises(RuntimeError):
        call_with_retry(always, max_retries=3, sleep=slept.append)
    assert attempts["n"] == 1  # not 3
    assert slept == []


def test_retry_on_extends_the_taxonomy():
    class Repo(Exception):
        pass

    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise Repo("would otherwise fail fast")
        return "ok"

    assert call_with_retry(flaky, retry_on=(Repo,), sleep=lambda _: None) == "ok"
    assert attempts["n"] == 2


def test_exhausted_attempts_reraise_the_last_error():
    def always():
        raise RuntimeError("Overloaded")

    with pytest.raises(RuntimeError, match="Overloaded"):
        call_with_retry(always, max_retries=2, sleep=lambda _: None)


def test_on_retry_reports_each_backoff():
    events: list[tuple[int, float, str]] = []
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("Overloaded")
        return "ok"

    call_with_retry(
        flaky,
        sleep=lambda _: None,
        on_retry=lambda index, delay, exc: events.append((index, delay, str(exc))),
    )
    assert events == [(1, 2.0, "Overloaded")]


def test_max_retries_below_one_is_a_usage_error():
    with pytest.raises(ValueError, match="max_retries"):
        call_with_retry(lambda: "ok", max_retries=0)


def test_default_sleep_is_resolved_at_call_time(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(api_retry.time, "sleep", lambda seconds: slept.append(seconds))
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("Overloaded")
        return "ok"

    assert call_with_retry(flaky) == "ok"
    assert slept == [2.0]
