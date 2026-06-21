"""Append policy-candidate snippets from DVIDS to the gold set, for hand-labeling.

The gold set came out heavy on operations/technology and thin on policy. This pulls
fresh DVIDS items likely to be policy / leadership / strategy news -- excluding every
asset already in the corpus or the gold set (no retrieval leakage, no duplicates) --
and appends them to data/gold/gold.csv with BLANK category/domain. A human then labels
and confirms them (some candidates may not actually be policy; relabel or delete those).

Run:
    uv run --env-file .env python scripts/add_policy_gold.py

Needs DVIDS_API_KEY (the public key); standard library only.
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
GOLD_CSV = Path("data/gold/gold.csv")
FIELDS = ["id", "dvids_id", "source_url", "text", "category", "domain"]

WANT = 8
PER_QUERY = 30
PER_QUERY_KEEP = 3
MIN_SNIPPET = 200

# Queries aimed at the archived DoD leadership/policy news, not unit PR.
QUERIES = [
    "Secretary of Defense announces policy",
    "testifies before Congress posture",
    "new defense policy guidance directive",
    "nuclear posture review",
    "arms control treaty agreement",
    "National Defense Strategy released",
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


def existing_dvids_ids() -> set[str]:
    """Asset ids already used anywhere -- corpus manifest notes + gold dvids_id."""
    ids: set[str] = set()
    if CORPUS_MANIFEST.exists():
        with CORPUS_MANIFEST.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                ids.update(re.findall(r"news:\d+", row.get("notes", "")))
    if GOLD_CSV.exists():
        with GOLD_CSV.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("dvids_id"):
                    ids.add(row["dvids_id"])
    return ids


def next_gold_index() -> int:
    """One past the highest existing gNNN id, so appended ids never collide."""
    if not GOLD_CSV.exists():
        return 1
    highest = 0
    with GOLD_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            match = re.match(r"g(\d+)", row.get("id", ""))
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def keep_title(title: str) -> bool:
    low = title.lower()
    return bool(title) and not any(bad in low for bad in TITLE_DENY)


def main() -> int:
    api_key = os.environ.get("DVIDS_API_KEY")
    if not api_key:
        print("DVIDS_API_KEY is not set. Add it to .env and run with --env-file .env.")
        return 1

    exclude = existing_dvids_ids()
    idx = next_gold_index()
    seen: set[str] = set()
    new_rows: list[dict[str, str]] = []

    for query in QUERIES:
        kept = 0
        for result in search_news(api_key, query):
            if len(new_rows) >= WANT or kept >= PER_QUERY_KEEP:
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
            new_rows.append(
                {
                    "id": f"g{idx:03d}",
                    "dvids_id": asset_id,
                    "source_url": result.get("url", ""),
                    "text": snippet,
                    "category": "",
                    "domain": "",
                }
            )
            idx += 1
            kept += 1
        if len(new_rows) >= WANT:
            break

    if not new_rows:
        print("No new policy candidates found (all already in corpus/gold).")
        return 0

    with GOLD_CSV.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=FIELDS).writerows(new_rows)

    print(f"appended {len(new_rows)} unlabeled candidates to {GOLD_CSV}:")
    for row in new_rows:
        print(f"  {row['id']}  {row['text'][:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
