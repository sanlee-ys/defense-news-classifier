"""Fetch a public-domain defense-news corpus from the DVIDS API.

Runs a curated map of on-topic queries (tuned from scripts/dvids_scan.py), pulls the
top news hits, fetches each item's full body via the /asset endpoint, filters obvious
non-news, and writes one UTF-8 .txt per doc plus data/corpus/manifest.csv.

It manages only its own auto-generated docs: the numbered files 000-899 and
manifest.csv. Hand-collected docs (numbered 901+, catalogued in manifest_manual.csv)
are never touched, so this can run while someone hand-collects in parallel.

Run:
    uv run --env-file .env python scripts/fetch_corpus.py

Needs DVIDS_API_KEY (the public key); see .env.example. Standard library only.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

SEARCH_URL = "https://api.dvidshub.net/search"
ASSET_URL = "https://api.dvidshub.net/asset"
CORPUS_DIR = Path("data/corpus")
MANIFEST = CORPUS_DIR / "manifest.csv"

FIELDS = [
    "id",
    "title",
    "source",
    "source_url",
    "published_date",
    "license",
    "category",
    "domain",
    "notes",
]

MAX_PER_CATEGORY = 14
RESULTS_PER_QUERY = 15
MIN_BODY_CHARS = 200
MAX_BODY_CHARS = 4000

# (query, category, domain): tight queries chosen from the scan to surface real news.
# A non-empty domain PINS the domain -- needed for sea/space/cyber, which the item's
# branch alone won't capture. "" derives the domain from the branch. Domain-pinned
# queries are listed first so they survive the per-category cap.
QUERY_MAP: list[tuple[str, str, str]] = [
    ("aircraft carrier strike group operations", "operations", "sea"),
    ("submarine deployment", "operations", "sea"),
    ("destroyer freedom of navigation", "operations", "sea"),
    ("Space Force satellite launch", "operations", "space"),
    ("missile warning satellite", "technology", "space"),
    ("Guardians space control operations", "operations", "space"),
    ("cyber defense operation", "operations", "cyber"),
    ("cyberspace mission force", "operations", "cyber"),
    ("cybersecurity threat hunt", "technology", "cyber"),
    ("awards contract production", "procurement", ""),
    ("low-rate initial production", "procurement", ""),
    ("Milestone C approval", "procurement", ""),
    ("delivers first aircraft", "procurement", ""),
    ("conducts exercise", "operations", ""),
    ("deployment in support of operation", "operations", ""),
    ("airstrike against", "operations", ""),
    ("hypersonic test", "technology", ""),
    ("unmanned prototype demonstration", "technology", ""),
    ("directed energy weapon", "technology", ""),
    ("Secretary of Defense policy", "policy", ""),
    ("commander testifies before Congress", "policy", ""),
    ("National Defense Strategy", "policy", ""),
]

BRANCH_TO_DOMAIN = {
    "Army": "land",
    "Marines": "land",
    "Navy": "sea",
    "Coast Guard": "sea",
    "Air Force": "air",
    "Space Force": "space",
    "Joint": "multi",
}

# Obvious non-news to drop by title substring (ceremonies, base life, human interest).
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
            "max_results": str(RESULTS_PER_QUERY),
            "sort": "score",
            "sortdir": "desc",
        },
    )
    results = data.get("results", [])
    return results if isinstance(results, list) else []


def fetch_asset(api_key: str, asset_id: str) -> dict[str, Any]:
    """Fetch one asset's full record by id, tolerating list- or dict-shaped responses."""
    data = _get(ASSET_URL, {"api_key": api_key, "id": asset_id})
    results = data.get("results", data)
    if isinstance(results, list):
        results = results[0] if results else {}
    return results if isinstance(results, dict) else {}


