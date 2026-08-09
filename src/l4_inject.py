"""Context-loss injection for the L4 work graph: corrupt one edge, score the bill.

WHY THIS EXISTS. `SYS-022` names the graph layer's characteristic failure --
*context does not cross a node boundary unless an edge explicitly carries it* --
and its Amendment 1 records that L4 is this system's one built-and-measured work
graph. `docs/specs/autonomy-ladder.md` §4 states the asymmetry that follows:
ADR-020 built three governance primitives for that graph (a fail-closed validity
gate, a structural bounce cap, a critic charter) and **all three guard against a
bad critic**. Nothing validates upstream state. This module is the instrument
that measures what that costs.

**The claim under test is not "removing information makes things worse."** That
is a tautology in a lab coat. The claim is that *the guards were built at the
wrong boundary*, and the number that supports it is the share of drops the
existing guards never notice. The pre-registration --
`docs/specs/l4-context-loss-injection.md` -- is canonical for the hypothesis, the
cell matrix, the scoring rules and the decision rule; where this docstring and
that file ever differ, that file wins.

WHAT IT DOES, AND WHAT IT DELIBERATELY DOES NOT. :class:`InjectingBackend` wraps
any :class:`~l4_pipeline.L4Backend` and corrupts exactly one payload as it
crosses exactly one edge. `src/l4_pipeline.py` is **not modified** -- the backend
is the seam, it is the driver's first positional argument, and the existing tests
already inject fakes through it. The corruption is applied to the *consumer's
argument*, never to a producer's return value, which is the distinction that
makes this a context-loss experiment rather than an answer-tampering one: on
`classify -> critic` the critic sees a corrupted label while the label that
actually ships is untouched.

THE THREE EDGES, AND THE ONE THAT DOES NOT EXIST.

===========================  ==================================================
`triage -> critic`           the evidence dict, `critic(evidence=...)`
`classify -> critic`         the label dict, `critic(label=...)`
`critic -> classify`         the reviewer note, `classify(note=...)`, on a bounce
===========================  ==================================================

`triage -> classify` **is not on that list and is not an omission.**
`classify()` takes no evidence argument at all (design fork 1,
`docs/specs/l4-multi-agent.md` §9.1), so there is no edge to drop. Two of the
three edges that do exist terminate at the verifier, so a dropped field here does
not contaminate a downstream *producer* -- it **blinds the verifier**. That is a
narrower and more defensible phenomenon than "propagation", and it is why
:data:`ABSENT_EDGE` is a named constant with a test on it rather than a footnote.

SCORING IS A RATE OVER A PARTITION, NOT A DISTANCE. Hop count is bounded by graph
depth and graph depth is a free parameter someone chose, so publishing a hop
count publishes an architecture decision with error bars on it. Every trial lands
in exactly one bucket of :class:`InjectionOutcome` and the headline is a rate,
which does not move when a node is added. Detection displacement survives only as
a **distribution with an explicit "never" mass** (:func:`displacement_distribution`)
-- there is deliberately no mean, because averaging over a bounded index whose
"never" bucket is undefined is the exact number the partition replaces.

Offline and free:

    uv run python src/l4_inject.py --cells    # the pre-registered matrix + budget
    uv run python src/l4_inject.py --power    # what this n can and cannot detect

Paid (San drives; see the spec's run protocol before spending anything):

    uv run --env-file .env python src/l4_inject.py --control-arm
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

import l4_pipeline
import stability
from eval import wilson_interval
from l4_pipeline import (
    AXES3,
    AgentReply,
    DryRunBackend,
    L4Backend,
    challenge_violations,
    run_pipeline,
)
from mcnemar_power import Scenario, power, required_n
from optimize import UNCLASSIFIED

# ---------------------------------------------------------------------------
# The graph's edges, and the one the graph does not have.
# ---------------------------------------------------------------------------


class Edge(StrEnum):
    """The three edges of the L4 graph that carry state between nodes."""

    TRIAGE_TO_CRITIC = "triage->critic"
    CLASSIFY_TO_CRITIC = "classify->critic"
    CRITIC_TO_CLASSIFY = "critic->classify"


#: The edge a reader expects and the graph does not have. ``classify()`` takes no
#: evidence argument, so no state crosses from triage to classify. Kept as a named
#: constant so the absence is asserted in a test rather than assumed in prose.
ABSENT_EDGE = "triage->classify"

#: Fields the evidence dict carries across ``triage -> critic`` (``TRIAGE_TOOL``).
EVIDENCE_FIELDS = (
    "category_evidence",
    "domain_evidence",
    "region_evidence",
    "ambiguous_axes",
)

#: Fields the label dict carries across ``classify -> critic``.
LABEL_FIELDS = AXES3

#: Audit events that each cost one model call. ``challenge_discarded`` is free.
CALL_EVENTS = ("triage", "classify", "critic", "reclassify", "critic_second")


class DropType(StrEnum):
    """How a payload is corrupted as it crosses its edge.

    ``NULL`` is the negative control and performs no mutation at all. That is a
    deliberate departure from the design brief, which proposed dropping "a field
    the consumer provably never reads": no such field exists on any of the three
    edges. ``ambiguous_axes`` is the closest candidate and it has no critic rubric
    rule -- which makes it a *research question* (is a schema-required field
    decorative?), and a live question cannot double as the arm that proves the
    instrument is quiet. A full-cost pass-through arm is the stronger control
    anyway: it measures the whole apparatus's own noise floor, end to end.
    """

    OMIT = "omit"
    EMPTY = "empty"
    TRUNCATE = "truncate"
    STALE = "stale"
    NULL = "null"


class InjectionOutcome(StrEnum):
    """The terminal bucket for one (row x injection x axis) trial.

    Exactly one applies, and they are assigned in the order
    :func:`classify_outcome` documents. ``CORRECTED`` is not in the design
    brief's four-way partition; it is what makes the partition *exhaustive*. A
    drop that changes the label and lands on gold with no guard involved has to
    go somewhere, and folding it into ``ABSORBED`` (which means "the payload was
    not load-bearing") or ``CAUGHT`` (which credits a guard that never fired)
    would each be a lie of a different kind.
    """

    CAUGHT = "caught"
    CONTAMINATED = "contaminated"
    ABSORBED = "absorbed"
    CORRECTED = "corrected"
    CRASHED = "crashed"


# ---------------------------------------------------------------------------
# The pre-registered cell matrix.
# ---------------------------------------------------------------------------


class CellTier(StrEnum):
    """What kind of claim a cell is allowed to support.

    Added 2026-08-09, after the pre-run power analysis was read and *before* any
    paid call -- which is the only window in which this may change (§6's void
    condition; ``--cells`` says so on every run). The power table showed a
    Bonferroni correction over eleven live cells pushing the minimum detectable
    contamination rate to 33 points at ``n=44`` and 51 points on the backward
    edge, so a matrix of eleven co-equal confirmatory tests could not have
    concluded anything short of catastrophic. Tiering fixes that by spending the
    confirmatory budget on one cell instead of splitting it eleven ways.

    ``CONTROL`` is the negative control: it gates readability of everything else
    and makes no claim of its own.

    ``PRIMARY`` is the single confirmatory test, at :data:`ALPHA_PRIMARY`. One
    test, no correction, because there is one of it.

    ``SECONDARY`` cells are pre-registered and reported in full -- rate, Wilson
    interval, and p-value -- but **no secondary p-value is read as a discovery**.
    They exist to place the primary in context and to answer H2, which is a
    question about rates and never needed a significance test.

    ``DESCRIPTIVE`` cells additionally cannot support a comparative claim at any
    alpha: the backward edge only fires on rows that bounce, leaving ``n~=25``,
    where even the uncorrected minimum detectable rate is 36 points. Reporting
    their p-values as if they were tests would be the "not detectable here" ->
    "no effect" slide §7.1 forbids. Their rates are still worth having.
    """

    CONTROL = "control"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    DESCRIPTIVE = "descriptive"


@dataclass(frozen=True)
class Cell:
    """One pre-registered injection: an edge, a field on it, and a corruption.

    Attributes:
        edge: Which edge the corruption is applied to.
        drop: How the payload is corrupted.
        field: The payload key, or ``None`` when the whole payload is a scalar
            (the backward edge carries a bare string) or when nothing is
            corrupted at all (``DropType.NULL``).
        affected_axis: The label axis this cell is expected to disturb, or
            ``None`` when the cell targets no single axis. It selects the
            headline axis for the partition and decides which challenge counts
            as the guard firing.
        tier: What kind of claim this cell may support. See :class:`CellTier`.
    """

    edge: Edge
    drop: DropType
    field: str | None = None
    affected_axis: str | None = None
    tier: CellTier = CellTier.SECONDARY

    @property
    def name(self) -> str:
        """Stable cell id, used in reports and pinned against the spec."""
        return f"{self.edge}/{self.field or 'payload'}/{self.drop}"


#: The negative control: a full-cost pass-through arm. Registered first because
#: the run is void if it is not quiet, so nothing else is readable without it.
NULL_CONTROL = Cell(Edge.TRIAGE_TO_CRITIC, DropType.NULL, tier=CellTier.CONTROL)

#: Every live cell, fixed before the first paid call. Post-hoc cell selection is
#: the failure this tuple exists to prevent, and
#: ``test_l4_inject.py::test_the_registered_matrix_matches_the_pre_registration``
#: pins it against the spec so neither can move alone.
LIVE_CELLS = (
    # -- triage -> critic: the SYS-022 failure verbatim, on the hypothesis axis.
    # The first of these is THE confirmatory test: it is the surgical version of
    # the failure (one field, not the payload) and it sits on the axis ADR-020
    # built the critic to fix, so a null here is maximally informative.
    Cell(
        Edge.TRIAGE_TO_CRITIC,
        DropType.OMIT,
        "region_evidence",
        "region",
        CellTier.PRIMARY,
    ),
    Cell(Edge.TRIAGE_TO_CRITIC, DropType.EMPTY, "region_evidence", "region"),
    Cell(Edge.TRIAGE_TO_CRITIC, DropType.TRUNCATE, "region_evidence", "region"),
    Cell(Edge.TRIAGE_TO_CRITIC, DropType.STALE, "region_evidence", "region"),
    # A second axis: is the effect about region, or about evidence in general?
    Cell(Edge.TRIAGE_TO_CRITIC, DropType.OMIT, "category_evidence", "category"),
    # The anti-tuned cell: a schema-required field with NO critic rubric rule.
    # H2's sharpest test, and H2 is a question about rates, so SECONDARY costs
    # it nothing -- the ABSORBED rate and its interval are the whole answer.
    Cell(Edge.TRIAGE_TO_CRITIC, DropType.OMIT, "ambiguous_axes", None),
    # -- classify -> critic: blind the verifier to what it is verifying.
    Cell(Edge.CLASSIFY_TO_CRITIC, DropType.OMIT, "region", "region"),
    Cell(Edge.CLASSIFY_TO_CRITIC, DropType.STALE, "region", "region"),
    # -- critic -> classify: the backward edge, and it only fires on a bounce.
    # n~=25 puts even the uncorrected MDR at 36 points, so these are registered
    # as DESCRIPTIVE: rates yes, comparative claims no. See CellTier.
    Cell(Edge.CRITIC_TO_CLASSIFY, DropType.OMIT, None, None, CellTier.DESCRIPTIVE),
    Cell(
        Edge.CRITIC_TO_CLASSIFY,
        DropType.TRUNCATE,
        None,
        None,
        CellTier.DESCRIPTIVE,
    ),
    Cell(Edge.CRITIC_TO_CLASSIFY, DropType.STALE, None, None, CellTier.DESCRIPTIVE),
)

#: The full matrix in run order, control first.
CELLS = (NULL_CONTROL, *LIVE_CELLS)

#: The single confirmatory cell. Derived rather than restated so it cannot drift
#: from :data:`LIVE_CELLS`; a test pins that exactly one cell holds this tier.
PRIMARY_CELL = next(c for c in LIVE_CELLS if c.tier is CellTier.PRIMARY)

#: Cells whose rates are reported but which may not carry a comparative claim.
DESCRIPTIVE_CELLS = tuple(c for c in LIVE_CELLS if c.tier is CellTier.DESCRIPTIVE)

#: Measured calls per row for L4 on gold (``evals/l4_eval.txt``, ADR-020 run).
CALLS_PER_ROW = 4.15

#: Gold rows, and the share of them the backward edge fires on (``fixed`` +
#: ``contested`` = 31/54 in the ADR-020 run). The backward-edge cells are scored
#: on that subset only, which is the single largest n cost in the design.
GOLD_ROWS = 54
BOUNCE_RATE = 31 / 54

#: Control passes used to build the stable set (``src/stability.py``'s method).
CONTROL_RUNS = 5

#: Where this experiment's artifacts go. Nothing here overlaps the committed
#: ADR-020 record.
ARTIFACT_DIR = "evals/l4_inject"


def infeasible_cells() -> dict[str, str]:
    """Combinations the matrix omits on purpose, and why.

    Recording them here rather than in prose keeps "we did not run that" separable
    from "we ran that and buried it" -- the distinction pre-registration exists
    to protect.

    Returns:
        Cell-shaped keys mapped to the reason the cell is not registered.
    """
    return {
        "classify->critic/*/truncate": (
            "a label value is a single enum token; it has no clause to cut, so "
            "truncation degenerates into either omit or a corrupt token"
        ),
        "critic->classify/*/empty": (
            "the backward edge carries a bare string, so emptying it and omitting "
            "it are the same injection; only omit is registered"
        ),
        ABSENT_EDGE
        + "/*/*": (
            "the edge does not exist -- classify() takes no evidence argument, so "
            "no state crosses from triage to classify. This absence is a finding, "
            "not a gap in the matrix"
        ),
    }


def planned_calls(stable_n: int) -> dict[str, int]:
    """Budget the whole experiment in calls, from measured cost per row.

    Args:
        stable_n: Rows surviving the stability filter, on which cells are scored.

    Returns:
        ``control``, ``injected`` and ``total`` call counts, rounded up.
    """
    control = round(CONTROL_RUNS * GOLD_ROWS * CALLS_PER_ROW)
    forward = sum(1 for c in CELLS if c.edge is not Edge.CRITIC_TO_CLASSIFY)
    backward = sum(1 for c in CELLS if c.edge is Edge.CRITIC_TO_CLASSIFY)
    injected = round(
        forward * stable_n * CALLS_PER_ROW
        + backward * stable_n * BOUNCE_RATE * CALLS_PER_ROW
    )
    return {"control": control, "injected": injected, "total": control + injected}


# ---------------------------------------------------------------------------
# The injection itself.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Donor:
    """Another row's payloads: the source of every ``STALE`` substitution.

    Staleness is the most realistic drop type and the nastiest -- a well-formed,
    plausible value that belongs to a different snippet. The donor row is fixed
    by the run protocol (row ``i`` is donated to by row ``i+1``, wrapping), never
    chosen per trial, so a stale cell cannot be quietly tuned by picking a donor
    that happens to hurt.

    Attributes:
        evidence: The donor row's triage payload.
        label: The donor row's classify payload.
        note: The donor row's reviewer note, or ``""`` if it never bounced.
    """

    evidence: Mapping[str, object] = field(default_factory=dict)
    label: Mapping[str, str] = field(default_factory=dict)
    note: str = ""


def first_clause(text: str) -> str:
    """The leading clause of a span -- a brief that fits, badly.

    Cuts at the first clause boundary (``,;:.``). A span with no boundary is cut
    to its first half by whitespace tokens, so truncation always removes
    something; a no-op truncation would silently become a second null control.

    Args:
        text: The span to shorten.

    Returns:
        The leading clause, stripped. An empty or single-token input is returned
        unchanged -- there is nothing to cut.
    """
    stripped = text.strip()
    for index, char in enumerate(stripped):
        if char in ",;:." and index > 0:
            return stripped[:index].strip()
    tokens = stripped.split()
    if len(tokens) < 2:
        return stripped
    return " ".join(tokens[: len(tokens) // 2])


def corrupt_value(value: object, drop: DropType, donor: object = None) -> object:
    """Apply one corruption to one payload value.

    Type-aware because the edges are: evidence spans and the reviewer note are
    strings, ``ambiguous_axes`` is a list, and label values are enum tokens.

    Args:
        value: The value crossing the edge.
        drop: The corruption to apply. ``OMIT`` is handled by the caller for
            dicts (the key is removed); here it empties the value, which is what
            omission means for a bare string payload.
        donor: The replacement used by ``STALE``.

    Returns:
        The corrupted value.

    Raises:
        ValueError: If ``STALE`` is requested with no donor value.
    """
    if drop is DropType.NULL:
        return value
    if drop is DropType.STALE:
        if donor is None:
            raise ValueError("a STALE injection needs a donor value")
        return donor
    if drop in (DropType.EMPTY, DropType.OMIT):
        return [] if isinstance(value, list) else ""
    if isinstance(value, list):
        return value[:1]
    return first_clause(str(value))


def corrupt_payload(
    payload: Mapping[str, object],
    cell: Cell,
    donor: object = None,
) -> dict:
    """Return a corrupted **copy** of a payload dict.

    The copy is not a style preference. ``process_row`` appends the triage and
    classify payloads to the audit trail *by reference* before the critic runs,
    and the trail is serialized after the row completes -- so mutating in place
    would rewrite the record of what the producer actually said, and the
    experiment would lose the very thing it is measuring against.

    Args:
        payload: The producer's payload.
        cell: The registered cell; supplies the field and the drop type.
        donor: The replacement value for ``STALE``.

    Returns:
        A new dict with the cell's corruption applied. A field the payload does
        not carry is left alone -- the injection is a no-op rather than an error,
        because a model can legitimately omit a field the schema asked for and
        that is not this experiment's failure to report.
    """
    corrupted = dict(payload)
    if cell.drop is DropType.NULL or cell.field is None:
        return corrupted
    if cell.field not in corrupted:
        return corrupted
    if cell.drop is DropType.OMIT:
        del corrupted[cell.field]
        return corrupted
    corrupted[cell.field] = corrupt_value(corrupted[cell.field], cell.drop, donor)
    return corrupted


class InjectingBackend:
    """An ``L4Backend`` that corrupts one payload as it crosses one edge.

    Structurally satisfies the Protocol, so the driver, the resume logic, the
    retry policy and the audit trail are all reused unmodified. Corruption is
    applied to the **consumer's argument**, so a producer's own recorded output
    and the label that finally ships are both untouched.
    """

    def __init__(
        self, inner: L4Backend, cell: Cell, donor: Donor | None = None
    ) -> None:
        """Wrap a backend for one cell.

        Args:
            inner: The real (or dry-run) backend doing the work.
            cell: The registered injection.
            donor: Another row's payloads, required for ``STALE`` cells.
        """
        self.inner = inner
        self.cell = cell
        self.donor = donor or Donor()
        self.injections = 0

    def triage(self, text: str) -> AgentReply:
        """Pass through: triage is a producer, and producers are not corrupted."""
        return self.inner.triage(text)

    def classify(self, text: str, note: str = "") -> AgentReply:
        """The shipped classifier; the backward edge is the ``note`` argument."""
        if self.cell.edge is Edge.CRITIC_TO_CLASSIFY and note:
            note = str(corrupt_value(note, self.cell.drop, self.donor.note or None))
            self.injections += 1
        return self.inner.classify(text, note)

    def critic(self, text: str, evidence: dict, label: dict) -> AgentReply:
        """The verifier; both forward edges are its arguments."""
        if self.cell.edge is Edge.TRIAGE_TO_CRITIC:
            evidence = corrupt_payload(evidence, self.cell, self._donor_for(evidence))
            self.injections += 1
        elif self.cell.edge is Edge.CLASSIFY_TO_CRITIC:
            label = corrupt_payload(label, self.cell, self._donor_for(label))
            self.injections += 1
        return self.inner.critic(text, evidence, label)

    def _donor_for(self, payload: Mapping[str, object]) -> object:
        if self.cell.drop is not DropType.STALE or self.cell.field is None:
            return None
        source = (
            self.donor.evidence
            if self.cell.edge is Edge.TRIAGE_TO_CRITIC
            else self.donor.label
        )
        if self.cell.field not in source and self.cell.field in payload:
            raise ValueError(f"donor carries no {self.cell.field!r} to substitute")
        return source.get(self.cell.field)


class GuardedDryRunBackend(DryRunBackend):
    """The offline backend, hardened against a dropped key.

    ``DryRunBackend.critic`` subscripts ``evidence["region_evidence"]`` and
    ``label["region"]`` directly, so every omission cell would raise there and the
    whole offline harness would only ever exercise ``CRASHED``. The **live** path
    does not raise -- it ``json.dumps``es whatever it was handed -- so the crash
    is an artifact of the canned backend, not the behaviour under test. Absence
    is read the way the live critic would read it: as evidence that states
    nothing.
    """

    def critic(self, text: str, evidence: dict, label: dict) -> AgentReply:
        """Review, treating a missing key as an absent claim rather than an error."""
        return super().critic(
            text,
            {"region_evidence": l4_pipeline.NONE_STATED, **evidence},
            {"region": UNCLASSIFIED, **label},
        )


# ---------------------------------------------------------------------------
# Scoring: the four-way partition, plus the bucket that makes it exhaustive.
# ---------------------------------------------------------------------------


def valid_challenge_axes(events: Iterable[Mapping]) -> list[str]:
    """The axes of every *valid* challenge in one row's audit trail.

    Validity is the charter's own definition, read through
    ``l4_pipeline.challenge_violations`` rather than re-derived here -- an
    invalid challenge is discarded by the pipeline and must not be credited as
    the guard firing. The same gate is applied to the second review, which the
    driver only tests for ``accept``; a second challenge that names no axis is
    not evidence of detection either.

    Args:
        events: The row's audit events, as written to the run JSONL.

    Returns:
        Axis names, in the order they were challenged; duplicates kept.
    """
    axes = []
    for event in events:
        if event.get("event") not in ("critic", "critic_second"):
            continue
        payload = event.get("payload") or {}
        if payload.get("verdict") != "challenge":
            continue
        if challenge_violations(payload):
            continue
        axes.append(str(payload.get("axis")))
    return axes


def guard_fired(cell: Cell, challenged_axes: Sequence[str]) -> bool:
    """Did the existing guard notice this cell's injection?

    Args:
        cell: The registered injection.
        challenged_axes: Output of :func:`valid_challenge_axes`.

    Returns:
        True when a valid challenge names the cell's affected axis -- or any axis
        at all, for a cell that targets none.
    """
    if cell.affected_axis is None:
        return bool(challenged_axes)
    return cell.affected_axis in challenged_axes


def classify_outcome(
    gold: str,
    control: str,
    injected: str,
    *,
    caught: bool,
    crashed: bool = False,
) -> InjectionOutcome:
    """Assign one trial's terminal bucket, on one axis.

    Order matters and is fixed here so it cannot be re-litigated after the
    numbers are in:

    1. ``CRASHED`` -- the run raised rather than answered. A robustness fact, not
       a context-loss fact; reported separately and never folded into a rate.
    2. ``CAUGHT`` -- the guard fired on the affected axis *and* the shipped label
       is right. Checked before ``ABSORBED`` on purpose: a drop the critic caught
       and repaired back to the control's answer is a working guard, not an
       inert edge.
    3. ``ABSORBED`` -- the shipped label equals the control's. The payload was not
       load-bearing. **The most interesting bucket**, and the design's insurance
       against the tautology critique: if a carefully-specified edge turns out to
       change nothing, the finding is about which parts of an edge are real.
    4. ``CORRECTED`` -- changed, right, and no guard involved. Exhaustiveness.
    5. ``CONTAMINATED`` -- wrong, attributable to the drop, and shipped. The
       headline.

    Args:
        gold: The human label for this row and axis (``data/gold/gold.csv``).
        control: The paired un-injected run's label. Answers *did the drop cause
            it*, which gold alone cannot.
        injected: The label this trial shipped.
        caught: Output of :func:`guard_fired`.
        crashed: True when the trial raised.

    Returns:
        The bucket.
    """
    if crashed:
        return InjectionOutcome.CRASHED
    if caught and injected == gold:
        return InjectionOutcome.CAUGHT
    if injected == control:
        return InjectionOutcome.ABSORBED
    if injected == gold:
        return InjectionOutcome.CORRECTED
    return InjectionOutcome.CONTAMINATED


def partition_counts(outcomes: Iterable[InjectionOutcome]) -> dict[str, int]:
    """Count every bucket, including the empty ones.

    Args:
        outcomes: One outcome per trial.

    Returns:
        Every :class:`InjectionOutcome` value mapped to its count. Absent buckets
        report 0 rather than going missing -- a bucket that vanishes from a report
        reads as "not measured".
    """
    counts = {bucket.value: 0 for bucket in InjectionOutcome}
    for outcome in outcomes:
        counts[outcome.value] += 1
    return counts


def partition_rates(outcomes: Iterable[InjectionOutcome]) -> dict[str, dict]:
    """Bucket rates with Wilson intervals, denominated on the scored trials.

    ``CRASHED`` trials are counted but excluded from the denominator: a run that
    raised produced no label, so folding it into a contamination rate would
    charge a robustness failure to context loss. Wilson because it is the repo's
    only interval (``eval.wilson_interval``); nothing here needs a bootstrap and
    the repo has none.

    Args:
        outcomes: One outcome per trial.

    Returns:
        Per-bucket ``{count, rate, low, high}``, plus ``_meta`` carrying
        ``trials``, ``scored`` and ``crashed``. Rates are ``None`` when nothing
        scored -- "nothing to compare" is not "no difference".
    """
    counts = partition_counts(outcomes)
    trials = sum(counts.values())
    crashed = counts[InjectionOutcome.CRASHED.value]
    scored = trials - crashed
    out: dict[str, dict] = {
        "_meta": {"trials": trials, "scored": scored, "crashed": crashed}
    }
    for bucket, count in counts.items():
        if bucket == InjectionOutcome.CRASHED.value or not scored:
            out[bucket] = {"count": count, "rate": None, "low": None, "high": None}
            continue
        low, high = wilson_interval(count, scored)
        out[bucket] = {
            "count": count,
            "rate": count / scored,
            "low": low,
            "high": high,
        }
    return out


# ---------------------------------------------------------------------------
# Secondaries: cost after the drop, and displacement as a distribution.
# ---------------------------------------------------------------------------


def _consumer_event(edge: Edge) -> str:
    return "reclassify" if edge is Edge.CRITIC_TO_CLASSIFY else "critic"


def calls_after_injection(events: Sequence[Mapping], edge: Edge) -> int:
    """Model calls spent from the moment the corrupted payload crossed its edge.

    Inclusive of the consumer's own call, which is the first call spent on
    corrupted input. Calls are the honest cost axis here: ``AgentReply.tokens`` is
    computed and then dropped by the driver's event dict, ``classify`` reports
    zero tokens by design, and no latency is captured anywhere in the pipeline.

    Args:
        events: The row's audit events in order.
        edge: The injected edge.

    Returns:
        Call count, or 0 when the injection never fired (the backward edge on a
        row that never bounced).
    """
    names = [e.get("event") for e in events]
    consumer = _consumer_event(edge)
    if consumer not in names:
        return 0
    start = names.index(consumer)
    return sum(1 for name in names[start:] if name in CALL_EVENTS)


def detection_displacement(events: Sequence[Mapping], edge: Edge) -> int | None:
    """Call-events between the injection point and the first valid challenge.

    Args:
        events: The row's audit events in order.
        edge: The injected edge.

    Returns:
        The non-negative displacement, or ``None`` for never detected. ``None`` is
        the point of the function: it is the mass a mean would silently drop.
    """
    ordered = [e for e in events if e.get("event") in CALL_EVENTS]
    names = [e.get("event") for e in ordered]
    consumer = _consumer_event(edge)
    if consumer not in names:
        return None
    start = names.index(consumer)
    for offset, event in enumerate(ordered[start:]):
        if valid_challenge_axes([event]):
            return offset
    return None


def displacement_distribution(values: Iterable[int | None]) -> dict[str, int]:
    """Tally displacements with an explicit ``never`` bucket, and no mean.

    There is deliberately no mean and no median. On a three-node graph the
    observable range is ``{0, 1}`` with a ``never`` mass of unbounded size, so any
    central tendency is a statement about the graph's depth -- a parameter chosen
    at design time -- dressed as a measurement.

    Args:
        values: One displacement per trial, ``None`` for never detected.

    Returns:
        Stringified displacements mapped to counts, plus ``"never"``.
    """
    tally: dict[str, int] = {"never": 0}
    for value in values:
        key = "never" if value is None else str(value)
        tally[key] = tally.get(key, 0) + 1
    return tally


# ---------------------------------------------------------------------------
# The stable set: nondeterminism turned from a confound into a filter.
# ---------------------------------------------------------------------------


def stable_ids(frames: Sequence[pd.DataFrame], axes: Sequence[str] = AXES3) -> list:
    """Ids whose label is identical across every control run, on every axis.

    The method and the threshold are ``src/stability.py``'s, ratified there: a
    difference is only meaningful if it clears roughly 2x the run-to-run standard
    deviation, and run-to-run stability is *measured* rather than forced, because
    current models reject a non-default temperature with a 400 and no seed exists
    at the API level. What is added here is only the return type --
    ``stability.label_consistency`` reports the *fraction* that agreed, and the
    filter needs the *ids*, on all three axes rather than two.

    Args:
        frames: One predictions DataFrame per control run, each with ``id`` and
            ``pred_<axis>`` columns.
        axes: Axes that must all agree.

    Returns:
        Sorted ids present in every frame and identically labelled in all of them.

    Raises:
        ValueError: If no frames are supplied.
    """
    if not frames:
        raise ValueError("frames must contain at least one control run")
    stable: set | None = None
    for axis in axes:
        joined = pd.concat(
            [frame.set_index("id")[f"pred_{axis}"] for frame in frames], axis=1
        )
        complete = joined[joined.notna().all(axis=1)]
        agree = set(complete.index[complete.nunique(axis=1) == 1])
        stable = agree if stable is None else stable & agree
    return sorted(stable or set())


def control_consistency(frames: Sequence[pd.DataFrame]) -> dict:
    """The ratified consistency figures, computed by ``stability.py`` itself.

    Reported beside :func:`stable_ids` as a cross-check: the fraction the house
    function reports for category and domain must equal the fraction this
    module's filter keeps on those same axes, or one of the two is wrong.

    Args:
        frames: One predictions DataFrame per control run.

    Returns:
        ``stability.label_consistency``'s dict, plus ``region_consistency`` and
        ``stable_fraction`` over all three axes.
    """
    result = dict(stability.label_consistency(list(frames)))
    total = len(set(frames[0]["id"]))
    result["region_consistency"] = round(
        len(stable_ids(frames, ("region",))) / total, 4
    )
    result["stable_fraction"] = round(len(stable_ids(frames)) / total, 4)
    return result


# ---------------------------------------------------------------------------
# Power: what this n can and cannot detect, computed before anything is spent.
# ---------------------------------------------------------------------------

#: Two-sided alpha for the ONE confirmatory test (:data:`PRIMARY_CELL`). No
#: correction is applied to it and none is owed: a single pre-registered test is
#: not a family. This is the operative threshold for the whole design.
ALPHA_PRIMARY = 0.05

#: Backwards-compatible alias. Same number, and every remaining use is either the
#: primary's threshold or the uncorrected column of the power table.
ALPHA = ALPHA_PRIMARY

#: What a Bonferroni correction would cost if all eleven live cells were treated
#: as co-equal confirmatory tests. **They are not** -- see :class:`CellTier`.
#: Retained and still printed because it is the arithmetic that justifies the
#: tiering: at this threshold the design needs a 33-point effect at ``n=44`` and
#: 51 on the backward edge, which is why spending the budget on eleven tests was
#: the wrong design. Reported as a cost avoided, never as a threshold in force.
ALPHA_FAMILYWISE = ALPHA_PRIMARY / len(LIVE_CELLS)


def power_scenarios() -> list[Scenario]:
    """Assumed contamination rates, worst case first.

    ``p_b`` is the per-row probability the injected arm is wrong where the control
    arm was right -- the contamination the experiment is powered for. ``p_c``, the
    reverse, is held at 0.02: on the stable set a drop should essentially never
    *improve* an answer, and pretending it is exactly zero would flatter the
    sample size.

    Returns:
        Scenarios spanning a plausible effect range.
    """
    return [
        Scenario("very large (40%)", 0.40, 0.02),
        Scenario("large (30%)", 0.30, 0.02),
        Scenario("moderate (20%)", 0.20, 0.02),
        Scenario("small (15%)", 0.15, 0.02),
        Scenario("very small (10%)", 0.10, 0.02),
    ]


def minimum_detectable_rate(
    n: int, alpha: float = ALPHA, target: float = 0.80, reverse: float = 0.02
) -> float | None:
    """Smallest contamination rate this ``n`` can detect at ``target`` power.

    Args:
        n: Paired rows available in the cell.
        alpha: Two-sided significance level.
        target: Power to reach.
        reverse: Assumed rate of drops that improve the answer.

    Returns:
        The rate, to the nearest percentage point, or ``None`` if nothing under
        95% qualifies.
    """
    for step in range(1, 96):
        rate = step / 100
        if power(n, Scenario(f"mdr-{step}", rate, reverse), alpha) >= target:
            return rate
    return None


def power_table(stable_n: int = 44) -> str:
    """The pre-run power analysis, rendered.

    Args:
        stable_n: Expected size of the stable set.

    Returns:
        The report text.
    """
    backward_n = round(stable_n * BOUNCE_RATE)
    sizes = sorted({backward_n, stable_n, GOLD_ROWS})
    lines = [
        "=" * 78,
        "L4 INJECTION -- PRE-RUN POWER (exact two-sided McNemar, injected vs control)",
        "=" * 78,
        "",
        f"Rows: gold {GOLD_ROWS}; stable-set assumption {stable_n}; backward-edge "
        f"cells {backward_n} (only rows that bounce).",
        f"Cells: {len(LIVE_CELLS)} live + 1 null control, tiered. ONE confirmatory "
        f"test at alpha {ALPHA_PRIMARY} ({PRIMARY_CELL.name});",
        f"the other {len(LIVE_CELLS) - 1} are reported, not tested. The "
        f"{ALPHA_FAMILYWISE:.4f} Bonferroni column below is the cost",
        "that tiering avoids -- it is NOT a threshold in force.",
        "",
    ]
    for alpha, tag in (
        (ALPHA_PRIMARY, "in force, for the primary cell"),
        (ALPHA_FAMILYWISE, "Bonferroni over 11 -- avoided, shown for contrast"),
    ):
        lines.append(f"-- alpha = {alpha:.4f} ({tag}) " + "-" * 30)
        lines.append(
            f"{'contamination rate':<22}"
            + "".join(f"{'n=' + str(n):>10}" for n in sizes)
            + f"{'n for 80%':>12}"
        )
        for scenario in power_scenarios():
            row = f"{scenario.label:<22}"
            for n in sizes:
                row += f"{power(n, scenario, alpha):>10.3f}"
            need = required_n(0.80, scenario, alpha)
            row += f"{(str(need) if need else '>20000'):>12}"
            lines.append(row)
        lines.append("")
        for n in sizes:
            rate = minimum_detectable_rate(n, alpha)
            shown = f"{rate:.0%}" if rate else "not reachable"
            lines.append(f"  minimum detectable contamination at n={n:<4}: {shown}")
        lines.append("")
    lines += [
        "Read this before reading any result. The SIGNIFICANCE test detects LARGE",
        "effects only and cannot distinguish a modest contamination rate from zero;",
        "a null is 'not detectable here', never 'no effect'. That is why the headline",
        "is ABSORBED -- a proportion with a Wilson interval, which needs no test and",
        f"is usable at n={stable_n} wherever it sits near an extreme. CONTAMINATED is",
        "the attribution number and is secondary. Power is a variance instrument; it",
        "says nothing about the answer key's own disagreements with itself.",
        "=" * 78,
    ]
    return "\n".join(lines)


def cells_table(stable_n: int = 44) -> str:
    """The pre-registered matrix and its budget, rendered.

    Args:
        stable_n: Expected size of the stable set, used for the call budget.

    Returns:
        The report text.
    """
    budget = planned_calls(stable_n)
    lines = [
        "=" * 78,
        "L4 INJECTION -- PRE-REGISTERED CELL MATRIX",
        "=" * 78,
        "",
        f"{'#':>3}  {'cell':<52}{'axis':>12}{'tier':>13}",
    ]
    for index, cell in enumerate(CELLS):
        lines.append(
            f"{index:>3}  {cell.name:<52}"
            f"{cell.affected_axis or '-':>12}{cell.tier:>13}"
        )
    lines += [
        "",
        "Tiers, fixed before the first paid call and after the power table was read:",
        f"  primary     ONE confirmatory test at alpha {ALPHA_PRIMARY}. No correction "
        f"is owed a single test.",
        "  secondary   Rate + Wilson interval + p-value, all reported. No secondary",
        "              p-value is read as a discovery. H2 lives here and needs no test.",
        "  descriptive Rates only. The backward edge fires only on rows that bounce,",
        "              so n~=25 and even the uncorrected MDR is 36 points; a",
        "              comparative claim there would be unsupportable at any alpha.",
    ]
    lines += ["", "Not registered, and why:"]
    for key, reason in infeasible_cells().items():
        lines.append(f"  {key}")
        lines.append(f"      {reason}")
    lines += [
        "",
        f"Budget at stable_n={stable_n}: control {budget['control']} calls "
        f"({CONTROL_RUNS} x {GOLD_ROWS} rows x {CALLS_PER_ROW} calls/row), "
        f"injected {budget['injected']}, TOTAL {budget['total']}.",
        "",
        "No arm has been run against this matrix. Adding, removing or re-scoping a",
        "cell after the first paid call is post-hoc selection and voids the",
        "pre-registration.",
        "=" * 78,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The control arm (the only paid path here, and it is opt-in).
# ---------------------------------------------------------------------------


def control_arm(runs: int = CONTROL_RUNS, dry_run: bool = False) -> list[str]:
    """Run the un-injected pipeline N times to build the stable set.

    The committed ADR-020 record (``evals/l4_gold_predictions.csv``) is never
    opened. ``l4_pipeline.RUN_PATHS`` is repointed at this experiment's own
    directory for the duration and restored in a ``finally`` -- the same seam the
    pipeline's own tests use, and the reason this needs no edit to
    ``src/l4_pipeline.py``. Each pass is individually resume-safe, so an
    interrupted run costs at most one call.

    Args:
        runs: Number of control passes.
        dry_run: Use the offline backend and spend nothing.

    Returns:
        The per-run predictions CSV paths, in order.
    """
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    original = l4_pipeline.RUN_PATHS["gold"]
    paths = []
    try:
        for index in range(1, runs + 1):
            out = os.path.join(ARTIFACT_DIR, f"control_gold_run{index}.csv")
            audit = os.path.join(ARTIFACT_DIR, f"control_gold_run{index}.jsonl")
            l4_pipeline.RUN_PATHS["gold"] = out
            backend: L4Backend = (
                GuardedDryRunBackend()
                if dry_run
                else l4_pipeline.AnthropicL4Backend(l4_pipeline.make_client())
            )
            print(f"control pass {index}/{runs} -> {out}", flush=True)
            run_pipeline("gold", backend, audit_path=audit)
            paths.append(out)
    finally:
        l4_pipeline.RUN_PATHS["gold"] = original
    return paths


def main() -> None:
    """CLI entrypoint. ``--cells`` and ``--power`` are offline and free."""
    parser = argparse.ArgumentParser(description="L4 context-loss injection harness.")
    parser.add_argument("--cells", action="store_true", help="print the matrix")
    parser.add_argument("--power", action="store_true", help="print the power table")
    parser.add_argument(
        "--stable-n", type=int, default=44, help="assumed stable-set size"
    )
    parser.add_argument(
        "--control-arm",
        action="store_true",
        help=f"run {CONTROL_RUNS} un-injected passes (PAID unless --dry-run)",
    )
    parser.add_argument("--dry-run", action="store_true", help="offline backend")
    args = parser.parse_args()
    if args.cells:
        print(cells_table(args.stable_n))
    if args.power:
        print(power_table(args.stable_n))
    if args.control_arm:
        for path in control_arm(dry_run=args.dry_run):
            print(f"  wrote {path}")
    if not (args.cells or args.power or args.control_arm):
        parser.error("nothing to do: pass --cells, --power and/or --control-arm")


if __name__ == "__main__":
    main()
