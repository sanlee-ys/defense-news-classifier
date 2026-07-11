"""Synthetic dataset generator.

Makes one API call per (category × domain) combination — 30 calls total.
Uses tool_choice to force structured JSON output, which is more reliable
than asking Claude to return raw JSON in the message body.

Output: data/synthetic_articles.csv
Columns: id, text, category, operational_domain
"""

import os
import time
from typing import cast

import anthropic
import pandas as pd
from anthropic.types import ToolParam, ToolUseBlock

CATEGORIES = ["procurement", "operations", "policy", "technology", "industry"]
DOMAINS = ["air", "land", "sea", "cyber", "space", "multi"]
ARTICLES_PER_COMBO = 10
MODEL = "claude-sonnet-4-6"
OUTPUT_PATH = "data/synthetic_articles.csv"

# Tool schema — defines the exact shape Claude must return.
# Enums lock the labels so Claude can't drift to synonyms like "aerial" or "navy".
# strict=true (same rationale as classify.py's CLASSIFY_TOOL -- see
# decisions/008-strict-structured-outputs.md) makes the API enforce this schema,
# including both enums, via server-side constrained decoding rather than
# relying on the enum alone to bias the model. additionalProperties: false is
# required on every object level for strict mode, so it's set on both the
# outer object and the nested item schema.
GENERATE_TOOL: ToolParam = {
    "name": "generate_articles",
    "description": "Return a list of synthetic defense-news article snippets.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "articles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": CATEGORIES,
                        },
                        "operational_domain": {
                            "type": "string",
                            "enum": DOMAINS,
                        },
                    },
                    "required": ["text", "category", "operational_domain"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["articles"],
        "additionalProperties": False,
    },
}


def generate_combo(
    client: anthropic.Anthropic, category: str, domain: str
) -> list[dict]:
    """Ask Claude to produce ARTICLES_PER_COMBO snippets for one (category, domain) pair.

    Uses tool_choice to force Claude to call generate_articles — no free-text fallback.

    Args:
        client: Authenticated Anthropic client.
        category: One of the CATEGORIES labels (e.g. "procurement").
        domain: One of the DOMAINS labels (e.g. "air").

    Returns:
        List of article dicts, each with keys ``text``, ``category``,
        and ``operational_domain``.
    """
    prompt = (
        f"Generate exactly {ARTICLES_PER_COMBO} distinct, realistic defense-news article snippets. "
        f"Each snippet must be about **{category}** and relate to the **{domain}** operational domain. "
        f"Write 2-4 sentences per snippet. "
        f"Vary the countries, weapon systems, companies, and specific scenarios across the {ARTICLES_PER_COMBO} snippets — "
        f"do not repeat the same event or name. "
        f"Set category to '{category}' and operational_domain to '{domain}' for every item."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        tools=[GENERATE_TOOL],
        tool_choice={"type": "tool", "name": "generate_articles"},
        messages=[{"role": "user", "content": prompt}],
    )

    # With tool_choice forcing the tool, the first content block is always a tool_use block.
    tool_block = next(b for b in response.content if isinstance(b, ToolUseBlock))
    return cast(dict, tool_block.input)["articles"]


def main() -> None:
    """Generate the synthetic dataset and write it to OUTPUT_PATH.

    Iterates over every (category × domain) combination, calls generate_combo
    for each, collects the results, and saves a CSV with columns
    ``id``, ``text``, ``category``, ``operational_domain``.

    Raises:
        EnvironmentError: If ``ANTHROPIC_API_KEY`` is not set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise OSError(
            "ANTHROPIC_API_KEY is not set. "
            "Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    client = anthropic.Anthropic(api_key=api_key)

    rows = []
    article_id = 0
    total_combos = len(CATEGORIES) * len(DOMAINS)  # 30

    for i, category in enumerate(CATEGORIES):
        for j, domain in enumerate(DOMAINS):
            combo_num = i * len(DOMAINS) + j + 1
            print(
                f"[{combo_num:2d}/{total_combos}] {category} × {domain} ...", flush=True
            )

            articles = generate_combo(client, category, domain)

            for article in articles:
                rows.append(
                    {
                        "id": article_id,
                        "text": article["text"],
                        "category": article["category"],
                        "operational_domain": article["operational_domain"],
                    }
                )
                article_id += 1

            # Small sleep to stay well inside rate limits between calls.
            if combo_num < total_combos:
                time.sleep(0.5)

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_PATH, index=False)

    print(f"\nSaved {len(df)} articles to {OUTPUT_PATH}")
    print("\nArticle counts by (category, domain):")
    print(
        df.groupby(["category", "operational_domain"])
        .size()
        .unstack(fill_value=0)
        .to_string()
    )


if __name__ == "__main__":
    main()
