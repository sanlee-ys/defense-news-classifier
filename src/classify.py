"""Classifier: maps article text -> {category, operational_domain, region}.

Single LLM call with forced tool use for structured output.
Usable as a module (import classify) or as a CLI tool.
"""

import json
import os
import sys
from typing import Literal, cast

import anthropic
from anthropic.types import (
    OutputConfigParam,
    SearchResultBlockParam,
    TextBlockParam,
    ToolParam,
    ToolUseBlock,
)
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from telemetry import get_tracer, set_usage_attributes, setup_tracing

# The user-message content classify() accepts: either a plain article string, or a
# list of content blocks (used by the RAG layer to present retrieved passages as
# first-class ``search_result`` blocks so the API attaches source/title citations).
UserContent = str | list[TextBlockParam | SearchResultBlockParam]

CATEGORIES = ["procurement", "operations", "policy", "technology", "industry"]
DOMAINS = ["air", "land", "sea", "cyber", "space", "multi"]
# v3.0.0 axis (decisions/014): the geographic theater of the story's subject
# activity. `global` is the single catch-all for both no-anchor and
# multi-region stories, mirroring how `multi` works on the domain axis.
REGIONS = ["indo-pacific", "europe", "middle-east", "africa", "americas", "global"]
MODEL = "claude-sonnet-5"

# Effort hint sent on every classify call via output_config. On Sonnet 5 (and the
# Opus judge) `output_config.effort` is the replacement lever for the removed manual
# thinking budget: it caps how much the model thinks before answering. "low" is right
# for this task -- a single forced-tool structured classification has nothing to reason
# through, and strict:true already guarantees a schema-valid answer.
#
# Measured caveat (see the migration report): because classify() FORCES tool use
# (tool_choice={"type":"tool",...}), the model must emit the tool immediately and never
# thinks -- so on the current call shape `effort` is provably a no-op (identical tokens
# and labels at low / high / adaptive / disabled). It is set explicitly anyway so the
# call stays cheap-by-default if tool_choice is ever relaxed (e.g. a reasoning variant),
# and so the intent is on the wire rather than left to Sonnet 5's adaptive-on-by-default.
EFFORT: Literal["low", "medium", "high", "xhigh", "max"] = "low"
OUTPUT_CONFIG: OutputConfigParam = {"effort": EFFORT}

