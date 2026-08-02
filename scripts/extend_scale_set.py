"""Extend the scaled-eval snippet set with more DVIDS news snippets.

WHY. ADR-023 declined the `global`-boundary clause at McNemar p=0.0522 on n=295 and
named the one thing that would change the answer: a higher-power ruler.
``src/mcnemar_power.py`` prices that at ~545 effective pairs for 80% power against the
observed effect and ~713 for 90%, so the follow-up needs roughly 250-435 more snippets
than the frozen 300. This script collects them.

THE SAMPLING METHOD IS THE ORIGINAL ONE, AND LITERALLY SO. Every filter, query and
exclusion is *imported* from ``scripts/build_scale_set.py`` rather than restated here --
same 24 queries, same relevance sort, same title deny-list, same 200-character minimum,
same public DVIDS search endpoint. A copy could drift; an import cannot. ADR-015 governs
the source: DVIDS is US government public-affairs work, public domain under 17 U.S.C.
Section 105, retrieved through the official API. That is the same collection the existing
300 came from, not a new pipeline, and it is why this does not run into CLAUDE.md's
"scraping pipelines are out of scope" line.

THE ONE DEVIATION, STATED PLAINLY. ``build_scale_set`` kept at most **25** rows per
query and stopped the moment it reached 300 -- so it filled its target from roughly the
first half of the query list and never reached the rest. This keeps up to
``--per-query`` rows (default: the whole result page) and walks the full list. Nothing
else changes. The consequence is real and worth naming: the original set is more evenly
spread across its consumed queries, while the extension leans toward whichever queries
return more usable results. That shifts topic mix, not label definitions, and the
combined set's region distribution is reported by the eval rather than engineered.

THREE EXCLUSIONS, TWO OF THEM INHERITED.

- **Corpus and gold ids** (inherited): the judge must never grade its own validation
  data, and the retrieval corpus stays out for the same no-leakage reason.
- **The frozen scale set's DVIDS ids** (new): re-collecting a snippet already numbered
  ``s001..s300`` would pair one snippet against two answer-key rows.
- **Exact-duplicate snippet TEXT** (new, and the ADR-023 lesson): that run found four
  duplicate groups it could only drop from the pairing *after* they had been judge-graded
  -- including ``s024``/``s025``, byte-identical text the key labels ``europe`` and
  ``middle-east``, so at least one row is unwinnable for any classifier. Duplicates also
  violate McNemar's independence assumption in the anti-conservative direction. Here they
  are removed **before** any grading, against both the frozen set and the extension
  itself, so nothing is paid for and then discarded.

Ids continue from the end of the frozen set (``s301``, ``s302``, ...), and the output is
a SEPARATE file: appending to ``data/scale/scale_set.csv`` would silently redefine what
every committed ``s001..s300`` artifact is a measurement of.

Run (free -- DVIDS search costs nothing and makes no LLM call):

    uv run --env-file .env python scripts/extend_scale_set.py --target 435

Needs ``DVIDS_API_KEY`` (the public read-only key); see ``.env.example``. Refuses to
overwrite an existing extension file. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_scale_set import (  # noqa: E402  (path set above)
    MIN_SNIPPET,
    PER_QUERY,
    QUERIES,
    excluded_dvids_ids,
    keep_title,
    search_news,
)

SCALE_CSV = Path("data/scale/scale_set.csv")
EXT_CSV = Path("data/scale/scale_set_ext.csv")
FIELDNAMES = ["id", "dvids_id", "source_url", "text"]

# 80% power against the ADR-023 effect needs ~545 effective pairs and 90% needs ~713
# (src/mcnemar_power.py). The frozen set contributes 295 effective rows, so this is the
# default ask: enough to clear the 90% mark with headroom for the duplicates that only
# show up after collection.
DEFAULT_TARGET = 435


def normalize(text: str) -> str:
    """Collapse whitespace so two snippets that differ only in spacing compare equal.

    Matches ``region_clause_ab.duplicate_snippet_ids``, which strips before comparing --
    the point is that this script's notion of "duplicate" is the same one the pairing
    will later apply, so nothing gets collected here only to be dropped there.

    Args:
        text: Raw snippet text.

    Returns:
        The whitespace-normalized text.
    """
    return " ".join(str(text).split())


def existing_rows(path: Path = SCALE_CSV) -> list[dict[str, str]]:
    """Read the frozen scale set.

    Args:
        path: Path to the frozen scale-set CSV.

    Returns:
        Its rows, or an empty list if the file is absent.
    """
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def next_index(rows: list[dict[str, str]]) -> int:
    """The number the extension's first id should carry.

    Derived from the highest ``sNNN`` actually present rather than from ``len(rows)``,
    so a set that ever gains or loses a row cannot produce an id that collides with one
    already spent.

    Args:
        rows: The frozen set's rows.

    Returns:
        One past the highest existing index (1 for an empty set).
    """
    numbers = [
        int(row["id"][1:])
        for row in rows
        if row.get("id", "").startswith("s") and row["id"][1:].isdigit()
    ]
    return max(numbers, default=0) + 1


def select(
    results: list[dict[str, Any]],
    exclude_ids: set[str],
    seen_texts: set[str],
    seen_ids: set[str],
    limit: int,
) -> list[dict[str, str]]:
    """Filter one query's raw results down to keepable, non-duplicate snippets.

    Pure and network-free so the selection rules are testable without a key. Mutates
    ``seen_texts`` and ``seen_ids`` as it accepts rows, which is what makes the
    de-duplication hold *across* queries as well as within one.

    Args:
        results: Raw DVIDS search result dicts.
        exclude_ids: DVIDS asset ids that must not be collected (corpus, gold, frozen
            scale set).
        seen_texts: Normalized texts already accepted, updated in place.
        seen_ids: DVIDS asset ids already accepted, updated in place.
        limit: Maximum rows to take from this query.

    Returns:
        Accepted rows with ``dvids_id``, ``source_url`` and ``text`` (no ``id`` yet --
        numbering is the caller's job, so it stays contiguous across queries).
    """
    kept: list[dict[str, str]] = []
    for result in results:
        if len(kept) >= limit:
            break
        asset_id = result.get("id")
        title = (result.get("title") or "").strip()
        snippet = normalize(result.get("short_description") or "")
        if (
            not asset_id
            or asset_id in exclude_ids
            or asset_id in seen_ids
            or normalize(snippet) in seen_texts
            or not keep_title(title)
            or len(snippet) < MIN_SNIPPET
        ):
            continue
        seen_ids.add(asset_id)
        seen_texts.add(normalize(snippet))
        kept.append(
            {
                "dvids_id": asset_id,
                "source_url": result.get("url", ""),
                "text": snippet,
            }
        )
    return kept


def number(rows: list[dict[str, str]], start: int) -> list[dict[str, str]]:
    """Assign contiguous ``sNNN`` ids starting at ``start``.

    Args:
        rows: Accepted rows, in collection order.
        start: First index to use.

    Returns:
        The same rows with an ``id`` key, in ``FIELDNAMES`` key order.
    """
    return [
        {"id": f"s{start + i:03d}", **row} for i, row in enumerate(rows)  # noqa: RUF005
    ]


def write(rows: list[dict[str, str]], path: Path = EXT_CSV) -> None:
    """Write the extension CSV.

    Args:
        rows: Numbered rows.
        path: Destination.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    """Collect the extension set, refusing to overwrite an existing one.

    Args:
        argv: Command-line arguments (for testing); defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: 0 on success (including "already exists"), 1 if
        ``DVIDS_API_KEY`` is unset.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target",
        type=int,
        default=DEFAULT_TARGET,
        help=f"how many new snippets to collect (default {DEFAULT_TARGET}: enough for "
        "~90%% power against the ADR-023 effect once the frozen 295 are added)",
    )
    parser.add_argument(
        "--per-query",
        type=int,
        default=PER_QUERY,
        help=f"max rows kept per query (default {PER_QUERY}; build_scale_set.py used "
        "25, which is the one documented deviation)",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("DVIDS_API_KEY")
    if not api_key:
        print("DVIDS_API_KEY is not set. Add it to .env and run with --env-file .env.")
        return 1
    if EXT_CSV.exists():
        print(f"{EXT_CSV} already exists -- refusing to overwrite.")
        print("Delete it first if you really want to rebuild the extension.")
        return 0

    # Paths passed explicitly rather than left to the parameter defaults: a default
    # argument binds at DEFINITION time, so a caller (or a test) that repoints
    # SCALE_CSV / EXT_CSV would otherwise be silently ignored -- and this function
    # writes a file, so "silently ignored" means writing to the real data directory.
    frozen = existing_rows(SCALE_CSV)
    exclude = excluded_dvids_ids() | {
        row["dvids_id"] for row in frozen if row.get("dvids_id")
    }
    seen_texts = {normalize(row["text"]) for row in frozen if row.get("text")}
    frozen_texts = len(seen_texts)
    seen_ids: set[str] = set()

    collected: list[dict[str, str]] = []
    for query in QUERIES:
        if len(collected) >= args.target:
            break
        collected.extend(
            select(
                search_news(api_key, query),
                exclude,
                seen_texts,
                seen_ids,
                min(args.per_query, args.target - len(collected)),
            )
        )

    rows = number(collected, next_index(frozen))
    write(rows, EXT_CSV)
    print(f"wrote {len(rows)} new snippets to {EXT_CSV}")
    print(
        f"(excluded {len(exclude)} corpus + gold + frozen-scale ids; "
        f"de-duplicated against {frozen_texts} frozen snippet texts)"
    )
    if len(rows) < args.target:
        print(
            f"\nCEILING REACHED: {len(rows)} of {args.target} requested. The 24 "
            "documented queries cannot yield more without changing the sampling frame "
            "(new queries, or a different source). Do NOT quietly add queries to hit a "
            "number -- decide whether the achieved n clears the pre-registered floor "
            "in docs/specs/global-boundary-clause-rerun.md first."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
