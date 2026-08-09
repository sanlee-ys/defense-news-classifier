"""Offline tests for the L4 context-loss injection harness (no key, no network).

What gets pinned: every drop type on every edge does what the pre-registration
says it does, the producer's own payload and the shipped label are never touched,
all five outcome buckets are reachable, the partition is exhaustive, the
displacement report keeps its ``never`` mass, and the committed cell matrix still
matches the spec file it was pre-registered in.
"""

import re

import pandas as pd
import pytest

import l4_inject
import l4_pipeline
from l4_inject import (
    ABSENT_EDGE,
    CELLS,
    LIVE_CELLS,
    NULL_CONTROL,
    Cell,
    Donor,
    DropType,
    Edge,
    GuardedDryRunBackend,
    InjectingBackend,
    InjectionOutcome,
    calls_after_injection,
    cells_table,
    classify_outcome,
    control_arm,
    corrupt_payload,
    corrupt_value,
    detection_displacement,
    displacement_distribution,
    first_clause,
    guard_fired,
    partition_counts,
    partition_rates,
    power_table,
    stable_ids,
    valid_challenge_axes,
)
from l4_pipeline import AgentReply, process_row

SPEC_PATH = "docs/specs/l4-context-loss-injection.md"

EVIDENCE = {
    "category_evidence": "awarded a contract, worth $4M",
    "domain_evidence": "the destroyer got under way",
    "region_evidence": "the Philippine Sea, east of Luzon",
    "ambiguous_axes": ["region", "category"],
}
LABEL = {
    "category": "operations",
    "operational_domain": "sea",
    "region": "indo-pacific",
}
DONOR = Donor(
    evidence={
        "category_evidence": "a budget request of $1.2B",
        "region_evidence": "Ramstein Air Base, Germany",
        "ambiguous_axes": ["category"],
    },
    label={"category": "procurement", "operational_domain": "air", "region": "europe"},
    note="\n\nA reviewer flagged the 'category' axis. Rubric rule: no contract verb.",
)


class SpyBackend:
    """A stub backend that records exactly what each node was handed."""

    def __init__(self, bounce: bool = False) -> None:
        self.seen: list[tuple] = []
        self.bounce = bounce
        self.critic_calls = 0

    def triage(self, text):
        self.seen.append(("triage", text))
        return AgentReply(payload=dict(EVIDENCE), tokens=0)

    def classify(self, text, note=""):
        self.seen.append(("classify", note))
        return AgentReply(payload=dict(LABEL), tokens=0)

    def critic(self, text, evidence, label):
        self.seen.append(("critic", dict(evidence), dict(label)))
        self.critic_calls += 1
        if self.bounce and self.critic_calls == 1:
            return AgentReply(
                payload={
                    "verdict": "challenge",
                    "axis": "region",
                    "rubric_rule": "Do not guess a region with no place stated.",
                    "evidence_gap": "The snippet names no location whatsoever.",
                },
                tokens=0,
            )
        return AgentReply(payload={"verdict": "accept"}, tokens=0)

    def critic_evidence(self, nth=0):
        return [e for e in self.seen if e[0] == "critic"][nth][1]

    def critic_label(self, nth=0):
        return [e for e in self.seen if e[0] == "critic"][nth][2]

    def notes(self):
        return [e[1] for e in self.seen if e[0] == "classify"]


# --- the corruption primitives --------------------------------------------


def test_first_clause_always_removes_something():
    assert first_clause("the Philippine Sea, east of Luzon") == "the Philippine Sea"
    assert first_clause("awarded a contract; worth $4M") == "awarded a contract"
    # No clause boundary: fall back to the first half rather than a no-op, which
    # would silently turn a truncation cell into a second null control.
    assert first_clause("one two three four") == "one two"
    assert first_clause("solo") == "solo"


@pytest.mark.parametrize(
    "drop,expected",
    [
        (DropType.EMPTY, ""),
        (DropType.TRUNCATE, "the Philippine Sea"),
        (DropType.NULL, "the Philippine Sea, east of Luzon"),
    ],
)
def test_corrupt_value_on_a_string(drop, expected):
    assert corrupt_value(EVIDENCE["region_evidence"], drop) == expected


def test_corrupt_value_is_list_aware():
    assert corrupt_value(["region", "category"], DropType.EMPTY) == []
    assert corrupt_value(["region", "category"], DropType.TRUNCATE) == ["region"]