# System prompt gives Claude the label definitions so it applies them consistently.
# Without this, the model has to infer what "procurement" vs "industry" means from
# the label name alone, which introduces unnecessary ambiguity.
SYSTEM_PROMPT = """You are a defense-news analyst. Given a defense-related article snippet, \
classify it into exactly one category, one operational domain, and one region.

Categories:
- procurement: contracts, acquisitions, budgets, program awards
- operations: active conflict, deployments, military operations
- policy: legislation, treaties, strategy, doctrine
- technology: R&D, new systems, autonomous/drone/AI developments
- industry: defense-company business, earnings, mergers

Operational domains:
- air: aircraft, missiles, UAVs, aerospace operations
- land: ground forces, armored vehicles, infantry operations
- sea: naval vessels, submarines, maritime operations
- cyber: information warfare, network attacks, electronic warfare
- space: satellites, launch systems, space operations
- multi: joint/combined operations spanning more than one domain

Regions (the geographic theater of the story's subject activity):
- indo-pacific: East, South, and Southeast Asia, Oceania, and the Pacific
- europe: Europe, including Russia and the Ukraine conflict theater
- middle-east: the Gulf, the Levant, Iran, Iraq, and the Arabian Peninsula
- africa: the African continent and adjacent waters
- americas: North, Central, and South America, including the continental United States
- global: no identifiable regional anchor, or the story genuinely spans multiple regions

Pick the single best label for each field. If the article spans two categories or domains, \
choose the one that is most prominent.

Extended rubric -- apply these conventions when labels overlap:

Category boundaries:
- procurement vs industry: a purchase, contract award, or program decision is the BUYER'S \
story -- label it procurement, even when the winning company is named in the headline. Label \
industry only when the story is the company's own business (earnings, mergers and \
acquisitions, stock moves, workforce or corporate strategy) with no government purchase at \
its center.
- procurement vs technology: a contract to buy, develop, or field a system is procurement; \
the system itself -- its capabilities, tests, demonstrations, R&D milestones -- is \
technology. If the money event is the story, choose procurement; if the machine is the \
story, choose technology.
- policy is the rule, not the doing: label policy only when the story is about a policy, \
strategy, treaty, piece of legislation, doctrine, or formal rule ITSELF (its creation, \
change, review, or articulation). A unit or official implementing, exercising, or merely \
name-dropping a policy or strategy document is doing an action -- usually operations. A \
snippet can mention a strategy review and still be operations if it is really about \
carrying it out.
- operations vs technology: the first combat or exercise use of a new system is operations \
when the story is the engagement or deployment, technology when the story is what the \
system proved it can do. A system being built, tested, prototyped, or demonstrated is \
technology even when an operational unit does the work or it happens during an exercise -- \
the operational setting does not override that the system or capability is the subject. \
Reserve operations for when the unit's activity itself (a deployment, a drill, an \
engagement) is the story, with no new system at its center.
- industry vs technology: a company unveiling or developing a system is technology when the \
capability is the point, industry when the business result (revenue, market position, a \
merger) is the point.
- budget boundary: debate over or passage of budget legislation is policy (the rule being \
made); an executed award or program decision spending an existing budget is procurement.

Domain boundaries:
- cyber vs the host platform: electronic warfare, network attack or defense, and \
information-warfare capabilities are cyber even when mounted on a tank, ship, or aircraft. \
If the cyber/EW capability is the subject, label cyber; if the platform is the subject and \
the EW kit is a supporting detail, label the platform's domain.
- air vs space: aircraft, UAVs, helicopters, and missiles operating inside the atmosphere \
are air; satellites, launch vehicles, ground-based space-surveillance, and orbital systems \
are space.
- uncrewed systems go by operating medium: aerial drones/UAVs are air, uncrewed surface or \
undersea vessels are sea, ground robots are land.
- carrier and amphibious stories: the ship or fleet as subject is sea; the embarked air \
wing's flying operations as subject is air.
- multi is for genuinely joint stories: use multi only when the story itself spans domains \
(a joint exercise, a cross-domain program, a service-wide strategy). Do not use multi just \
because a second domain gets a passing mention -- pick the dominant one.
- air action over a ground setting is still air: an airstrike, close-air-support mission, or \
air-and-missile-defense story is air (the aircraft or missile is the actor), even when \
ground forces or ground targets are present. Do not default to land just because the \
setting is on the ground; use multi only when a ground engagement genuinely shares the \
story's center of gravity with the air action.

Region rules:
- Label the theater where the story's subject activity happens or is aimed, not the \
actor's nationality: a US carrier operating in the South China Sea is indo-pacific; a \
Ukraine aid debate in Washington is europe.
- Use only what the snippet states or unambiguously implies (a named base, city, sea, or \
country). Do not guess a region from world knowledge when the text names no place: an \
unnamed "contested strait" is global.
- A concrete identifiable location makes an anchor even at home: training at a named US \
base or waters off a named US coast is americas. No-anchor means the story has no \
meaningful geography at all -- a budget line, a doctrine change, an enterprise-wide \
program -- not "the geography is the United States".
- Two or more theaters with none dominant is global -- the same test as multi on the \
domain axis. Pick a single region only when the story is primarily about that theater.
- Orbital/space and cyberspace stories with no terrestrial theater in view are global.

Worked examples:
- "Army awards $1.2B contract for next-generation ground vehicles" -> procurement / land / global
- "Contractor reports quarterly earnings up 8 percent on strong missile demand" -> industry / air / global
- "Destroyers conduct freedom-of-navigation transit through contested strait" -> operations / sea / global
- "New national defense strategy elevates deterrence across theaters" -> policy / multi / global
- "Startup demonstrates autonomous drone swarm for contested resupply" -> technology / air / global
- "Two defense primes announce merger to consolidate satellite manufacturing" -> industry / space / global
- "Air Force awards development contract for counter-drone electronic-warfare pod" -> procurement / cyber / global
- "Cyber command runs defensive operations against intrusions into logistics networks" -> operations / cyber / global
- "Congress passes authorization act setting shipbuilding budget levels" -> policy / sea / global
- "Soldiers field-test powered exoskeleton during live-fire exercise" -> technology / land / global
- "Navy commissions new attack submarine after sea trials" -> operations / sea / global
- "Pentagon budget request prioritizes munitions restocking over platform buys" -> policy / multi / global
- "Prime contractor selected to build next missile-warning satellite constellation" -> procurement / space / global
- "Battalion completes rotation at combat training center under new doctrine" -> operations / land / global
- "Lab unveils jam-resistant navigation system for GPS-denied environments" -> technology / cyber / global
- "Shipbuilder stock surges after analysts raise defense-spending outlook" -> industry / sea / global
- "Squadron stands up test track to put a new hypersonic sled through its paces" -> technology / air / global
- "Prototype uncrewed surface vessels join a fleet exercise to prove autonomous resupply" -> technology / sea / global
- "Coalition aircraft conduct airstrike on insurgent position during ground firefight" -> operations / multi / global
- "Carrier strike group drills with allied navies in the South China Sea" -> operations / sea / indo-pacific
- "Fighter squadrons rotate to bases on NATO's eastern flank amid heightened tensions" -> operations / air / europe
- "Naval coalition escorts commercial tankers through the Strait of Hormuz" -> operations / sea / middle-east
- "Peacekeepers expand counterinsurgency patrols across the Sahel" -> operations / land / africa
- "Destroyer completes builder's sea trials off the coast of Maine" -> operations / sea / americas
- "Allied cyber commands on three continents run a joint defensive exercise" -> operations / cyber / global

Note the pattern in the examples: a snippet earns a specific region only when it names an \
identifiable place; everything else -- however strongly world knowledge suggests a theater \
-- is global.

Tie-breaking, in order: (1) weigh the headline and lead sentence most heavily; (2) identify \
the story's center of gravity -- the money event (procurement), the action (operations), \
the rule (policy), the machine (technology), or the business result (industry) -- and label \
that; (3) if two domains genuinely share the center of gravity, only then use multi; (4) for \
region, ask where the subject activity happens or is aimed -- if the snippet names no \
identifiable place, or the story spans regions, use global."""

