"""
Classifier: maps article text -> {category, operational_domain}

Single LLM call with forced tool use for structured output.
Usable as a module (import classify) or as a CLI tool.
"""

import json
import os
import sys
from typing import cast

import anthropic
from anthropic.types import ToolParam, ToolUseBlock

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
    },
}


class InvalidLabelError(ValueError):
    """Raised when the model returns a label outside the allowed enum.

    A tool-use ``enum`` strongly biases the model toward valid labels but is
    not a hard server-side constraint, so on rare occasions the model can
    return an out-of-enum value. We validate the result ourselves and surface
    it rather than letting a bad label flow silently into the metrics.
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

    Makes one LLM call with forced tool use so the response is always
    structured JSON — never free text. The tool-use ``enum`` biases the model
    toward valid labels but does not hard-enforce them, so the result is
    validated against the allowed sets; on the rare out-of-enum response the
    call is re-sampled once before raising.

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
        InvalidLabelError: If two successive responses both fall outside the
            allowed label sets.
    """
    # Pass the SDK's `omit` sentinel when no temperature is requested, so the
    # API uses its own default rather than us forcing a value.
    last_exc: InvalidLabelError | None = None
    for _ in range(2):  # one normal call, plus one re-sample on an invalid label
        response = client.messages.create(
            model=model,
            max_tokens=256,
            system=system_prompt,
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "classify_article"},
            messages=[{"role": "user", "content": text}],
            temperature=anthropic.omit if temperature is None else temperature,
        )
        tool_block = next(b for b in response.content if isinstance(b, ToolUseBlock))
        try:
            return _validate(cast(dict, tool_block.input))
        except InvalidLabelError as exc:
            last_exc = exc  # try once more; the next sample usually lands in range
    assert last_exc is not None  # loop ran at least once
    raise last_exc


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
