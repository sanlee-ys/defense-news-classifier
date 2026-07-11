"""Diagnose when classify()'s prompt cache will actually start working.

classify() marks its system block with ``cache_control``, but on
claude-sonnet-4-6 the cache silently does nothing until the cached prefix
(tool schema + system prompt) clears the model's ~2048-token minimum
cacheable-prefix floor. This script gives visibility into that gap, in two
parts:

1. **Token counting (free, default).** Uses the free ``/v1/messages/count_tokens``
   endpoint to measure classify()'s current cacheable prefix and report how many
   tokens short of (or over) the floor it is -- i.e. whether the cache marker is
   a no-op today.
2. **Live cache diagnosis (``--live``, costs two API calls).** Makes two identical
   classify-shaped calls via the ``cache-diagnosis-2026-04-07`` beta, passing the
   first call's message id as ``previous_message_id`` on the second so the API
   reports *why* the prefix did or didn't cache (``cache_miss_reason``), alongside
   the raw ``cache_creation`` / ``cache_read`` token counts from ``usage``.

This is a diagnostic/reporting tool only -- it does not change classify()'s hot
path. The reusable measurement helpers (``count_prefix_tokens``,
``cacheable_prefix_gap``, ``MIN_CACHEABLE_PREFIX_TOKENS``) live in
``src/classify.py`` so they are unit-tested; this script wires them into a report
and adds the live beta call.

Run:
    uv run --env-file .env python scripts/cache_diagnostics.py            # token counting only (free)
    uv run --env-file .env python scripts/cache_diagnostics.py --live     # + two live cache-diagnosis calls
    uv run --env-file .env python scripts/cache_diagnostics.py --model claude-opus-4-8

Needs ANTHROPIC_API_KEY (both count_tokens and the live calls hit the API; only
count_tokens is free). See .env.example.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Import the classifier module the same way the src/ scripts import each other.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import classify  # noqa: E402

CACHE_DIAGNOSIS_BETA = "cache-diagnosis-2026-04-07"

# A representative on-topic snippet for the --live pass. The exact text does not
# affect the cacheable prefix (tool schema + system prompt) -- it only occupies
# the post-breakpoint, per-request portion of the message -- so any realistic
# article works here.
SAMPLE_TEXT = (
    "The Air Force awarded a multi-year contract for next-generation "
    "aerial refueling tankers, with initial deliveries expected in 2028."
)


def diagnose_cache(
    client: classify.anthropic.Anthropic,
    text: str = SAMPLE_TEXT,
    model: str = classify.MODEL,
    system_prompt: str = classify.SYSTEM_PROMPT,
) -> dict:
    """Make two identical classify-shaped calls and report cache behavior.

    Uses the ``cache-diagnosis-2026-04-07`` beta: the first call primes the
    cache, the second passes the first's message id as ``previous_message_id``
    so the API can report *why* the prefix did or didn't cache. Mirrors
    classify()'s exact call shape (system block with ``cache_control``, forced
    strict tool use) so the numbers reflect the real classifier, not a
    stand-in.

    Args:
        client: Authenticated Anthropic client.
        text: Article snippet for the two probe calls.
        model: Model to diagnose. Defaults to the workhorse.
        system_prompt: System prompt to diagnose. Defaults to ``SYSTEM_PROMPT``.

    Returns:
        Dict with ``first_usage`` / ``second_usage`` (the ``usage`` blocks) and
        ``diagnostics`` (the second response's ``.diagnostics``, carrying
        ``cache_miss_reason`` when the prefix did not cache; ``None`` if the SDK
        did not surface it).
    """
    system_block = {
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }
    common = dict(
        model=model,
        max_tokens=256,
        system=[system_block],
        tools=[classify.CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "classify_article"},
        messages=[{"role": "user", "content": text}],
        betas=[CACHE_DIAGNOSIS_BETA],
    )
    first = client.beta.messages.create(
        diagnostics={"previous_message_id": None}, **common
    )
    second = client.beta.messages.create(
        diagnostics={"previous_message_id": first.id}, **common
    )
    return {
        "first_usage": first.usage,
        "second_usage": second.usage,
        "diagnostics": getattr(second, "diagnostics", None),
    }


def _report_token_counting(client, model: str) -> None:
    """Print the free token-counting section: prefix size vs the cacheable floor."""
    prefix = classify.count_prefix_tokens(client, model=model)
    floor = classify.MIN_CACHEABLE_PREFIX_TOKENS.get(model)
    gap = classify.cacheable_prefix_gap(prefix, model=model)

    print(
        f"\n-- cacheable prefix (tool schema + system prompt), model={model} " + "-" * 6
    )
    print(f"{'prefix tokens':<28}{prefix:>10}")
    if floor is None or gap is None:
        print(
            f"{'floor':<28}{'unknown':>10}   (no documented cacheable-prefix "
            f"floor for {model})"
        )
        return
    print(f"{'floor':<28}{floor:>10}")
    if gap > 0:
        print(
            f"{'gap to floor':<28}{gap:>10}   caching is a NO-OP -- prefix is "
            f"{gap} tokens short of the floor"
        )
    else:
        print(
            f"{'gap to floor':<28}{gap:>10}   caching is ACTIVE -- prefix clears "
            f"the floor by {-gap} tokens"
        )


def _report_live_diagnosis(client, model: str) -> None:
    """Print the live cache-diagnosis section (two API calls)."""
    print(
        "\n-- live cache diagnosis (2 calls via "
        + CACHE_DIAGNOSIS_BETA
        + ") "
        + "-" * 6
    )
    result = diagnose_cache(client, model=model)
    for label, usage in (
        ("call 1", result["first_usage"]),
        ("call 2", result["second_usage"]),
    ):
        created = getattr(usage, "cache_creation_input_tokens", None)
        read = getattr(usage, "cache_read_input_tokens", None)
        uncached = getattr(usage, "input_tokens", None)
        print(
            f"{label}: input(uncached)={uncached}  cache_creation={created}  "
            f"cache_read={read}"
        )
    diagnostics = result["diagnostics"]
    if diagnostics is None:
        print("diagnostics: (not surfaced by this SDK version)")
    else:
        # diagnostics carries cache_miss_reason when the prefix did not cache.
        dump = getattr(diagnostics, "to_dict", None)
        print(
            "diagnostics:",
            json.dumps(dump() if dump else str(diagnostics), indent=2, default=str),
        )


def main() -> None:
    """Report classify()'s cache posture: token-count gap always, live diagnosis on --live."""
    parser = argparse.ArgumentParser(
        description="Diagnose when classify()'s prompt cache will start working."
    )
    parser.add_argument(
        "--model",
        default=classify.MODEL,
        help=f"Model to diagnose (default: {classify.MODEL}).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also make two live calls to report cache_miss_reason (costs API calls).",
    )
    args = parser.parse_args()

    client = classify.make_client()
    _report_token_counting(client, args.model)
    if args.live:
        _report_live_diagnosis(client, args.model)
    else:
        print("\n(pass --live to also report cache_miss_reason from two real calls)")


if __name__ == "__main__":
    main()