CLASSIFY_TOOL: ToolParam = {
    "name": "classify_article",
    "description": (
        "Return the category, operational domain, and region for a defense-news snippet."
    ),
    # strict=true turns on server-side constrained decoding: the API guarantees
    # tool_use.input validates against input_schema, including enum membership,
    # before the response is ever returned to us. See decisions/008 for why this
    # replaces the client-side re-sample-on-invalid-label loop that used to live
    # in classify() below (ADR-002 predates strict mode, which wasn't available
    # then). Strict mode requires additionalProperties: false alongside required.
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": CATEGORIES,
                "description": "The primary topic of the article.",
            },
            "operational_domain": {
                "type": "string",
                "enum": DOMAINS,
                "description": "The warfighting domain the article relates to.",
            },
            "region": {
                "type": "string",
                "enum": REGIONS,
                "description": (
                    "The geographic theater of the story's subject activity; "
                    "global when no place is identified or the story spans regions."
                ),
            },
        },
        "required": ["category", "operational_domain", "region"],
        "additionalProperties": False,
    },
}


class InvalidLabelError(ValueError):
    """Raised when the model returns a label outside the allowed enum.

    Kept as a defensive backstop, not the primary guard it was before strict
    mode: with ``strict: true`` on CLASSIFY_TOOL, the API's constrained
    decoding enforces the schema (including these enums) server-side before
    the response is ever returned, so an out-of-enum ``tool_use.input`` should
    no longer occur in practice. ``classify()`` still validates and raises
    this rather than silently trusting the wire, in case that guarantee is
    ever violated (e.g. an API regression) -- but it no longer re-samples on
    failure, since there is nothing left for a re-sample to routinely fix.
    """