def slugify(title: str) -> str:
    """Turn a title into a short, filesystem-safe slug for the doc filename."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:50].strip("-") or "untitled"


def keep_title(title: str) -> bool:
    """Return True if the title is non-empty and not obvious non-news (see TITLE_DENY)."""
    low = title.lower()
    return bool(title) and not any(bad in low for bad in TITLE_DENY)


def clean_body(body: str) -> str:
    """Normalize newlines and collapse runs of blank lines in an article body."""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def collect_candidates(api_key: str) -> list[dict[str, Any]]:
    """Search every query, dedupe by id, keep the first category a doc appears under."""
    seen: dict[str, dict[str, Any]] = {}
    for query, category, domain in QUERY_MAP:
        for r in search_news(api_key, query):
            asset_id = r.get("id")
            title = (r.get("title") or "").strip()
            if not asset_id or asset_id in seen or not keep_title(title):
                continue
            seen[asset_id] = {
                "asset_id": asset_id,
                "title": title,
                "url": r.get("url", ""),
                "date": (r.get("date_published") or "")[:10],
                "branch": r.get("branch") or "",
                "category": category,
                "domain": domain,
            }
    # Cap per category for a more even spread.
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for cand in seen.values():
        by_cat.setdefault(cand["category"], []).append(cand)
    selected: list[dict[str, Any]] = []
    for items in by_cat.values():
        selected.extend(items[:MAX_PER_CATEGORY])
    return selected


def clear_auto_docs() -> None:
    """Remove previously auto-generated docs (000-899) so reruns start clean."""
    for path in CORPUS_DIR.glob("[0-8][0-9][0-9]-*.txt"):
        path.unlink()


def write_manifest(rows: list[dict[str, Any]]) -> Path:
    """Write the manifest, falling back to a sibling file if manifest.csv is locked."""

    def _write(path: Path) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    try:
        _write(MANIFEST)
        return MANIFEST
    except PermissionError:
        fallback = CORPUS_DIR / "manifest.generated.csv"
        _write(fallback)
        print(
            f"WARNING: {MANIFEST} is locked (open in Excel?). Wrote {fallback} "
            "instead -- close manifest.csv, then rename this over it."
        )
        return fallback


def main() -> int:
    """Collect candidates, fetch and filter bodies, and write the docs + manifest.

    Returns:
        Process exit code: 0 on success, 1 if DVIDS_API_KEY is not set.
    """
    api_key = os.environ.get("DVIDS_API_KEY")
    if not api_key:
        print("DVIDS_API_KEY is not set. Add it to .env and run with --env-file .env.")
        return 1

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    clear_auto_docs()

    candidates = collect_candidates(api_key)
    print(f"collected {len(candidates)} candidates; fetching bodies...")

    rows: list[dict[str, Any]] = []
    for cand in candidates:
        asset = fetch_asset(api_key, cand["asset_id"])
        body = clean_body(str(asset.get("body") or asset.get("description") or ""))
        if len(body) < MIN_BODY_CHARS:
            continue
        body = body[:MAX_BODY_CHARS]
        stem = f"{len(rows) + 1:03d}-{slugify(cand['title'])}"
        (CORPUS_DIR / f"{stem}.txt").write_text(
            f"{cand['title']}\n\n{body}\n", encoding="utf-8"
        )
        rows.append(
            {
                "id": stem,
                "title": cand["title"],
                "source": "dvids",
                "source_url": cand["url"],
                "published_date": cand["date"],
                "license": "public-domain-usgov",
                "category": cand["category"],
                "domain": cand["domain"]
                or BRANCH_TO_DOMAIN.get(cand["branch"], "multi"),
                "notes": f"dvids {cand['asset_id']}; branch={cand['branch']}",
            }
        )
        time.sleep(0.15)

    target = write_manifest(rows)

    print(f"\nwrote {len(rows)} docs to {CORPUS_DIR}/ and {target}")
    print("by category:", dict(Counter(r["category"] for r in rows)))
    print("by domain:  ", dict(Counter(r["domain"] for r in rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
