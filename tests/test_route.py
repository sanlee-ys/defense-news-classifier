"""Tests for src/route.py (v2.2.0 tiered routing). Offline only."""

import pytest

import classify
import route

# ---------------------------------------------------------------------------
# Schema and prompt construction
# ---------------------------------------------------------------------------


def test_route_tool_extends_the_shipped_schema():
    schema = route.ROUTE_TOOL["input_schema"]
    assert route.ROUTE_TOOL["strict"] is True
    assert schema["properties"]["runner_up_category"]["enum"] == route.RUNNER_UP_VALUES
    assert "runner_up_category" in schema["required"]
    # The shared fields are the shipped ones, verbatim.
    for field in ("category", "operational_domain"):
        assert (
            schema["properties"][field]
            == classify.CLASSIFY_TOOL["input_schema"]["properties"][field]
        )


def test_route_tool_does_not_mutate_the_shipped_tool():
    """ROUTE_TOOL is a deep copy -- the shipped classifier schema must be untouched."""
    shipped = classify.CLASSIFY_TOOL["input_schema"]
    assert "runner_up_category" not in shipped["properties"]
    assert shipped["required"] == ["category", "operational_domain"]


def test_route_prompt_is_a_superset_of_the_shipped_prompt():
    assert route.ROUTE_SYSTEM_PROMPT.startswith(classify.SYSTEM_PROMPT)
    assert "runner_up_category" in route.ROUTE_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_runner_up_accepts_a_valid_result():
    result = {
        "category": "technology",
        "operational_domain": "air",
        "runner_up_category": "operations",
    }
    assert route._validate_runner_up(dict(result)) == result


def test_validate_runner_up_rejects_an_out_of_enum_runner_up():
    with pytest.raises(classify.InvalidLabelError, match="runner_up_category"):
        route._validate_runner_up(
            {
                "category": "technology",
                "operational_domain": "air",
                "runner_up_category": "sports",
            }
        )


def test_validate_runner_up_normalizes_a_self_runner_up_to_none():
    result = route._validate_runner_up(
        {
            "category": "technology",
            "operational_domain": "air",
            "runner_up_category": "technology",
        }
    )
    assert result["runner_up_category"] == route.RUNNER_UP_NONE


# ---------------------------------------------------------------------------
# The workhorse routing call
# ---------------------------------------------------------------------------


def test_classify_with_runner_up_uses_the_routing_schema_and_prompt(tool_client):
    client = tool_client(
        {
            "category": "operations",
            "operational_domain": "sea",
            "runner_up_category": "none",
        }
    )
    result = route.classify_with_runner_up(client, "destroyers transit strait")
    assert result["runner_up_category"] == "none"
    kwargs = client.messages.last_kwargs
    assert kwargs["tools"] == [route.ROUTE_TOOL]
    assert kwargs["system"][0]["text"] == route.ROUTE_SYSTEM_PROMPT
    assert kwargs["model"] == classify.MODEL


def test_classify_with_runner_up_raises_on_refusal(refusal_client):
    with pytest.raises(classify.ClassificationRefusalError):
        route.classify_with_runner_up(refusal_client(category="x"), "text")


# ---------------------------------------------------------------------------
# The escalation decision
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("category", "runner_up", "expected"),
    [
        ("technology", "operations", True),
        ("operations", "technology", True),  # either order
        ("technology", "none", False),
        ("technology", "procurement", False),
        ("industry", "procurement", False),
        ("operations", "none", False),
    ],
)
def test_should_escalate_fires_only_on_the_tech_ops_pair(category, runner_up, expected):
    result = {
        "category": category,
        "operational_domain": "air",
        "runner_up_category": runner_up,
    }
    assert route.should_escalate(result) is expected


# ---------------------------------------------------------------------------
# route() / classify_routed()
# ---------------------------------------------------------------------------


def test_route_keeps_the_workhorse_answer_when_no_escalation(tool_client):
    client = tool_client(
        {
            "category": "policy",
            "operational_domain": "multi",
            "runner_up_category": "none",
        }
    )
    result = route.route(client, "new defense strategy")
    assert not result.escalated
    assert (result.category, result.operational_domain) == ("policy", "multi")
    assert result.workhorse == {"category": "policy", "operational_domain": "multi"}


def test_route_escalates_the_tech_ops_boundary_to_the_premium_model(tool_client_seq):
    client = tool_client_seq(
        [
            {  # workhorse: on the boundary
                "category": "technology",
                "operational_domain": "air",
                "runner_up_category": "operations",
            },
            {  # escalation answer wins outright
                "category": "operations",
                "operational_domain": "land",
            },
        ]
    )
    result = route.route(client, "unit field-tests prototype during exercise")
    assert result.escalated
    assert (result.category, result.operational_domain) == ("operations", "land")
    assert result.workhorse == {"category": "technology", "operational_domain": "air"}
    assert result.runner_up_category == "operations"
    # The second (escalation) call ran classify()'s shipped shape on the premium tier.
    kwargs = client.messages.last_kwargs
    assert client.messages.calls == 2
    assert kwargs["model"] == route.ESCALATION_MODEL
    assert kwargs["tools"] == [classify.CLASSIFY_TOOL]
    assert kwargs["system"][0]["text"] == classify.SYSTEM_PROMPT


def test_classify_routed_returns_the_shipped_contract_only(tool_client):
    client = tool_client(
        {
            "category": "procurement",
            "operational_domain": "space",
            "runner_up_category": "industry",
        }
    )
    result = route.classify_routed(client, "satellite contract awarded")
    assert result == {"category": "procurement", "operational_domain": "space"}