class ClassificationRefusalError(RuntimeError):
    """Raised when the model declines to classify (``stop_reason == "refusal"``).

    A safety-classifier refusal comes back as a *successful* HTTP 200 with
    ``stop_reason == "refusal"`` and an empty (or tool_use-less) ``content``
    list -- not as an SDK exception. So nothing upstream raises, and the
    forced-tool-use contract this classifier relies on is silently broken: the
    ``next(... ToolUseBlock ...)`` extraction in ``classify()`` /
    ``parse_batch_result`` would otherwise blow up with a bare, contextless
    ``StopIteration``. This turns that into a clear, named error that says a
    refusal happened and (when present) why.

    Distinct from both ``InvalidLabelError`` (the model answered, but with an
    out-of-enum label -- a validation problem) and ``BatchItemError`` (the
    batch transport failed the item). A refusal is the model's safety layer
    declining the request itself, an operational outcome neither of those
    covers, hence a separate ``RuntimeError`` subclass callers can catch on its
    own.

    The workhorse is now ``claude-sonnet-5`` -- the first Sonnet-tier model with
    real-time cyber safeguards -- so this branch is load-bearing, not just
    defensive: a false-positive decline on defense-domain text is a real (if
    rare) possibility here, and this guard keeps such a decline legible instead
    of surfacing as a confusing ``StopIteration`` deep in result parsing. (The
    Opus judge, ``claude-opus-4-8``, also carries these safeguards.) A live gold
    eval on this content saw no refusals, so it stays rare in practice.
    """


def _raise_if_refusal(payload, *, context: str = "") -> None:
    """Raise ``ClassificationRefusalError`` if ``payload`` is a refusal response.

    ``payload`` is either a ``Message`` (synchronous path) or a batch item's
    ``.result.message`` -- both carry ``stop_reason`` and, on a refusal, a
    ``stop_details`` object with ``category`` / ``explanation``. ``getattr`` is
    used throughout so this is a safe no-op against response shapes that don't
    set these fields (e.g. test doubles): only an explicit
    ``stop_reason == "refusal"`` triggers it.

    Args:
        payload: The API ``Message`` (or batch ``result.message``) to inspect.
        context: Optional label (e.g. a batch ``custom_id``) folded into the
            error message so a refusal in a bulk run points at the offending row.
    """
    if getattr(payload, "stop_reason", None) != "refusal":
        return
    details = getattr(payload, "stop_details", None)
    category = getattr(details, "category", None)
    explanation = getattr(details, "explanation", None)
    where = f" ({context})" if context else ""
    extra = []
    if category:
        extra.append(f"category={category!r}")
    if explanation:
        extra.append(f"explanation={explanation!r}")
    suffix = " -- " + ", ".join(extra) if extra else ""
    raise ClassificationRefusalError(
        f"model declined to classify{where} (stop_reason='refusal'){suffix}"
    )


def _validate(result: dict) -> dict:
    """Return ``result`` unchanged if all three labels are valid; raise InvalidLabelError otherwise."""
    category = result.get("category")
    domain = result.get("operational_domain")
    region = result.get("region")
    if category not in CATEGORIES:
        raise InvalidLabelError(f"category {category!r} is not one of {CATEGORIES}")
    if domain not in DOMAINS:
        raise InvalidLabelError(
            f"operational_domain {domain!r} is not one of {DOMAINS}"
        )
    if region not in REGIONS:
        raise InvalidLabelError(f"region {region!r} is not one of {REGIONS}")
    return result


