"""Assemble an UNLABELED gold test set of real DVIDS snippets, disjoint from the corpus.

Pulls fresh DVIDS news items (excluding everything already catalogued in
data/corpus/manifest.csv, so there is no retrieval leakage), takes each item's
short_description as a news snippet, and writes data/gold/gold.csv with blank
category/domain columns for a human to fill. Those hand labels are the honest answer
key that the v2 eval and the LLM judge are measured against.

Run:
    uv run --env-file .env python scripts/build_gold.py

Refuses to overwrite an existing data/gold/gold.csv, so it can never clobber hand
labels. Needs DVIDS_API_KEY (the public key); standard library only.
"""

from __future__ import annotations

import csv
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SEARCH_URL = "https://api.dvidshub.net/search"
CORPUS_MANIFEST = Path("data/corpus/manifest.csv")
GOLD_DIR = Path("data/gold")
GOLD_CSV = GOLD_DIR / "gold.csv"

TARGET = 45
PER_QUERY = 30
PER_QUERY_KEEP = 3
MIN_SNIPPET = 200

# A spread of queries so the test set touches every category DVIDS can serve and every
# domain. Same shape as the corpus puller; the corpus's own items are excluded by id.
QUERIES = [
    "aircraft carrier strike group operations",
    "submarine deployment",
    "Space Force satellite",
    "missile warning satellite",
    "cyber defense operation",
    "cyberspace mission force",
    "awards contract production",
    "low-rate initial production",
    "delivers first aircraft",
    "conducts exercise",
    "deployment in support of operation",
    "airstrike",
    "hypersonic test",
    "unmanned prototype",
    "directed energy weapon",
    "Secretary of Defense policy",
    "commander testifies before Congress",
    "National Defense Strategy",
]

TITLE_DENY = (
    "change of command",
    "ceremony",
    "sneaker",
    "birthday",
    "spotlight",
    "honored",
    "retire",
    "graduat",
    "memorial",
    "holiday",
    "santa",
    "fun run",
    "scholarship",
    "obituary",
    "promotion",
)


def _get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    full = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    with urllib.request.urlopen(full, timeout=30) as resp:  # noqa: S310 - https only
        return json.loads(resp.read().decode("utf-8"))


def search_news(api_key: str, query: str) -> list[dict[str, Any]]:
    data = _get(
        SEARCH_URL,
        {
            "api_key": api_key,
            "q": query,
            "type": "news",
            "max_results": str(PER_QUERY),
            "sort": "score",
            "sortdir": "desc",
        },
    )
    results = data.get("results", [])
    return results if isinstance(results, list) else []


def corpus_dvids_ids() -> set[str]:
    """The DVIDS asset ids already in the corpus (parsed from the manifest notes)."""
    ids: set[str] = set()
    if not CORPUS_MANIFEST.exists():
        return ids
    with CORPUS_MANIFEST.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ids.update(re.findall(r"news:\d+", row.get("notes", "")))
    return ids


def keep_title(title: str) -> bool:
    low = title.lower()
    return bool(title) and not any(bad in low for bad in TITLE_DENY)


def main() -> int:
    api_key = os.environ.get("DVIDS_API_KEY")
    if not api_key:
        print("DVIDS_API_KEY is not set. Add it to .env and run with --env-file .env.")
        return 1
    if GOLD_CSV.exists():
        print(f"{GOLD_CSV} already exists -- refusing to overwrite hand labels.")
        print("Delete it first if you really want to rebuild the gold set.")
        return 0

    exclude = corpus_dvids_ids()
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for query in QUERIES:
        kept = 0
        for result in search_news(api_key, query):
            if len(rows) >= TARGET or kept >= PER_QUERY_KEEP:
                break
            asset_id = result.get("id")
            title = (result.get("title") or "").strip()
            snippet = " ".join((result.get("short_description") or "").split())
            if (
                not asset_id
                or asset_id in exclude
                or asset_id in seen
                or not keep_title(title)
                or len(snippet) < MIN_SNIPPET
            ):
                continue
            seen.add(asset_id)
            rows.append(
                {
                    "id": f"g{len(rows) + 1:03d}",
                    "dvids_id": asset_id,
                    "source_url": result.get("url", ""),
                    "text": snippet,
                    "category": "",
                    "domain": "",
                }
            )
            kept += 1
        if len(rows) >= TARGET:
            break

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    with GOLD_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "dvids_id", "source_url", "text", "category", "domain"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} unlabeled snippets to {GOLD_CSV}")
    print(f"(excluded {len(exclude)} corpus items to avoid leakage)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
