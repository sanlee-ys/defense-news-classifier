"""Lint this repo's ADRs for the 'Downstream surfaces' section.

Why this exists, concretely: `ADR-014` shipped the `region` axis on
2026-07-18 with no `## Downstream surfaces` section. The sweep that
followed updated `gold_eval.py` and `eval_confusion.py` and missed
`src/optimize.py`, which had not been touched since 2026-07-11 and knew
nothing about a third axis. The prompt-optimization loop was left able to
silently delete the region rubric on its next run. Nobody noticed for a day.

The architecture repo has enforced this section on its `SYS-NNN` documents
since 2026-07-18 (`architecture/scripts/lint_decision_log.py`). Repo-local
ADRs were never covered, which is how ADR-014 slipped through. This is that
check, ported.

Deliberately narrow. It does NOT try to verify that the listed surfaces are
correct or complete -- a linter cannot know that. It only enforces that the
author was made to think about it and write the list down, which is the step
that was skipped.

RATCHETED: documents in ``LEGACY_NO_DOWNSTREAM`` are grandfathered and the
list may only shrink. New ADRs must comply. This mirrors the architecture
repo's non-retroactivity stance -- fix the rule going forward rather than
backfilling fifteen documents nobody is about to re-derive.

SCANS THE ARCHIVE TOO. The 2026-08-20 restructure moved fifteen superseded
ADRs into ``decisions/archive/``. An archived ADR is still an ADR: its number
was issued and its text is unchanged, so it must stay visible to the ratchet.
A top-level-only scan reported five grandfathered numbers as "no such ADR
exists" and turned a file move into a lint failure, which is the linter
losing track of the documents rather than a real problem with them.

Usage:
    uv run python scripts/lint_decisions.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISIONS = REPO_ROOT / "decisions"
ARCHIVE = DECISIONS / "archive"

REQUIRED_SECTION = "## Downstream surfaces"

# ADRs predating the ported rule (2026-07-19). The practice lived only in the
# architecture repo until then, so an author following this repo's own
# conventions literally produced a non-compliant document -- the fault was the
# missing instruction, not these docs. Grandfathered rather than backfilled.
#
# THIS LIST MAY ONLY SHRINK. Removing an entry means that ADR grew a real
# Downstream surfaces section; adding one means the rule was weakened.
LEGACY_NO_DOWNSTREAM = {
    "001",
    "002",
    "003",
    "004",
    "005",
    "006",
    "007",
    "008",
    "009",
    "010",
    "011",
    "012",
    "013",
    "014",
}

STATUS = re.compile(r"^\*\*Status:\*\*\s*(.+)$", re.MULTILINE)


def adr_files() -> list[Path]:
    """Every numbered ADR, live or archived, sorted by number.

    Both directories are scanned. ``decisions/`` holds the ADRs still in
    force; ``decisions/archive/`` holds the superseded ones, whose numbers
    were still issued and whose text is unchanged.
    """
    found = list(DECISIONS.glob("[0-9][0-9][0-9]-*.md"))
    found += list(ARCHIVE.glob("[0-9][0-9][0-9]-*.md"))
    return sorted(found, key=lambda path: path.name)


def adr_rel(path: Path) -> str:
    """Repo-relative path, so a message points at the file that actually moved."""
    return path.relative_to(REPO_ROOT).as_posix()


def adr_id(path: Path) -> str:
    """'014' from '014-region-field-design.md'."""
    return path.name.split("-", 1)[0]


def lint() -> list[str]:
    """Run the checks. Returns human-readable problems, empty if clean."""
    problems: list[str] = []
    seen: set[str] = set()

    for path in adr_files():
        num = adr_id(path)
        rel = adr_rel(path)
        text = path.read_text(encoding="utf-8")

        if num in seen:
            problems.append(f"{rel}: duplicate ADR number {num}.")
        seen.add(num)

        if not STATUS.search(text):
            problems.append(f"{rel}: no '**Status:**' header.")

        if REQUIRED_SECTION not in text and num not in LEGACY_NO_DOWNSTREAM:
            problems.append(
                f"{rel}: missing '{REQUIRED_SECTION}'. Every new ADR must list the "
                f"code, docs, and other decisions its change touches. ADR-014 "
                f"shipped without one and the sweep missed src/optimize.py, "
                f"leaving the loop able to delete the region rubric."
            )

    # The grandfather list may only shrink: an entry naming an ADR that does not
    # exist means someone edited the list instead of the document.
    for num in sorted(LEGACY_NO_DOWNSTREAM - seen):
        problems.append(
            f"LEGACY_NO_DOWNSTREAM names {num}, but no such ADR exists. "
            f"The list may only shrink, and only by an ADR gaining a real section."
        )

    # An entry that now HAS the section should be removed from the list, or the
    # ratchet silently stops ratcheting.
    for path in adr_files():
        num = adr_id(path)
        if num in LEGACY_NO_DOWNSTREAM:
            text = path.read_text(encoding="utf-8")
            if REQUIRED_SECTION in text:
                problems.append(
                    f"{adr_rel(path)} has '{REQUIRED_SECTION}' but is still "
                    f"grandfathered in LEGACY_NO_DOWNSTREAM. Remove {num} from the "
                    f"list so the ratchet keeps its meaning."
                )

    return problems


def main() -> int:
    """Lint the decisions; exit 1 on any problem."""
    problems = lint()
    if problems:
        # ASCII only: this runs on a Windows console (cp1252) as well as in CI.
        print("DECISION LINT - problems found:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        return 1

    total = len(adr_files())
    grandfathered = len(LEGACY_NO_DOWNSTREAM)
    archived = len(list(ARCHIVE.glob("[0-9][0-9][0-9]-*.md")))
    print(
        f"OK - decisions clean. {total} ADRs ({total - archived} live, {archived} "
        f"archived), {grandfathered} grandfathered out of the "
        f"'{REQUIRED_SECTION}' rule, {total - grandfathered} enforced."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