def classify(
    client: anthropic.Anthropic,
    text: UserContent,
    temperature: float | None = None,
    model: str = MODEL,
    system_prompt: str = SYSTEM_PROMPT,
) -> dict:
    """Classify a single defense-news article snippet.

    Makes one LLM call with forced, strict tool use so the response is always
    structured JSON — never free text — and is guaranteed by the API's
    constrained decoding to validate against CLASSIFY_TOOL's schema (including
    all three enums) before we ever see it. ``_validate`` is still run as a
    defensive backstop (see ``InvalidLabelError``), but there is no re-sample
    loop any more: a single out-of-schema response would indicate the
    guarantee itself failed, which a client-side retry can't fix.

    Args:
        client: Authenticated Anthropic client.
        text: The user-message content to classify. Usually a raw article
            snippet (``str``), but the RAG layer (``classify_rag``) passes a
            list of content blocks so retrieved passages ride along as
            first-class ``search_result`` blocks; either is forwarded to the
            API's user-message ``content`` field unchanged.
        temperature: Optional sampling temperature. Left at the API default
            (the SDK ``omit`` sentinel) when ``None``. NOTE: Sonnet 5 and the
            other current models reject any *non-default* sampling value with an
            HTTP 400, so in practice this must stay ``None`` -- it is retained
            only so a caller on an older model can still pin it. Determinism is
            no longer sought via temperature: ``strict: true`` already guarantees
            a schema-valid label, and run-to-run stability is measured
            empirically (see ``stability.py``).
        model: Which Claude model classifies. Defaults to the workhorse
            (claude-sonnet-5); pass a higher tier (e.g. the Opus judge) to run
            the same task on a stronger model.
        system_prompt: The instruction block (label definitions + rules) sent as
            the system prompt. Defaults to the module ``SYSTEM_PROMPT`` so callers
            and existing behavior are unchanged; the prompt-optimization loop
            passes a revised prompt here to score a variant against the eval.

    Returns:
        Dict with keys ``category``, ``operational_domain``, and ``region``,
        all str.

    Raises:
        ClassificationRefusalError: If the model declined the request
            (``stop_reason == "refusal"``) -- see that exception's docstring.
        InvalidLabelError: If the response falls outside the allowed label
            sets despite ``strict: true`` -- see ``InvalidLabelError``'s
            docstring for why this should no longer occur in practice.
    """
    # cache_control on the system block caches it AND the tool schema (tools
    # render before system in the API's prefix, so a breakpoint on the last
    # system block covers both). Every caller here reuses one system_prompt
    # across many calls in a row -- eval.py/gold_eval.py across every row of
    # their dataset, the optimize.py loop across ~354 scoring calls per
    # iteration -- so this is the textbook repeated-prefix caching case.
    # SYSTEM_PROMPT's extended rubric deliberately carries the prefix past
    # Sonnet 5's 2048-token minimum cacheable floor (~2425 measured; verified
    # live with scripts/cache_diagnostics.py --live: call 2 reads the full
    # prefix from cache). If a future edit shrinks the prompt back under the
    # floor, the marker silently reverts to a no-op -- re-run that script
    # after any prompt change.
    system_block: TextBlockParam = {
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }

    # One span per classification wraps the LLM call so its cost and outcome are
    # legible when tracing is on (CLASSIFIER_TRACING); a no-op otherwise, so the
    # eval hot path pays nothing. Same GenAI-semconv shape as the kb-agent loop.
    tracer = get_tracer()
    with tracer.start_as_current_span(f"chat {model}") as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model)
        # Pass the SDK's `omit` sentinel when no temperature is requested, so the
        # API uses its own default rather than us forcing a value.
        response = client.messages.create(
            model=model,
            max_tokens=256,
            system=[system_block],
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "classify_article"},
            messages=[{"role": "user", "content": text}],
            output_config=OUTPUT_CONFIG,
            temperature=anthropic.omit if temperature is None else temperature,
        )
        if span.is_recording():
            set_usage_attributes(span, getattr(response, "usage", None))
            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason:
                span.set_attribute("gen_ai.response.finish_reasons", [stop_reason])
        # Guard the refusal case before extracting the tool block: a refusal is an
        # HTTP 200 with stop_reason == "refusal" and no tool_use block, so the
        # next() below would otherwise raise a bare StopIteration. See
        # ClassificationRefusalError.
        _raise_if_refusal(response)
        tool_block = next(b for b in response.content if isinstance(b, ToolUseBlock))
        result = _validate(cast(dict, tool_block.input))
        if span.is_recording():
            span.set_attribute("classifier.category", result["category"])
            span.set_attribute(
                "classifier.operational_domain", result["operational_domain"]
            )
        return result


# ---------------------------------------------------------------------------
# Message Batches API path -- an alternative to calling classify() once per
# article, for non-latency-sensitive bulk runs (a full corpus, or the
# gold-eval judge pass). See decisions/009-message-batches-for-bulk-runs.md
# for when to reach for this instead of the synchronous loop.
# ---------------------------------------------------------------------------


