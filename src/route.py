"""v2.2.0 tiered routing: escalate technology-vs-operations boundary cases to Opus.

The workhorse forces tool use, so it emits no confidence signal a router could act on.
This module manufactures one: a routing variant of the classify tool adds a required
``runner_up_category`` field ("the label you most nearly chose instead, or none"), and
the router escalates to the premium model exactly when the workhorse reports the
{technology, operations} pair as its top-two -- the one clustered confusion the real
gold set showed (ADR-011). Everything else keeps the workhorse's answer.

The public contract is unchanged: ``classify_routed()`` returns the same
``{category, operational_domain}`` dict as ``classify()``. The runner-up field lives
only on the routing wire; callers never see it.

This shipped as an EXPERIMENT with a stated hypothesis: the PR #79 prompt fix already
cleared the tech->ops cluster on the human-graded gold set, so routing likely no longer
pays. ``src/route_eval.py`` measured that verdict, and it held -- routing moved +0 rows
on both gold axes at ~1.97x the cost (evals/route_eval.txt). Tiered routing is DECLINED
(decisions/013-decline-tiered-routing.md): nothing in the shipped path imports this
module; it stays dormant, with its tests, as the reproducible record.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import cast

import anthropic
from anthropic.types import TextBlockParam, ToolParam, ToolUseBlock

from classify import (
    CATEGORIES,
    CLASSIFY_TOOL,
    MODEL,
    OUTPUT_CONFIG,
    SYSTEM_PROMPT,
    InvalidLabelError,
    _raise_if_refusal,
    _validate,
    classify,
)

# The premium tier escalated cases are re-classified on. Same model (and, via
# classify(), the same prompt + schema) as the gold-eval judge -- deliberately, so a
# stored judge prediction IS what an escalation would have produced, and the eval
# harness can replay routing offline without new Opus spend.
ESCALATION_MODEL = "claude-opus-4-8"

# The boundary the router watches: escalate iff the workhorse's top-two categories are
# exactly this pair, in either order (ADR-011's re-aimed target).
ESCALATION_PAIR = frozenset({"technology", "operations"})

# "none" = no other category was seriously in contention (the clear-cut case).
RUNNER_UP_NONE = "none"
RUNNER_UP_VALUES = [*CATEGORIES, RUNNER_UP_NONE]

# The routing tool: CLASSIFY_TOOL plus the required runner_up_category field. Built by
# deep-copying the shipped tool so the two schemas can never drift on the shared fields.
ROUTE_TOOL: ToolParam = copy.deepcopy(CLASSIFY_TOOL)
_schema = cast(dict, ROUTE_TOOL["input_schema"])
_schema["properties"]["runner_up_category"] = {
    "type": "string",
    "enum": RUNNER_UP_VALUES,
    "description": (
        "The category you most nearly chose instead of `category`, or `none` if no "
        "other category was seriously in contention."
    ),
}
_schema["required"].append("runner_up_category")
del _schema

# Appended to SYSTEM_PROMPT for the routing call only. The shipped prompt is untouched;
# this rides after it so the cacheable prefix stays a superset of the shipped one.
ROUTE_PROMPT_SUFFIX = """

