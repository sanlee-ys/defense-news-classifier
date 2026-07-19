"""The published /classify contract must match what the service actually returns.

This project is the **provider** on the SYS-004 seam and owns the wire contract.
``contracts/classify-response.schema.json`` is the artifact consumers assert
against, so it has exactly one job: never describe a shape this service does not
return.

Why this file exists at all. Before it, both sides of the seam had "contract
tests" that asserted each implementation against its *own* copy of the shape. When
``region`` shipped in v3.0.0, the provider's fixture was updated in the same commit
and the consumer's stub was not — and both suites stayed green through a breaking
change. These tests close the provider half: the committed artifact is regenerated
in memory and compared, so changing the response model or a label constant without
regenerating turns this build red, and the stale artifact can never reach a
consumer.

No JSON Schema validator is needed. The schema's entire content is the field set
plus the enums, both of which are compared directly against their sources.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from gen_contract_schema import CONTRACT_PATH, build_schema  # noqa: E402

from api import ClassifyResponse  # noqa: E402
from classify import CATEGORIES, DOMAINS, REGIONS  # noqa: E402


def _committed() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_committed_artifact_exists():
    assert CONTRACT_PATH.exists(), (
        f"{CONTRACT_PATH} is missing. Consumers fetch this file; without it the "
        "seam has no guard. Run: uv run python scripts/gen_contract_schema.py"
    )


def test_committed_artifact_is_not_stale():
    """The committed file must equal a fresh generation, byte for byte.

    This is the tripwire SYS-004 claimed to have and did not: edit the response
    model or a label constant, forget to regenerate, and this fails.
    """
    rendered = json.dumps(build_schema(), indent=2) + "\n"
    assert CONTRACT_PATH.read_text(encoding="utf-8") == rendered, (
        "The committed contract is stale relative to the live model.\n"
        "Run: uv run python scripts/gen_contract_schema.py"
    )


def test_required_fields_match_the_response_model():
    """Adding or removing a response field must move the contract with it."""
    assert _committed()["required"] == list(ClassifyResponse.model_fields)


def test_enums_match_the_label_constants():
    """A changed label set is a breaking change; the artifact must carry it."""
    props = _committed()["properties"]
    assert props["category"]["enum"] == CATEGORIES
    assert props["operational_domain"]["enum"] == DOMAINS
    assert props["region"]["enum"] == REGIONS


def test_contract_is_closed():
    """`additionalProperties: false` is what makes an added field a breaking change.

    Without this, a consumer validating against the schema would silently accept a
    new field, which is precisely how the `region` drift went unnoticed.
    """
    assert _committed()["additionalProperties"] is False


def test_generator_rejects_a_field_with_no_enum_mapping(monkeypatch):
    """A new response field cannot be published without its backing label set.

    Guards the failure mode where a fourth axis is added to ClassifyResponse and
    the contract silently describes it as an unconstrained string.
    """
    import gen_contract_schema as gen

    monkeypatch.setattr(
        gen.ClassifyResponse,
        "model_fields",
        {**ClassifyResponse.model_fields, "confidence": None},
    )
    try:
        gen.build_schema()
    except SystemExit as exc:
        assert "confidence" in str(exc)
    else:  # pragma: no cover - the guard is the point
        raise AssertionError("build_schema() accepted a field with no enum mapping")