class BatchItemError(RuntimeError):
    """Raised when one Message Batches API result item did not succeed.

    Distinct from InvalidLabelError: a batch item can come back "errored",
    "canceled", or "expired" -- outcomes the synchronous classify() path
    can't produce, since a synchronous call either returns a result or raises
    an SDK exception. InvalidLabelError is still raised separately for a
    "succeeded" item whose labels are somehow out of range.
    """


def build_batch_request(
    custom_id: str,
    text: str,
    model: str = MODEL,
    system_prompt: str = SYSTEM_PROMPT,
    temperature: float | None = None,
) -> Request:
    """Build one Message Batches API request with classify()'s exact call shape.

    Mirrors classify()'s system block -- including its cache_control marker --
    so a batch run over the same system_prompt benefits from prompt caching
    the same way the synchronous path does once the prompt is long enough to
    qualify (see classify()'s docstring/comment for the current token-length
    caveat on claude-sonnet-5). It also mirrors the ``output_config.effort``
    hint so a batch run behaves the same as the synchronous path.

    Args:
        custom_id: Caller-chosen id used to match this request's result back
            to its row once the batch completes. Batch results arrive in any
            order, so callers must key on this -- never on position in the
            requests list.
        text: Raw article snippet to classify.
        model: Which Claude model classifies. Defaults to the workhorse
            (claude-sonnet-5); pass a higher tier (e.g. the Opus judge) for
            the gold-eval judge pass.
        system_prompt: The instruction block sent as the system prompt.
            Defaults to the module ``SYSTEM_PROMPT``.
        temperature: Optional sampling temperature; omitted (API default)
            when ``None``, matching classify()'s behavior.

    Returns:
        A ``Request`` ready to append to the ``requests`` list passed to
        ``client.messages.batches.create``.
    """
    system_block: TextBlockParam = {
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }
    params: MessageCreateParamsNonStreaming = {
        "model": model,
        "max_tokens": 256,
        "system": [system_block],
        "tools": [CLASSIFY_TOOL],
        "tool_choice": {"type": "tool", "name": "classify_article"},
        "messages": [{"role": "user", "content": text}],
        "output_config": OUTPUT_CONFIG,
    }
    if temperature is not None:
        params["temperature"] = temperature
    return Request(custom_id=custom_id, params=params)


def parse_batch_result(result) -> dict:
    """Extract and validate the classified labels from one batch result item.

    Args:
        result: One item yielded by iterating
            ``client.messages.batches.results(batch_id)``.

    Returns:
        Dict with keys ``category``, ``operational_domain``, and ``region``,
        validated the same way as classify()'s return value.

    Raises:
        BatchItemError: If the item's result type is not ``"succeeded"``.
        ClassificationRefusalError: If a succeeded item is a refusal
            (``stop_reason == "refusal"``) -- see that exception's docstring.
        InvalidLabelError: If a succeeded item's labels are somehow still out
            of range -- the same defensive backstop classify() applies.
    """
    if result.result.type != "succeeded":
        raise BatchItemError(
            f"batch item {result.custom_id!r} did not succeed: {result.result.type}"
        )
    message = result.result.message
    # A "succeeded" batch item can still be a refusal (the item transport
    # worked; the model declined) -- guard it the same way classify() does.
    _raise_if_refusal(message, context=f"batch item {result.custom_id!r}")
    tool_block = next(b for b in message.content if isinstance(b, ToolUseBlock))
    return _validate(cast(dict, tool_block.input))


# ---------------------------------------------------------------------------
# Cache-diagnostics instrumentation -- visibility into WHEN classify()'s prompt
# cache actually engages, without touching classify()'s hot path.
#
# classify() marks its system block with cache_control, but on claude-sonnet-5
# the cache silently does nothing until the cached prefix (tool schema + system
# prompt) crosses the model's ~2048-token minimum cacheable-prefix floor. The
# prefix deliberately clears that floor today (~2425 tokens, via SYSTEM_PROMPT's
# extended rubric), so the marker is live -- and these helpers are the guard
# that a future prompt edit doesn't silently slip back under it, using the free
# /v1/messages/count_tokens
# endpoint -- so the prompt-optimization loop (which revises the system prompt
# over iterations) can see whether caching still pays off. The live
# cache_miss_reason beta reporting that pairs with this lives in
# scripts/cache_diagnostics.py, which drives these functions.
# ---------------------------------------------------------------------------

