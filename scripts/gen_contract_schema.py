"""Generate the published /classify response contract from the live source of truth.

This project is the **provider** on the SYS-004 seam, so it owns the wire contract
and publishes it as a committed artifact that consumers assert against. The schema
is generated from ``ClassifyResponse`` plus the label constants — never hand-edited —
so it cannot describe a shape the service does not actually return.

The companion test (``tests/test_contract_schema.py``) regenerates in memory and
compares against the committed file, so changing the response model or an enum
without regenerating turns the build red here, and the consumer's build red there.

Run locally:
    uv run python scripts/gen_contract_schema.py          # rewrite the artifact
    uv run python scripts/gen_contract_schema.py --check  # exit 1 if stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from api import ClassifyResponse  # noqa: E402
from classify import CATEGORIES, DOMAINS, REGIONS  # noqa: E402

CONTRACT_PATH = REPO_ROOT / "contracts" / "classify-response.schema.json"

# Which label constant backs which response field. The generator fails loudly if a
# field appears on the model without an entry here, so a new axis cannot be added
# to the response and quietly published without its enum.
_ENUMS = {
    "category": CATEGORIES,
    "operational_domain": DOMAINS,
    "region": REGIONS,
}


def build_schema() -> dict:
    """Build the contract schema from the live response model and label constants."""
    fields = list(ClassifyResponse.model_fields)

    unmapped = [name for name in fields if name not in _ENUMS]
    if unmapped:
        raise SystemExit(
            f"ClassifyResponse has field(s) with no enum mapping in _ENUMS: "
            f"{', '.join(unmapped)}. Add the backing constant before publishing."
        )

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://raw.githubusercontent.com/sanlee-ys/defense-news-classifier/"
            "main/contracts/classify-response.schema.json"
        ),
        "title": "POST /classify — 200 response",
        "description": (
            "The frozen wire contract between defense-news-classifier (provider) "
            "and its consumers. Governed by system/SYS-004; adding, removing or "
            "renaming a field, or changing an enum's membership, is a breaking "
            "change requiring a MAJOR bump and a coordinated consumer update."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": fields,
        "properties": {
            name: {"type": "string", "enum": list(_ENUMS[name])} for name in fields
        },
    }


def main() -> int:
    """Write the contract artifact, or verify it is current under ``--check``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed artifact is current; do not write.",
    )
    args = parser.parse_args()

    schema = build_schema()
    rendered = json.dumps(schema, indent=2) + "\n"

    if args.check:
        if not CONTRACT_PATH.exists():
            print(f"MISSING: {CONTRACT_PATH}", file=sys.stderr)
            return 1
        current = CONTRACT_PATH.read_text(encoding="utf-8")
        if current != rendered:
            print(
                "STALE: the committed contract does not match the live model.\n"
                "Run: uv run python scripts/gen_contract_schema.py",
                file=sys.stderr,
            )
            return 1
        print("Contract artifact is current.")
        return 0

    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {CONTRACT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
