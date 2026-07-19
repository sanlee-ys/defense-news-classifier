"""Generate the README's headline metrics table from the published artifact.

WHY GENERATE RATHER THAN CHECK. Every other surface quoting these numbers now
*asserts* against ``evals/metrics.json`` — the portfolio site, the architecture repo's
program view. This README is different: it lives in the same repo as the artifact, so
it does not need to check a copy. It can have no copy at all.

That is `architecture/ADR-002`'s argument, and it is strictly stronger than a checker:
a generated table "cannot drift from reality because it has no state of its own to
drift." A checked number is still wrong in the window between a careless edit and the
next CI run. A generated one is never wrong, because it was never typed.

The irony this closes: this repo *produces* the artifact every other surface is
verified against, and its own README — the project's most-read page, whose whole stated
job is to "lead with the numbers" — was the last place still holding hand-typed copies
of them.

WHAT IS GENERATED, AND WHAT IS DELIBERATELY NOT. Only the current three-axis gold table
between the BEGIN/END markers. The historical tables further down (the v1 synthetic
baseline, the v2.0 Sonnet-4-6 record, the routing comparison) are **frozen records of
past runs** and must never track the latest artifact — regenerating them would rewrite
history to match today, which is the failure `SYS-001`'s retroactivity rule exists to
prevent.

Run locally:
    uv run python scripts/gen_readme_metrics.py          # rewrite the block
    uv run python scripts/gen_readme_metrics.py --check  # exit 1 if stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
ARTIFACT_PATH = REPO_ROOT / "evals" / "metrics.json"

BEGIN = "<!-- BEGIN GENERATED: gold-metrics (scripts/gen_readme_metrics.py) -->"
END = "<!-- END GENERATED: gold-metrics -->"

# Rows in display order: (label, accuracy key, macro-F1 key, judge-agreement key).
# Listing the keys explicitly rather than deriving them from the artifact is deliberate:
# a new axis should require a conscious edit here, not silently appear in the headline
# table of the project's front page.
ROWS = (
    ("Category", "category_accuracy", "category_macro_f1", "judge_category_agreement"),
    (
        "Operational domain",
        "domain_accuracy",
        "domain_macro_f1",
        "judge_domain_agreement",
    ),
    ("Region", "region_accuracy", "region_macro_f1", "judge_region_agreement"),
)

# Region macro-F1 carries a footnote about support limits (`europe` n=1, `africa` n=2).
# The marker has to survive regeneration or the caveat silently disappears the first
# time this script runs — a generated table that drops a caveat is worse than a stale
# one, because it reads as cleaner than the data supports.
FOOTNOTED = {"region_macro_f1": "*"}


# Accuracies are bolded (the headline figure), macro-F1 is not. Judge agreement is
# bolded only at 100.0%, matching how the surrounding prose treats it as the gate for
# the scaled region eval.
def _cell(value: object, key: str, bold: bool) -> str:
    """Render one table cell, preserving the footnote marker and bolding rules."""
    text = f"{value}%" if key.endswith(("accuracy", "agreement")) else f"{value}"
    text = f"**{text}**" if bold else text
    return text + FOOTNOTED.get(key, "")


def render(artifact: dict) -> str:
    """Build the generated block from the artifact."""
    gold = artifact["gold"]
    lines = [
        BEGIN,
        "",
        "| Axis | Accuracy | Macro-F1 | Judge vs human |",
        "|---|---|---|---|",
    ]
    for label, acc, f1, judge in ROWS:
        for key in (acc, f1, judge):
            if key not in gold:
                raise KeyError(
                    f"{key} is missing from {ARTIFACT_PATH.name}. Regenerate the "
                    f"artifact first (scripts/gen_metrics_artifact.py) - this script "
                    f"renders it, it does not compute it."
                )
        lines.append(
            f"| {label} "
            f"| {_cell(gold[acc], acc, bold=True)} "
            f"| {_cell(gold[f1], f1, bold=False)} "
            f"| {_cell(gold[judge], judge, bold=gold[judge] == 100.0)} |"
        )
    lines += ["", END]
    return "\n".join(lines)


def splice(text: str, block: str) -> str:
    """Replace the marked block in the README, leaving everything else untouched."""
    start = text.find(BEGIN)
    end = text.find(END)
    if start == -1 or end == -1:
        raise SystemExit(
            f"Could not find the generated-block markers in {README_PATH.name}. "
            f"Expected:\n  {BEGIN}\n  ...\n  {END}\n"
            f"Without them this script does not know what it owns, and rewriting the "
            f"whole file would clobber the historical tables it must never touch."
        )
    if end < start:
        raise SystemExit(
            "The END marker appears before the BEGIN marker in the README."
        )
    return text[:start] + block + text[end + len(END) :]


def main() -> int:
    """Regenerate the block, or verify it is current."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Exit 1 if the block is stale."
    )
    args = parser.parse_args()

    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    current = README_PATH.read_text(encoding="utf-8")
    updated = splice(current, render(artifact))

    if args.check:
        if updated != current:
            print(
                "README metrics table is STALE.\n\n"
                "  The table does not match evals/metrics.json. Run:\n"
                "      uv run python scripts/gen_readme_metrics.py\n"
                "  and commit the result. Do not hand-edit the block - the next run "
                "overwrites it.",
                file=sys.stderr,
            )
            return 1
        print(
            f"OK - README metrics table matches the artifact (v{artifact['version']})."
        )
        return 0

    if updated == current:
        print("README metrics table already current; nothing to do.")
        return 0

    README_PATH.write_text(updated, encoding="utf-8")
    print(f"Wrote the README metrics table from the artifact (v{artifact['version']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
