"""Classifier: maps article text -> {category, operational_domain}.

Single LLM call with forced tool use for structured output.
Usable as a module (import classify) or as a CLI tool.
"""

import json
import os
import sys
from typing import cast

import anthropic
from anthropic.types import TextBlockParam, ToolParam, ToolUseBlock
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

CATEGORIES = ["procurement", "operations", "policy", "technology", "industry"]
DOMAINS = ["air", "land", "sea", "cyber", "space", "multi"]
MODEL = "claude-sonnet-4-6"

# System prompt gives Claude the label definitions so it applies them consistently.
# Without this, the model has to infer what "procurement" vs "industry" means from
# the label name alone, which introduces unnecessary ambiguity.
SYSTEM_PROMPT = """You are a defense-news analyst. Given a defense-related article snippet, \
classify it into exactly one category and one operational domain.

Categories:
- procurement: contracts, acquisitions, budgets, program awards
- operations: active conflict, deployments, military operations
- policy: legislation, treaties, strategy, doctrine
- technology: R&D, new systems, autonomous/drone/AI developments
- industry: defense-company business, earnings, mergers

Operational domains:
- air: aircraft, missiles, UAVs, aerospace operations
- land: ground forces, armored vehicles, infantry operations
- sea: naval vessels, submarines, maritime operations
- cyber: information warfare, network attacks, electronic warfare
- space: satellites, launch systems, space operations
- multi: joint/combined operations spanning more than one domain

Pick the single best label for each field. If the article spans two categories or domains, \
choose the one that is most prominent."""

CLASSIFY_TOOL: ToolParam = {
    "name": "classify_article",
    "description": "Return the category and operational domain for a defense-news snippet.",
    # strict=true turns on server-side constrained decoding: the API guarantees
    # tool_use.input validates against input_schema, including enum membership,
    # before the response is ever returned to us. See decisions/008 for why this
    # replaces the client-side re-sample-on-invalid-label loop that used to live
    # in classify() below (ADR-002 predates strict mode, which wasn't available
    # then). Strict mode requires additionalProperties: false alongside required.
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": CATEGORIES,
                "description": "The primary topic of the article.",
            },
            "operational_domain": {
                "type": "string",
                "enum": DOMAINS,
                "description": "The warfighting domain the article relates to.",
            },
        },
        "required": ["category", "operational_domain"],
        "additionalProperties": False,
    },
}


class InvalidLabelError(ValueError):
    """Raised when the model returns a label outside the allowed enum.

    Kept as a defensive backstop, not the primary guard it was before strict
    mode: with ``strict: true`` on CLASSIFY_TOOL, the API's constrained
    decoding enforces the schema (including these enums) server-side before
    the response is ever returned, so an out-of-enum ``tool_use.input`` should
    no longer occur in practice. ``classify()`` still validates and raises
    this rather than silently trusting the wire, in case that guarantee is
    ever violated (e.g. an API regression) -- but it no longer re-samples on
    failure, since there is nothing left for a re-sample to routinely fix.
    """


def _validate(result: dict) -> dict:
    """Return ``result`` unchanged if both labels are valid; raise InvalidLabelError otherwise."""
    category = result.get("category")
    domain = result.get("operational_domain")
    if category not in CATEGORIES:
        raise InvalidLabelError(f"category {category!r} is not one of {CATEGORIES}")
    if domain not in DOMAINS:
        raise InvalidLabelError(
            f"operational_domain {domain!r} is not one of {DOMAINS}"
        )
    return result


def classify(
    client: anthropic.Anthropic,
    text: str,
    temperature: float | None = None,
    model: str = MODEL,
    system_prompt: str = SYSTEM_PROMPT,
) -> dict:
    """Classify a single defense-news article snippet.

    Makes one LLM call with forced, strict tool use so the response is always
    structured JSON — never free text — and is guaranteed by the API's
    constrained decoding to validate against CLASSIFY_TOOL's schema (including
    both enums) before we ever see it. ``_validate`` is still run as a
    defensive backstop (see ``InvalidLabelError``), but there is no re-sample
    loop any more: a single out-of-schema response would indicate the
    guarantee itself failed, which a client-side retry can't fix.

    Args:
        client: Authenticated Anthropic client.
        text: Raw article snippet to classify.
        temperature: Optional sampling temperature. Left at the API default
            when ``None``; set to ``0`` for the most repeatable output, or pass
            a fixed value when measuring run-to-run variance.
        model: Which Claude model classifies. Defaults to the workhorse
            (claude-sonnet-4-6); pass a higher tier (e.g. the Opus judge) to run
            the same task on a stronger model.
        system_prompt: The instruction block (label definitions + rules) sent as
            the system prompt. Defaults to the module ``SYSTEM_PROMPT`` so callers
            and existing behavior are unchanged; the prompt-optimization loop
            passes a revised prompt here to score a variant against the eval.

    Returns:
        Dict with keys ``category`` and ``operational_domain``, both str.

    Raises:
        InvalidLabelError: If the response falls outside the allowed label
            sets despite ``strict: true`` -- see ``InvalidLabelError``'s
            docstring for why this should no longer occur in practice.
    """
    # cache_control on the system block caches it AND the tool schema (tools
    # render before system in the API's prefix, so a breakpoint on the last
    # system block covers both). Every caller here reuses one system_prompt
    # across many calls in a row -- eval.py/gold_eval.py across every row of
    # their dataset, the optimize.py loop across ~354 scoring calls per
    # iteration -- so this is the textbook repeated-prefix caching case.
    # Below Sonnet 4.6's ~2048-token minimum cacheable prefix the marker is a
    # harmless no-op (cache_creation_input_tokens stays 0, no error); it
    # starts paying off once a prompt grows past that, which happens in
    # practice as optimize.py's loop revises and lengthens the prompt.
    system_block: TextBlockParam = {
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }

    # Pass the SDK's `omit` sentinel when no temperature is requested, so the
    # API uses its own default rather than us forcing a value.
    response = client.messages.create(
        model=model,
        max_tokens=256,
        system=[system_block],
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "classify_article"},
        messages=[{"role": "user", "content": text}],
        temperature=anthropic.omit if temperature is None else temperature,
    )
    tool_block = next(b for b in response.content if isinstance(b, ToolUseBlock))
    return _validate(cast(dict, tool_block.input))