def test_stale_without_a_donor_is_an_error_not_a_silent_noop():
    with pytest.raises(ValueError, match="donor"):
        corrupt_value("anything", DropType.STALE)


def test_corrupt_payload_never_mutates_the_producers_dict():
    # process_row appends the payload to the audit trail BY REFERENCE before the
    # critic runs, so an in-place edit would rewrite the record of what the
    # producer said -- the exact thing the experiment scores against.
    original = dict(EVIDENCE)
    cell = Cell(Edge.TRIAGE_TO_CRITIC, DropType.OMIT, "region_evidence", "region")
    corrupted = corrupt_payload(original, cell)
    assert "region_evidence" not in corrupted
    assert original == EVIDENCE


def test_corrupt_payload_on_a_field_the_payload_lacks_is_a_noop():
    cell = Cell(Edge.TRIAGE_TO_CRITIC, DropType.OMIT, "region_evidence", "region")
    assert corrupt_payload({"category_evidence": "x"}, cell) == {
        "category_evidence": "x"
    }


# --- the wrapper, per edge and per drop type ------------------------------


@pytest.mark.parametrize("drop", [DropType.OMIT, DropType.EMPTY, DropType.TRUNCATE])
@pytest.mark.parametrize("evidence_field", list(l4_inject.EVIDENCE_FIELDS))
def test_triage_to_critic_corrupts_only_what_the_critic_sees(drop, evidence_field):
    spy = SpyBackend()
    cell = Cell(Edge.TRIAGE_TO_CRITIC, drop, evidence_field)
    backend = InjectingBackend(spy, cell)
    label, events, _ = process_row(backend, "a snippet")

    seen = spy.critic_evidence()
    if drop is DropType.OMIT:
        assert evidence_field not in seen
    else:
        assert seen[evidence_field] != EVIDENCE[evidence_field]
    # Every other field crosses intact, and the audit trail still records what
    # triage actually said.
    for other in l4_inject.EVIDENCE_FIELDS:
        if other != evidence_field:
            assert seen[other] == EVIDENCE[other]
    assert events[0]["payload"] == EVIDENCE
    assert {k: v for k, v in label.items() if k != "l4_status"} == LABEL
    assert backend.injections == 1


def test_triage_to_critic_stale_substitutes_a_donor_value():
    spy = SpyBackend()
    cell = Cell(Edge.TRIAGE_TO_CRITIC, DropType.STALE, "region_evidence", "region")
    process_row(InjectingBackend(spy, cell, DONOR), "a snippet")
    assert spy.critic_evidence()["region_evidence"] == "Ramstein Air Base, Germany"


@pytest.mark.parametrize("drop", [DropType.OMIT, DropType.EMPTY])
@pytest.mark.parametrize("label_field", list(l4_inject.LABEL_FIELDS))
def test_classify_to_critic_blinds_the_verifier_not_the_shipped_label(
    drop, label_field
):
    spy = SpyBackend()
    cell = Cell(Edge.CLASSIFY_TO_CRITIC, drop, label_field, label_field)
    label, events, _ = process_row(InjectingBackend(spy, cell), "a snippet")

    seen = spy.critic_label()
    if drop is DropType.OMIT:
        assert label_field not in seen
    else:
        assert seen[label_field] == ""
    # The distinction that makes this context loss rather than answer tampering.
    assert {k: v for k, v in label.items() if k != "l4_status"} == LABEL
    assert events[1]["payload"] == LABEL


def test_classify_to_critic_stale_shows_the_critic_another_rows_region():
    spy = SpyBackend()
    cell = Cell(Edge.CLASSIFY_TO_CRITIC, DropType.STALE, "region", "region")
    process_row(InjectingBackend(spy, cell, DONOR), "a snippet")
    assert spy.critic_label()["region"] == "europe"


def test_stale_with_a_donor_missing_the_field_raises():
    spy = SpyBackend()
    cell = Cell(Edge.CLASSIFY_TO_CRITIC, DropType.STALE, "region", "region")
    with pytest.raises(ValueError, match="donor carries no"):
        process_row(InjectingBackend(spy, cell, Donor(label={})), "a snippet")


