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
- procurement: a government/military customer acquiring something — contracts, \
acquisitions, budgets, program awards. The story centers on the deal or the buyer.
- operations: active conflict, deployments, military operations
- policy: legislation, treaties, strategy, doctrine
- technology: R&D, new systems, autonomous/drone/AI developments
- industry: a defense company's own business — earnings, mergers, stock moves, \
layoffs, facility changes. The story centers on the company itself, not a specific deal.

Key distinction — procurement vs industry: procurement is about a purchase or award \
(the customer's side); industry is about a company's financial or corporate news. \
A firm *winning a specific contract* is procurement; a firm *reporting earnings or merging* \
is industry.

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


def classify(client: anthropic.Anthropic, text: str) -> dict:
    """Classify a single defense-news article snippet.

    Makes one LLM call with forced tool use so the response is always
    structured JSON — never free text.

    Args:
        client: Authenticated Anthropic client.
        text: Raw article snippet to classify.

    Returns:
        Dict with keys ``category`` and ``operational_domain``, both str.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=SYSTEM_PROMPT,
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "classify_article"},
        messages=[{"role": "user", "content": text}],
    )
    tool_block = next(b for b in response.content if isinstance(b, ToolUseBlock))
    return cast(dict, tool_block.input)


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
    """CLI entry point: read article text from args or stdin and print JSON result."""
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