# ---------------------------------------------------------------------------
# Message Batches API path -- an alternative to calling classify() once per
# article, for non-latency-sensitive bulk runs (a full corpus, or the
# gold-eval judge pass). See decisions/009-message-batches-for-bulk-runs.md
# for when to reach for this instead of the synchronous loop.
# ---------------------------------------------------------------------------


class BatchItemError(RuntimeError):
    """Raised when one Message Batches API result item did not succeed.

    Distinct from InvalidLabelError: a batch item can come back "errored",
    "canceled", or "expired" -- outcomes the synchronous classify() path
    can't produce, since a synchronous call either returns a result or raises
    an SDK exception. InvalidLabelError is still raised separately for a
    "succeeded" item whose labels are somehow out of range.
    """


def build_batch_request(
    custom_id: str,
    text: str,
    model: str = MODEL,
    system_prompt: str = SYSTEM_PROMPT,
    temperature: float | None = None,
) -> Request:
    """Build one Message Batches API request with classify()'s exact call shape.

    Mirrors classify()'s system block -- including its cache_control marker --
    so a batch run over the same system_prompt benefits from prompt caching
    the same way the synchronous path does once the prompt is long enough to
    qualify (see classify()'s docstring/comment for the current token-length
    caveat on claude-sonnet-4-6).

    Args:
        custom_id: Caller-chosen id used to match this request's result back
            to its row once the batch completes. Batch results arrive in any
            order, so callers must key on this -- never on position in the
            requests list.
        text: Raw article snippet to classify.
        model: Which Claude model classifies. Defaults to the workhorse
            (claude-sonnet-4-6); pass a higher tier (e.g. the Opus judge) for
            the gold-eval judge pass.
        system_prompt: The instruction block sent as the system prompt.
            Defaults to the module ``SYSTEM_PROMPT``.
        temperature: Optional sampling temperature; omitted (API default)
            when ``None``, matching classify()'s behavior.

    Returns:
        A ``Request`` ready to append to the ``requests`` list passed to
        ``client.messages.batches.create``.
    """
    system_block: TextBlockParam = {
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }
    params: MessageCreateParamsNonStreaming = {
        "model": model,
        "max_tokens": 256,
        "system": [system_block],
        "tools": [CLASSIFY_TOOL],
        "tool_choice": {"type": "tool", "name": "classify_article"},
        "messages": [{"role": "user", "content": text}],
    }
    if temperature is not None:
        params["temperature"] = temperature
    return Request(custom_id=custom_id, params=params)


def parse_batch_result(result) -> dict:
    """Extract and validate the classified labels from one batch result item.

    Args:
        result: One item yielded by iterating
            ``client.messages.batches.results(batch_id)``.

    Returns:
        Dict with keys ``category`` and ``operational_domain``, validated the
        same way as classify()'s return value.

    Raises:
        BatchItemError: If the item's result type is not ``"succeeded"``.
        InvalidLabelError: If a succeeded item's labels are somehow still out
            of range -- the same defensive backstop classify() applies.
    """
    if result.result.type != "succeeded":
        raise BatchItemError(
            f"batch item {result.custom_id!r} did not succeed: {result.result.type}"
        )
    message = result.result.message
    tool_block = next(b for b in message.content if isinstance(b, ToolUseBlock))
    return _validate(cast(dict, tool_block.input))


def make_client() -> anthropic.Anthropic:
    """Build an Anthropic client from the environment.

    Returns:
        Configured ``anthropic.Anthropic`` instance.

    Raises:
        EnvironmentError: If ``ANTHROPIC_API_KEY`` is not set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise OSError(
            "ANTHROPIC_API_KEY is not set. "
            "Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
        )
    return anthropic.Anthropic(api_key=api_key)


def main() -> None:
    """CLI entry point: read article text from args or stdin and print JSON result.

    Raises:
        EnvironmentError: If ``ANTHROPIC_API_KEY`` is not set (via make_client).
    """
    client = make_client()

    # Accept text as CLI args or via stdin (pipe-friendly).
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        print("Enter article text (Ctrl+Z / Ctrl+D to submit):", file=sys.stderr)
        text = sys.stdin.read().strip()

    if not text:
        print("Error: no article text provided.", file=sys.stderr)
        sys.exit(1)

    result = classify(client, text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