@pytest.mark.parametrize(
    "drop,check",
    [
        (DropType.OMIT, lambda note: note == ""),
        (DropType.TRUNCATE, lambda note: note.startswith("A reviewer has flagged")),
        (DropType.STALE, lambda note: "no contract verb" in note),
    ],
)
def test_the_backward_edge_is_the_reviewer_note(drop, check):
    spy = SpyBackend(bounce=True)
    cell = Cell(Edge.CRITIC_TO_CLASSIFY, drop)
    backend = InjectingBackend(spy, cell, DONOR)
    process_row(backend, "a snippet")

    first_note, bounce_note = spy.notes()
    assert first_note == ""  # the forward classify is never touched
    assert check(bounce_note)
    assert backend.injections == 1


def test_the_backward_edge_never_fires_on_a_row_that_does_not_bounce():
    # The single largest n cost in the design, pinned so it cannot be forgotten
    # when the power analysis is read.
    spy = SpyBackend(bounce=False)
    backend = InjectingBackend(spy, Cell(Edge.CRITIC_TO_CLASSIFY, DropType.OMIT), DONOR)
    process_row(backend, "a snippet")
    assert backend.injections == 0
    assert spy.notes() == [""]


def test_the_null_control_changes_nothing_at_all():
    spy = SpyBackend(bounce=True)
    control = SpyBackend(bounce=True)
    process_row(InjectingBackend(spy, NULL_CONTROL), "a snippet")
    process_row(control, "a snippet")
    assert spy.seen == control.seen


def test_the_wrapper_satisfies_the_backend_protocol_structurally():
    # L4Backend is not @runtime_checkable and this branch does not edit
    # l4_pipeline.py to make it so, so the conformance check is what a structural
    # Protocol actually means: same methods, same signatures.
    import inspect

    backend = InjectingBackend(SpyBackend(), NULL_CONTROL)
    for method in ("triage", "classify", "critic"):
        assert inspect.signature(getattr(backend, method)) == inspect.signature(
            getattr(l4_pipeline.DryRunBackend(), method)
        )


# --- the graph's shape, asserted rather than assumed ----------------------


def test_the_triage_to_classify_edge_does_not_exist():
    # The absence IS the finding: classify() takes no evidence argument, so no
    # state crosses from triage to classify and no cell can target it.
    import inspect

    signature = inspect.signature(l4_pipeline.L4Backend.classify)
    assert list(signature.parameters) == ["self", "text", "note"]
    assert ABSENT_EDGE not in {edge.value for edge in Edge}
    assert ABSENT_EDGE + "/*/*" in l4_inject.infeasible_cells()


# --- the pre-registration, pinned against the code ------------------------


def test_the_registered_matrix_matches_the_pre_registration():
    # SYS-019's move applied to this experiment's own contract: the spec and the
    # code cannot drift apart silently, because post-hoc cell selection is
    # exactly what a pre-registration is for.
    with open(SPEC_PATH, encoding="utf-8") as handle:
        spec = handle.read()
    registered = {cell.name for cell in CELLS}
    quoted = set(
        re.findall(r"`((?:triage|classify|critic)->[a-z]+/[a-z_]+/[a-z]+)`", spec)
    )
    assert registered == quoted
    assert len(CELLS) == len(registered)  # no duplicate cells


def test_the_spec_states_that_nothing_has_been_run():
    with open(SPEC_PATH, encoding="utf-8") as handle:
        spec = handle.read()
    assert "No arm has been run" in spec


def test_every_live_cell_is_distinct_and_the_control_is_inert():
    assert len(set(LIVE_CELLS)) == len(LIVE_CELLS)
    assert NULL_CONTROL not in LIVE_CELLS
    assert NULL_CONTROL.drop is DropType.NULL


# --- the outcome partition -------------------------------------------------


def test_all_five_buckets_are_reachable():
    reached = {
        classify_outcome("global", "global", "global", caught=False, crashed=True),
        classify_outcome("global", "americas", "global", caught=True),
        classify_outcome("global", "americas", "americas", caught=False),
        classify_outcome("global", "americas", "global", caught=False),
        classify_outcome("global", "global", "europe", caught=False),
    }
    assert reached == set(InjectionOutcome)


def test_caught_outranks_absorbed_when_the_guard_repaired_the_drop():
    # The critic challenged and the bounce restored the control's answer. That is
    # a working guard, not an inert edge.
    assert (
        classify_outcome("global", "global", "global", caught=True)
        is InjectionOutcome.CAUGHT
    )


def test_a_guard_that_fired_and_still_shipped_wrong_is_contamination():
    assert (
        classify_outcome("global", "global", "europe", caught=True)
        is InjectionOutcome.CONTAMINATED
    )