Additionally, report `runner_up_category`: the single category you most nearly chose \
instead of your answer, or `none` if no other category was seriously in contention. \
Be honest about close calls -- naming a runner-up does not weaken your answer."""

ROUTE_SYSTEM_PROMPT = SYSTEM_PROMPT + ROUTE_PROMPT_SUFFIX


@dataclass
class RouteResult:
    """One routed classification, with the routing decision kept legible.

    ``category`` / ``operational_domain`` are the final answer (the escalation's if it
    fired, the workhorse's otherwise) -- the same contract classify() returns.
    ``workhorse`` preserves the workhorse's own labels either way, and
    ``runner_up_category`` is the signal the decision was made on, so the eval can
    report exactly which snippets flagged themselves as on the boundary.
    """

    category: str
    operational_domain: str
    escalated: bool
    runner_up_category: str
    workhorse: dict


def _validate_runner_up(result: dict) -> dict:
    """Validate a routing-call result, normalizing a degenerate runner-up.

    Args:
        result: The routing tool_use input: ``category``, ``operational_domain``,
            ``runner_up_category``.

    Returns:
        ``result`` with the base fields validated by classify's ``_validate`` and a
        runner-up equal to the chosen category normalized to ``none`` (a label cannot
        be its own runner-up; strict mode can enforce the enum but not inequality).

    Raises:
        InvalidLabelError: If any field falls outside its allowed set.
    """
    _validate(result)
    runner_up = result.get("runner_up_category")
    if runner_up not in RUNNER_UP_VALUES:
        raise InvalidLabelError(
            f"runner_up_category {runner_up!r} is not one of {RUNNER_UP_VALUES}"
        )
    if runner_up == result["category"]:
        result["runner_up_category"] = RUNNER_UP_NONE
    return result


def classify_with_runner_up(
    client: anthropic.Anthropic, text: str, model: str = MODEL
) -> dict:
    """The workhorse call with the routing schema: labels plus a runner-up signal.

    Mirrors classify()'s call shape exactly (forced strict tool use, cache_control on
    the system block, the effort hint) with two substitutions: ROUTE_TOOL for the tool
    and ROUTE_SYSTEM_PROMPT for the prompt.

    Args:
        client: Authenticated Anthropic client.
        text: Raw article snippet to classify.
        model: Which Claude model classifies. Defaults to the workhorse.

    Returns:
        Dict with ``category``, ``operational_domain``, and ``runner_up_category``.

    Raises:
        ClassificationRefusalError: If the model declined the request.
        InvalidLabelError: If a label falls outside its allowed set despite strict mode.
    """
    system_block: TextBlockParam = {
        "type": "text",
        "text": ROUTE_SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }
    response = client.messages.create(
        model=model,
        max_tokens=256,
        system=[system_block],
        tools=[ROUTE_TOOL],
        tool_choice={"type": "tool", "name": "classify_article"},
        messages=[{"role": "user", "content": text}],
        output_config=OUTPUT_CONFIG,
    )
    _raise_if_refusal(response)
    tool_block = next(b for b in response.content if isinstance(b, ToolUseBlock))
    return _validate_runner_up(cast(dict, tool_block.input))


def should_escalate(result: dict) -> bool:
    """True iff the workhorse's top-two categories are the escalation pair.

    Args:
        result: A ``classify_with_runner_up`` result.

    Returns:
        Whether the router should re-classify on the premium model: the chosen
        category and the runner-up are exactly {technology, operations}, in either
        order. A runner-up of ``none`` (or any other pair) never escalates.
    """
    pair = {result["category"], result["runner_up_category"]}
    return pair == set(ESCALATION_PAIR)


def route(
    client: anthropic.Anthropic,
    text: str,
    escalation_model: str = ESCALATION_MODEL,
) -> RouteResult:
    """Classify with tiered routing, keeping the decision trail.

    One workhorse call with the runner-up schema; iff the top-two categories are the
    tech/ops pair, one more call to the premium model (classify()'s exact shipped call
    shape -- same prompt, same schema) whose answer wins outright.

    Args:
        client: Authenticated Anthropic client.
        text: Raw article snippet to classify.
        escalation_model: Premium model for escalated cases. Defaults to the Opus
            judge tier.

    Returns:
        A RouteResult: the final labels, whether escalation fired, the runner-up
        signal, and the workhorse's own labels.
    """
    base = classify_with_runner_up(client, text)
    workhorse = {
        "category": base["category"],
        "operational_domain": base["operational_domain"],
    }
    if not should_escalate(base):
        return RouteResult(
            category=base["category"],
            operational_domain=base["operational_domain"],
            escalated=False,
            runner_up_category=base["runner_up_category"],
            workhorse=workhorse,
        )
    escalated = classify(client, text, model=escalation_model)
    return RouteResult(
        category=escalated["category"],
        operational_domain=escalated["operational_domain"],
        escalated=True,
        runner_up_category=base["runner_up_category"],
        workhorse=workhorse,
    )


def classify_routed(client: anthropic.Anthropic, text: str) -> dict:
    """Drop-in classify() with tiered routing -- the same output contract.

    Args:
        client: Authenticated Anthropic client.
        text: Raw article snippet to classify.

    Returns:
        Dict with keys ``category`` and ``operational_domain``, both str -- identical
        shape to classify()'s return value. Callers never see the routing metadata;
        use route() when the decision trail matters.
    """
    result = route(client, text)
    return {
        "category": result.category,
        "operational_domain": result.operational_domain,
    }