# Minimum cacheable prefix (tokens) per model: below this, the cache_control
# marker on classify()'s system block is a silent no-op (cache_creation stays 0,
# no error). Values from Anthropic's prompt-caching docs; only the models this
# project actually calls are listed (workhorse + Opus judge). Unknown models
# return None from cacheable_prefix_gap().
MIN_CACHEABLE_PREFIX_TOKENS = {
    "claude-sonnet-5": 2048,  # current workhorse (inferred: same-tier as Sonnet 4.6 / Fable 5)
    "claude-sonnet-4-6": 2048,  # prior workhorse, kept for back-compat
    "claude-opus-4-8": 4096,  # gold-eval judge
}


def count_prefix_tokens(
    client: anthropic.Anthropic,
    model: str = MODEL,
    system_prompt: str = SYSTEM_PROMPT,
) -> int:
    """Count the tokens in classify()'s cacheable prefix (tool schema + system prompt).

    Uses the free ``/v1/messages/count_tokens`` endpoint (never ``tiktoken`` --
    that is OpenAI's tokenizer and undercounts Claude tokens). ``count_tokens``
    has no "prefix only" mode, so this counts a request carrying a
    one-character user turn and returns its ``input_tokens``: that user turn
    adds only ~1 token of message-envelope overhead, and -- crucially -- it is
    NOT part of classify()'s cached prefix anyway (the cache breakpoint sits on
    the system block, which the API renders before any message), so the number
    returned is exactly what must clear the cacheable-prefix floor. Pair with
    ``cacheable_prefix_gap`` to see how far off that floor the prefix currently is.

    Args:
        client: Authenticated Anthropic client.
        model: Model whose tokenizer to count against (token counts are
            model-specific). Defaults to the workhorse.
        system_prompt: The system prompt whose prefix size to measure. Defaults
            to the module ``SYSTEM_PROMPT``.

    Returns:
        The token count of the tool schema + system prompt prefix.
    """
    count = client.messages.count_tokens(
        model=model,
        system=[{"type": "text", "text": system_prompt}],
        tools=[CLASSIFY_TOOL],
        messages=[{"role": "user", "content": "x"}],
    )
    return count.input_tokens


def cacheable_prefix_gap(prefix_tokens: int, model: str = MODEL) -> int | None:
    """Tokens the prefix must still gain before ``model``'s prompt cache engages.

    Returns ``floor - prefix_tokens``: a positive value means the prefix is
    still below the floor and the ``cache_control`` marker is currently a no-op;
    ``<= 0`` means the prefix clears the floor and caching is active. Returns
    ``None`` when the floor for ``model`` isn't known (see
    ``MIN_CACHEABLE_PREFIX_TOKENS``).

    Args:
        prefix_tokens: The measured prefix size (see ``count_prefix_tokens``).
        model: Model whose floor to compare against. Defaults to the workhorse.

    Returns:
        Remaining tokens to the floor, or ``None`` if the floor is unknown.
    """
    floor = MIN_CACHEABLE_PREFIX_TOKENS.get(model)
    if floor is None:
        return None
    return floor - prefix_tokens


def make_client() -> anthropic.Anthropic:
    """Build an Anthropic client from the environment.

    Returns:
        Configured ``anthropic.Anthropic`` instance.

    Raises:
        EnvironmentError: If ``ANTHROPIC_API_KEY`` is not set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise OSError(
            "ANTHROPIC_API_KEY is not set. "
            "Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
        )
    # Activate the tracing SDK if CLASSIFIER_TRACING is set; a no-op otherwise.
    setup_tracing()
    return anthropic.Anthropic(api_key=api_key)


def main() -> None:
    """CLI entry point: read article text from args or stdin and print JSON result.

    Raises:
        EnvironmentError: If ``ANTHROPIC_API_KEY`` is not set (via make_client).
    """
    client = make_client()

    # Accept text as CLI args or via stdin (pipe-friendly).
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        print("Enter article text (Ctrl+Z / Ctrl+D to submit):", file=sys.stderr)
        text = sys.stdin.read().strip()

    if not text:
        print("Error: no article text provided.", file=sys.stderr)
        sys.exit(1)

    result = classify(client, text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