def test_absorbed_covers_a_control_that_was_already_wrong():
    # The drop is not what made it wrong, so it is not contamination.
    assert (
        classify_outcome("global", "europe", "europe", caught=False)
        is InjectionOutcome.ABSORBED
    )


def test_guard_fired_needs_the_affected_axis():
    region_cell = Cell(
        Edge.TRIAGE_TO_CRITIC, DropType.OMIT, "region_evidence", "region"
    )
    assert guard_fired(region_cell, ["region"])
    assert not guard_fired(region_cell, ["category"])
    # A cell with no single affected axis takes any valid challenge.
    axisless = Cell(Edge.TRIAGE_TO_CRITIC, DropType.OMIT, "ambiguous_axes", None)
    assert guard_fired(axisless, ["category"])
    assert not guard_fired(axisless, [])


def test_valid_challenge_axes_ignores_a_challenge_the_pipeline_discards():
    events = [
        {"event": "critic", "payload": {"verdict": "challenge"}},  # no axis: invalid
        {
            "event": "critic_second",
            "payload": {
                "verdict": "challenge",
                "axis": "region",
                "rubric_rule": "a rule long enough to count",
                "evidence_gap": "a gap long enough to count",
            },
        },
        {"event": "critic", "payload": {"verdict": "accept"}},
    ]
    assert valid_challenge_axes(events) == ["region"]


def test_partition_counts_reports_empty_buckets_as_zero():
    counts = partition_counts([InjectionOutcome.ABSORBED])
    assert counts == {
        "caught": 0,
        "contaminated": 0,
        "absorbed": 1,
        "corrected": 0,
        "crashed": 0,
    }


def test_partition_rates_exclude_crashes_from_the_denominator():
    outcomes = [InjectionOutcome.CONTAMINATED] * 3 + [InjectionOutcome.CRASHED]
    rates = partition_rates(outcomes)
    assert rates["_meta"] == {"trials": 4, "scored": 3, "crashed": 1}
    assert rates["contaminated"]["rate"] == 1.0
    assert rates["crashed"]["rate"] is None  # counted, never rated
    assert rates["absorbed"]["low"] == 0.0


def test_partition_rates_with_nothing_scored_report_none_not_zero():
    rates = partition_rates([InjectionOutcome.CRASHED])
    assert rates["contaminated"]["rate"] is None


# --- secondaries -----------------------------------------------------------

ACCEPTED_EVENTS = [
    {"event": "triage", "payload": {}},
    {"event": "classify", "payload": {}},
    {"event": "critic", "payload": {"verdict": "accept"}},
]
BOUNCED_EVENTS = [
    {"event": "triage", "payload": {}},
    {"event": "classify", "payload": {}},
    {
        "event": "critic",
        "payload": {
            "verdict": "challenge",
            "axis": "region",
            "rubric_rule": "a rule long enough to count",
            "evidence_gap": "a gap long enough to count",
        },
    },
    {"event": "reclassify", "payload": {}},
    {"event": "critic_second", "payload": {"verdict": "accept"}},
]


def test_calls_after_injection_counts_from_the_consumer():
    assert calls_after_injection(ACCEPTED_EVENTS, Edge.TRIAGE_TO_CRITIC) == 1
    assert calls_after_injection(BOUNCED_EVENTS, Edge.TRIAGE_TO_CRITIC) == 3
    assert calls_after_injection(BOUNCED_EVENTS, Edge.CRITIC_TO_CLASSIFY) == 2
    # The backward edge never fired, so nothing was burned on corrupted input.
    assert calls_after_injection(ACCEPTED_EVENTS, Edge.CRITIC_TO_CLASSIFY) == 0


def test_detection_displacement_reports_never_rather_than_a_number():
    assert detection_displacement(ACCEPTED_EVENTS, Edge.TRIAGE_TO_CRITIC) is None
    assert detection_displacement(BOUNCED_EVENTS, Edge.TRIAGE_TO_CRITIC) == 0
    assert detection_displacement(BOUNCED_EVENTS, Edge.CRITIC_TO_CLASSIFY) is None


def test_displacement_distribution_keeps_the_never_mass():
    tally = displacement_distribution([0, 0, 1, None, None, None])
    assert tally == {"never": 3, "0": 2, "1": 1}
    # And offers no mean: averaging a bounded index over an undefined "never"
    # bucket is the number the partition exists to replace.
    assert not hasattr(l4_inject, "mean_displacement")


