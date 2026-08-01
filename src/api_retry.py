"""One error taxonomy and one backoff loop for every Anthropic call in this repo.

Five modules had grown their own copy of the same five-line retry loop
(``eval.classify_with_retry``, ``gold_eval.classify_retry``,
``gold_eval_rag.classify_rag_retry``, ``optimize._classify_retry``,
``route_eval._classify_runner_up_retry``). Each caught the same two exception
types -- ``InternalServerError`` and ``RateLimitError`` -- which turns out to be
both too narrow and too wide:

- **Too narrow.** ``anthropic.OverloadedError`` (HTTP 529, the single most
  common transient failure on a long unattended run) is *not* a subclass of
  ``InternalServerError``; it inherits straight from ``APIStatusError``. So an
  overloaded API aborted an eval mid-run instead of backing off. Connection
  drops and read timeouts (``APIConnectionError`` / ``APITimeoutError``) were
  missed the same way.
- **Too wide.** A spend cap, an exhausted credit balance, or an
  organization-level quota block can arrive *as a 429*. The old loops slept and
  retried it three times, which cannot succeed and only delays the real
  message. A deterministic account-state failure must fail on the first
  response.

The split is lifted from the pi agent harness's retry policy
(https://github.com/earendil-works/pi, ``packages/ai/src/utils/retry.ts``): a
non-retryable pattern is tested **first** and wins over any type-based
classification, then a retryable pattern/type set decides whether to back off.
The same two-tier order is what makes "429 that is really a billing failure"
fail fast here.

Backoff is unchanged from the loops this replaces: ``base_delay * 2 ** (n - 1)``
before retry *n*, i.e. 2s then 4s with the defaults, bounded by ``max_retries``
total attempts.

Deliberately not included: jitter, a shared retry budget across rows, and
``Retry-After`` header parsing. The SDK already applies its own connection-level
retries underneath this; this layer exists for the failures that survive that,
and adding scheduling policy on top would make two mechanisms fight.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import TypeVar

import anthropic

T = TypeVar("T")

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY_SECONDS = 2.0


class ErrorClass(StrEnum):
    """What a failed API call earns: another attempt, or an immediate stop."""

    FAIL_FAST = "fail-fast"
    RETRY = "retry"


def _pattern(parts: Sequence[str]) -> re.Pattern[str]:
    """Compile an alternation of case-insensitive substrings/patterns."""
    return re.compile("|".join(parts), re.IGNORECASE)


# Account/request state that no amount of waiting repairs. Tested BEFORE
# anything else, so a quota or billing failure dressed as a 429 still fails
# fast. Mirrors pi's NON_RETRYABLE_PROVIDER_LIMIT_ERROR_PATTERN, trimmed to the
# wordings Anthropic actually emits plus the generic gateway ones.
_FAIL_FAST_PATTERN = _pattern(
    [
        "insufficient_quota",
        "quota exceeded",
        "out of budget",
        "credit balance",
        "billing",
        "payment",
        "spend limit",
        "authentication_error",
        "invalid x-api-key",
        "permission_denied",
    ]
)

# Transient provider load, HTTP status, and transport failures. Mirrors pi's
# RETRYABLE_PROVIDER_ERROR_PATTERN, trimmed to this repo's single provider.
_RETRYABLE_PATTERN = _pattern(
    [
        "overloaded",
        "rate.?limit",
        "too many requests",
        r"\b429\b",
        r"\b5\d\d\b",
        "service.?unavailable",
        "server.?error",
        "internal.?error",
        "connection.?error",
        "connection.?reset",
        "fetch failed",
        "timed? out",
        "timeout",
    ]
)


def _fail_fast_types() -> tuple[type[BaseException], ...]:
    """SDK exception types that are deterministic given the same request.

    Resolved at call time rather than bound at import so a test that swaps an
    SDK exception class for a plain one still classifies correctly.
    """
    return (
        anthropic.AuthenticationError,
        anthropic.PermissionDeniedError,
        anthropic.NotFoundError,
        anthropic.BadRequestError,
        anthropic.UnprocessableEntityError,
        anthropic.RequestTooLargeError,
    )


def _retryable_types() -> tuple[type[BaseException], ...]:
    """SDK exception types worth another attempt after a backoff.

    ``OverloadedError`` is listed explicitly: it is a sibling of
    ``InternalServerError`` under ``APIStatusError``, not a subclass, which is
    exactly why the hand-rolled loops missed HTTP 529.
    """
    return (
        anthropic.RateLimitError,
        anthropic.InternalServerError,
        anthropic.OverloadedError,
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
    )


def classify_error(exc: BaseException) -> ErrorClass:
    """Classify one failed API call as retry-with-backoff or fail-fast.

    Order matters and is the whole point:

    1. A message naming quota, billing, or credentials is ``FAIL_FAST`` even
       when it arrived as a 429 -- account state, not throttling.
    2. A deterministic SDK error type (400/401/403/404/413/422) is ``FAIL_FAST``.
    3. A transient SDK error type (429/5xx/529/connection/timeout) is ``RETRY``.
    4. Otherwise the message is matched against the transient pattern, which
       covers wrapped or re-raised errors that lost their SDK type.
    5. Anything still unmatched is ``FAIL_FAST``. An unrecognized failure is
       not assumed transient: retrying an unknown error silently triples the
       spend on a bug.

    Args:
        exc: The exception raised by the API call.

    Returns:
        ``ErrorClass.RETRY`` or ``ErrorClass.FAIL_FAST``.
    """
    message = str(exc)
    if _FAIL_FAST_PATTERN.search(message):
        return ErrorClass.FAIL_FAST
    if isinstance(exc, _fail_fast_types()):
        return ErrorClass.FAIL_FAST
    if isinstance(exc, _retryable_types()):
        return ErrorClass.RETRY
    if _RETRYABLE_PATTERN.search(message):
        return ErrorClass.RETRY
    return ErrorClass.FAIL_FAST


def is_retryable(exc: BaseException) -> bool:
    """Whether ``exc`` should be retried after a backoff.

    Args:
        exc: The exception raised by the API call.

    Returns:
        True if ``classify_error`` returns ``ErrorClass.RETRY``.
    """
    return classify_error(exc) is ErrorClass.RETRY


def backoff_seconds(
    retry_index: int, base_delay: float = DEFAULT_BASE_DELAY_SECONDS
) -> float:
    """Delay before retry number ``retry_index`` (1-indexed).

    Args:
        retry_index: Which retry is about to be scheduled; 1 is the first.
        base_delay: Delay before the first retry.

    Returns:
        ``base_delay * 2 ** (retry_index - 1)`` -- 2s, 4s, 8s at the default.
    """
    return base_delay * 2 ** (retry_index - 1)


def call_with_retry(
    produce: Callable[[], T],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    retry_on: tuple[type[BaseException], ...] = (),
    on_retry: Callable[[int, float, BaseException], None] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> T:
    """Run ``produce`` with bounded retries on transient failures only.

    Args:
        produce: Zero-argument callable making one API call.
        max_retries: Total attempts, not retries-after-the-first. ``3`` means
            up to three calls -- the same meaning the hand-rolled loops had.
        base_delay: Delay before the first retry; doubles each time.
        retry_on: Extra exception types this caller considers transient even
            though the taxonomy does not (``gold_eval`` passes
            ``InvalidLabelError``, whose one observed occurrence cleared on an
            immediate replay).
        on_retry: Called as ``(retry_index, delay_seconds, exc)`` before each
            backoff, for progress output.
        sleep: Injectable sleep, for tests. Defaults to ``time.sleep`` resolved
            at call time.

    Returns:
        Whatever ``produce`` returns.

    Raises:
        ValueError: If ``max_retries`` is less than 1.
        BaseException: The last failure, re-raised unchanged once the attempts
            are exhausted -- or immediately, if it was never retryable.
    """
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")
    wait = sleep or time.sleep
    for attempt in range(max_retries):
        try:
            return produce()
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            if not (isinstance(exc, retry_on) if retry_on else False) and not (
                is_retryable(exc)
            ):
                raise
            retry_index = attempt + 1
            delay = backoff_seconds(retry_index, base_delay)
            if on_retry is not None:
                on_retry(retry_index, delay, exc)
            wait(delay)
    # Unreachable: the loop either returns or raises on its final attempt.
    raise AssertionError("call_with_retry exhausted its loop without returning")
