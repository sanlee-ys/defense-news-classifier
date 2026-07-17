"""Assemble a ~300-snippet UNLABELED scaled-eval set of real DVIDS snippets.

The v2.1.0 scaled eval (src/scale_eval.py) grades a larger real-text set with the
validated Opus judge as the answer key, to shrink the n=54 gold set's noise floor. This
pulls fresh DVIDS news snippets for that set, excluding everything already in the corpus
*and* in data/gold/gold.csv, so the scaled set never overlaps the judge's own validation
data (no leakage). Unlike build_gold.py, it writes NO label columns -- nothing here is
hand-labeled; the workhorse and judge produce the labels at eval time.

Same shape and filters as scripts/build_gold.py (kept deliberately close). Refuses to
overwrite an existing data/scale/scale_set.csv.

Run:
    uv run --env-file .env python scripts/build_scale_set.py

Needs DVIDS_API_KEY (the public key); see .env.example. Standard library only.
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
SCALE_DIR = Path("data/scale")
SCALE_CSV = SCALE_DIR / "scale_set.csv"

TARGET = 300
PER_QUERY = 60
PER_QUERY_KEEP = 25
MIN_SNIPPET = 200

# A spread of queries so the set touches every category DVIDS can serve and every domain.
# `industry` (corporate earnings/M&A) is deliberately underserved by the DVIDS wire -- the
# scaled eval reports the resulting label distribution honestly rather than faking balance.
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
    "joint task force operations",
    "amphibious ready group",
    "air defense artillery",
    "electronic warfare squadron",
    "special operations forces",
    "combat training rotation",
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
    """GET a URL with query params and parse the JSON body."""
    full = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    with urllib.request.urlopen(full, timeout=30) as resp:  # noqa: S310 - https only
        return json.loads(resp.read().decode("utf-8"))


def search_news(api_key: str, query: str) -> list[dict[str, Any]]:
    """Search DVIDS news for a query, returning the raw result dicts."""
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


def excluded_dvids_ids() -> set[str]:
    """DVIDS asset ids to avoid: everything in the corpus and in the gold set.

    Returns:
        The union of corpus manifest ``news:*`` ids and the gold set's ``dvids_id``
        column, so the scaled set overlaps neither (no retrieval leakage, and no
        overlap with the judge's own validation data).
    """
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


def keep_title(title: str) -> bool:
    """Return True if the title is non-empty and not obvious non-news (see TITLE_DENY)."""
    low = title.lower()
    return bool(title) and not any(bad in low for bad in TITLE_DENY)


def main() -> int:
    """Build the unlabeled scaled-eval set, refusing to overwrite an existing one.

    Returns:
        Process exit code: 0 on success (or when scale_set.csv already exists),
        1 if DVIDS_API_KEY is not set.
    """
    api_key = os.environ.get("DVIDS_API_KEY")
    if not api_key:
        print("DVIDS_API_KEY is not set. Add it to .env and run with --env-file .env.")
        return 1
    if SCALE_CSV.exists():
        print(f"{SCALE_CSV} already exists -- refusing to overwrite.")
        print("Delete it first if you really want to rebuild the scaled-eval set.")
        return 0

    exclude = excluded_dvids_ids()
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
                    "id": f"s{len(rows) + 1:03d}",
                    "dvids_id": asset_id,
                    "source_url": result.get("url", ""),
                    "text": snippet,
                }
            )
            kept += 1
        if len(rows) >= TARGET:
            break

    SCALE_DIR.mkdir(parents=True, exist_ok=True)
    with SCALE_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["id", "dvids_id", "source_url", "text"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} unlabeled snippets to {SCALE_CSV}")
    print(f"(excluded {len(exclude)} corpus + gold items to avoid leakage)")
    if len(rows) < TARGET:
        print(
            f"NOTE: only {len(rows)} of {TARGET} -- add queries or raise PER_QUERY_KEEP."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