# --- the stable set --------------------------------------------------------


def _frame(rows):
    return pd.DataFrame(
        [
            {
                "id": i,
                "pred_category": c,
                "pred_operational_domain": d,
                "pred_region": r,
            }
            for i, (c, d, r) in enumerate(rows)
        ]
    )


def test_stable_ids_keeps_only_rows_identical_on_every_axis_and_every_run():
    run_a = _frame([("ops", "sea", "global"), ("ops", "sea", "global")])
    run_b = _frame([("ops", "sea", "global"), ("ops", "sea", "europe")])
    assert stable_ids([run_a, run_b]) == [0]
    # Region alone is what makes row 1 unstable, so filtering on category only
    # keeps it -- the axis argument is doing real work.
    assert stable_ids([run_a, run_b], ("category",)) == [0, 1]


def test_stable_ids_agrees_with_the_house_consistency_function():
    run_a = _frame([("ops", "sea", "global"), ("ops", "sea", "global")])
    run_b = _frame([("policy", "sea", "global"), ("ops", "sea", "global")])
    house = l4_inject.control_consistency([run_a, run_b])
    assert (
        house["category_consistency"]
        == len(stable_ids([run_a, run_b], ("category",))) / 2
    )
    assert house["stable_fraction"] == 0.5


def test_stable_ids_needs_at_least_one_run():
    with pytest.raises(ValueError, match="at least one"):
        stable_ids([])


# --- the offline path, end to end -----------------------------------------


def test_the_guarded_dry_run_backend_survives_every_omission_cell():
    # Unguarded, DryRunBackend subscripts evidence["region_evidence"] directly,
    # so every omission cell would report CRASHED and the offline harness would
    # measure nothing. The live path does not raise -- it json.dumps whatever it
    # was handed -- so the crash is the canned backend's artifact, not the
    # behaviour under test.
    for cell in CELLS:
        label, _, _ = process_row(
            InjectingBackend(GuardedDryRunBackend(), cell, DONOR),
            "A U.S. Navy ship departed on deployment.",
        )
        assert label["l4_status"] in {"accepted", "fixed", "contested", "fail_closed"}

    naked = Cell(Edge.TRIAGE_TO_CRITIC, DropType.OMIT, "region_evidence", "region")
    with pytest.raises(KeyError):
        process_row(InjectingBackend(l4_pipeline.DryRunBackend(), naked), "a ship")


def test_the_control_arm_never_touches_the_committed_adr020_record(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(l4_inject, "ARTIFACT_DIR", str(tmp_path))
    before = l4_pipeline.RUN_PATHS["gold"]
    paths = control_arm(runs=2, dry_run=True)
    assert l4_pipeline.RUN_PATHS["gold"] == before  # restored in a finally
    assert len(paths) == 2
    for path in paths:
        assert str(tmp_path) in path
        assert len(pd.read_csv(path)) == 54


def test_the_control_arm_restores_the_run_path_even_when_a_pass_raises(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(l4_inject, "ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(
        l4_inject, "run_pipeline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError())
    )
    before = l4_pipeline.RUN_PATHS["gold"]
    with pytest.raises(RuntimeError):
        control_arm(runs=1, dry_run=True)
    assert l4_pipeline.RUN_PATHS["gold"] == before


# --- the free reports ------------------------------------------------------


def test_the_cells_report_names_every_cell_and_prices_the_run():
    report = cells_table(stable_n=44)
    for cell in CELLS:
        assert cell.name in report
    assert "No arm has been run" in report
    assert "TOTAL" in report


def test_the_power_report_states_what_cannot_be_detected():
    report = power_table(stable_n=44)
    assert "minimum detectable contamination" in report
    assert "Bonferroni" in report
    assert "never 'no effect'" in report


def test_the_budget_prices_the_backward_edge_on_bounced_rows_only():
    budget = l4_inject.planned_calls(44)
    assert budget["total"] == budget["control"] + budget["injected"]
    # Backward-edge cells are cheaper than forward ones because they only fire
    # on the rows that bounce.
    forward_only = l4_inject.planned_calls(44)["injected"]
    monkey = [c for c in CELLS if c.edge is Edge.CRITIC_TO_CLASSIFY]
    assert monkey and forward_only < round(len(CELLS) * 44 * l4_inject.CALLS_PER_ROW)
