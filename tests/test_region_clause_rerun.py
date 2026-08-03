"""Tests for src/region_clause_rerun.py (the higher-power `global`-clause re-run).

Offline only. The live passes drive conftest's fake clients, so even the
prompt-plumbing assertions cost nothing.

The single most important test here is
``test_the_composed_prompt_is_byte_identical_to_the_arm_adr023_paid_for``. Everything
else this module does -- reusing 295 already-measured rows, splicing new rows onto
frozen ones, quoting a power figure computed from ADR-023's discordants -- is valid
only if the clause under test is *the same clause*. That test reads the committed
provenance sidecar from the paid run and checks the composed prompt against it, so the
claim is verified against an artifact rather than asserted in prose.

The second group that matters is the prompt-routing pair: the answer-key pass must go
out under the SHIPPED prompt and the candidate pass under the COMPOSED one. Getting
those backwards would produce a perfectly clean report in which the judge graded the
new rows under the clause it is supposed to be testing.
"""

import hashlib
import json
import os
import sys

import pandas as pd
import pytest

import gold_eval
import provenance
import region_clause_ab as ab
import region_clause_rerun as rr
from classify import SYSTEM_PROMPT
from gold_eval import JUDGE_MODEL, WORKHORSE_MODEL

CATS = ["operations", "technology", "procurement", "policy", "industry"]
DOMS = ["air", "land", "sea", "cyber", "multi", "space"]


# ---------------------------------------------------------------------------
# The clause: composed, placed, and proven to be the one that was measured.
# ---------------------------------------------------------------------------


def test_the_composed_prompt_is_byte_identical_to_the_arm_adr023_paid_for():
    """The chain that makes every reuse in this module legitimate.

    Read the digest out of the committed sidecar rather than trusting the module
    constant, so this fails if either the clause text drifts OR the constant is
    "corrected" to match a drifted clause.
    """
    with open(rr.FROZEN_CANDIDATE_PROVENANCE_PATH, encoding="utf-8") as handle:
        recorded = json.load(handle)["recorded"]["prompt_sha256"]
    composed = hashlib.sha256(rr.candidate_prompt().encode("utf-8")).hexdigest()
    assert composed == recorded
    assert rr.ADR023_CANDIDATE_PROMPT_SHA256 == recorded
    rr.assert_clause_reproduces_the_recorded_arm()


def test_the_shipped_prompt_still_does_not_carry_the_clause():
    """`main` ships the v3.0.0 prompt, and this module must not be why that changes.

    The counterpart pin in tests/test_region_clause_ab.py survived ADR-023's revert;
    this one states the same thing from the follow-up's side, because the follow-up is
    the next thing that would plausibly break it.
    """
    assert rr.REVISED_CLAUSE not in SYSTEM_PROMPT
    assert "A US institution is not an American theater" not in SYSTEM_PROMPT
    assert rr.candidate_prompt() != SYSTEM_PROMPT


def test_the_clause_lands_inside_the_region_rules_block_right_after_its_anchor():
    """Placement is load-bearing: l4_pipeline and optimize both freeze that block."""
    composed = rr.candidate_prompt()
    assert rr.ANCHOR_BULLET + "\n" + rr.REVISED_CLAUSE in composed
    assert composed.index(rr.REVISED_CLAUSE) < composed.index("Worked examples:")
    assert composed.count(rr.REVISED_CLAUSE) == 1


def test_apply_clause_refuses_an_anchor_it_cannot_place_against():
    """Zero matches means the rubric moved; several means the insertion is ambiguous."""
    with pytest.raises(ValueError, match="found 0"):
        rr.apply_clause("a prompt with no region rules at all")
    with pytest.raises(ValueError, match="found 2"):
        rr.apply_clause(rr.ANCHOR_BULLET + "\n" + rr.ANCHOR_BULLET)


def test_the_digest_guard_fires_when_the_clause_drifts(monkeypatch):
    """One character is enough, and the message has to say what to do about it."""
    monkeypatch.setattr(rr, "REVISED_CLAUSE", rr.REVISED_CLAUSE + " ")
    with pytest.raises(ValueError, match="NOT the one ADR-023 measured"):
        rr.assert_clause_reproduces_the_recorded_arm()


def test_the_candidate_fingerprint_describes_the_composed_classifier():
    """Not SYSTEM_PROMPT's -- otherwise the sidecar would claim the arms are the same."""
    fingerprint = rr.candidate_fingerprint()
    assert fingerprint["prompt_sha256"] == rr.ADR023_CANDIDATE_PROMPT_SHA256
    assert fingerprint["workhorse_model"] == WORKHORSE_MODEL
    live = provenance.fingerprint(SYSTEM_PROMPT, WORKHORSE_MODEL, JUDGE_MODEL)
    assert fingerprint["prompt_sha256"] != live["prompt_sha256"]


# ---------------------------------------------------------------------------
# Set assembly.
# ---------------------------------------------------------------------------


def _snippets(ids, text="a snippet about a carrier strike group"):
    return pd.DataFrame({"id": list(ids), "text": [f"{text} {i}" for i in ids]})


def test_the_combined_set_refuses_an_extension_that_reuses_a_frozen_id(
    tmp_path, monkeypatch
):
    """Ids join every artifact here; a collision mispairs prediction and answer."""
    frozen, extension = tmp_path / "frozen.csv", tmp_path / "ext.csv"
    _snippets(["s001", "s002"]).to_csv(frozen, index=False)
    _snippets(["s002", "s301"]).to_csv(extension, index=False)
    monkeypatch.setattr(rr, "SCALE_SET_PATH", str(frozen))
    monkeypatch.setattr(rr, "EXT_SET_PATH", str(extension))
    with pytest.raises(ValueError, match="reuses 1 id"):
        rr.load_combined_set()


def test_the_combined_set_is_the_frozen_set_when_no_extension_exists(
    tmp_path, monkeypatch
):
    """Before collection, this module still loads -- it just has nothing extra."""
    frozen = tmp_path / "frozen.csv"
    _snippets(["s001", "s002"]).to_csv(frozen, index=False)
    monkeypatch.setattr(rr, "SCALE_SET_PATH", str(frozen))
    monkeypatch.setattr(rr, "EXT_SET_PATH", str(tmp_path / "absent.csv"))
    assert list(rr.load_combined_set()["id"]) == ["s001", "s002"]


def test_the_extension_set_names_the_builder_when_it_is_missing(tmp_path, monkeypatch):
    """A missing file should point at the command that makes one, not just raise."""
    monkeypatch.setattr(rr, "EXT_SET_PATH", str(tmp_path / "absent.csv"))
    with pytest.raises(FileNotFoundError, match="extend_scale_set.py"):
        rr.extension_set()


# ---------------------------------------------------------------------------
# Guards on the spliced arms.
# ---------------------------------------------------------------------------


def _arm(ids, judge=True):
    frame = pd.DataFrame(
        {
            "id": list(ids),
            "pred_category": ["operations"] * len(ids),
            "pred_operational_domain": ["sea"] * len(ids),
            "pred_region": ["global"] * len(ids),
        }
    )
    if judge:
        frame["judge_category"] = "operations"
        frame["judge_operational_domain"] = "sea"
        frame["judge_region"] = "global"
    return frame


def test_completeness_catches_a_partial_arm_in_both_directions():
    """The batch path skips unparseable rows, so 'looks fine, is short' is the risk."""
    snippets = _snippets(["s001", "s002", "s003"])
    with pytest.raises(ValueError, match="1 missing"):
        rr.assert_complete(_arm(["s001", "s002"]), snippets, "arm.csv")
    with pytest.raises(ValueError, match="1 unexpected"):
        rr.assert_complete(_arm(["s001", "s002", "s003", "s999"]), snippets, "arm.csv")


def test_completeness_catches_an_appended_rerun():
    """Duplicated ids silently drop out of the pairing rather than failing it."""
    with pytest.raises(ValueError, match="repeats 1 id"):
        rr.assert_complete(
            _arm(["s001", "s001", "s002"]), _snippets(["s001", "s002"]), "arm.csv"
        )


def test_blank_labels_are_caught_on_every_label_column():
    """A hole in the key shrinks the comparison instead of failing it."""
    arm = _arm(["s001", "s002"])
    arm.loc[0, "judge_region"] = ""
    with pytest.raises(ValueError, match="blank 'judge_region'"):
        rr.assert_no_blank_labels(arm, "key.csv")


def test_frozen_arm_reuse_is_refused_when_a_sidecar_no_longer_matches(
    tmp_path, monkeypatch
):
    """Splicing onto rows a different classifier produced is the failure to prevent."""
    key_sidecar = tmp_path / "key.provenance.json"
    provenance.write(
        provenance.fingerprint("some other prompt", WORKHORSE_MODEL, JUDGE_MODEL),
        "key.csv",
        path=str(key_sidecar),
    )
    monkeypatch.setattr(rr, "FROZEN_KEY_PROVENANCE_PATH", str(key_sidecar))
    with pytest.raises(ValueError, match="different prompt or model"):
        rr.assert_frozen_arms_are_still_ours()


def test_the_frozen_arms_on_disk_pass_their_own_guard():
    """The committed ADR-022/ADR-023 sidecars must still describe this checkout.

    If this fails on `main`, the reuse this module is built on has silently expired --
    which is exactly the condition worth learning about from a test rather than from a
    600-row report.
    """
    rr.assert_frozen_arms_are_still_ours()


# ---------------------------------------------------------------------------
# The live passes: which prompt goes out on which call.
# ---------------------------------------------------------------------------


def _batch_env(tmp_path, monkeypatch, ids):
    """Point every write path at tmp_path and hand back the extension snippet set."""
    extension = tmp_path / "ext.csv"
    _snippets(ids).to_csv(extension, index=False)
    monkeypatch.setattr(rr, "EXT_SET_PATH", str(extension))
    monkeypatch.setattr(rr, "EXT_KEY_PATH", str(tmp_path / "key.csv"))
    monkeypatch.setattr(rr, "EXT_KEY_PROVENANCE_PATH", str(tmp_path / "key.prov.json"))
    monkeypatch.setattr(rr, "EXT_CANDIDATE_PATH", str(tmp_path / "cand.csv"))
    monkeypatch.setattr(
        rr, "EXT_CANDIDATE_PROVENANCE_PATH", str(tmp_path / "cand.prov.json")
    )
    return extension


def _payload():
    return {"category": "operations", "operational_domain": "sea", "region": "global"}


def test_the_candidate_pass_sends_the_composed_prompt(
    tmp_path, monkeypatch, batch_client
):
    """The arm under test must actually carry the clause on the wire."""
    _batch_env(tmp_path, monkeypatch, ["s301", "s302"])
    client = batch_client({"s301": _payload(), "s302": _payload()})
    monkeypatch.setattr(rr, "make_client", lambda: client)

    rr.run_candidate(batch=True)

    sent = client.messages.batches.created_requests
    assert len(sent) == 2
    for request in sent:
        assert request["params"]["system"][0]["text"] == rr.candidate_prompt()
        assert rr.REVISED_CLAUSE in request["params"]["system"][0]["text"]
    recorded = provenance.load(rr.EXT_CANDIDATE_PROVENANCE_PATH)["recorded"]
    assert recorded["prompt_sha256"] == rr.ADR023_CANDIDATE_PROMPT_SHA256


def test_the_answer_key_pass_sends_the_SHIPPED_prompt_to_both_models(
    tmp_path, monkeypatch, batch_client
):
    """The judge grades under the baseline prompt, or the key means two things.

    ``classify()`` defaults both models to ``SYSTEM_PROMPT``; this pins that the
    re-run does not quietly reroute the key pass through the candidate prompt to save
    a code path.
    """
    _batch_env(tmp_path, monkeypatch, ["s301"])
    client = batch_client({"s301__workhorse": _payload(), "s301__judge": _payload()})
    monkeypatch.setattr(rr, "make_client", lambda: client)

    rr.run_key(batch=True)

    sent = client.messages.batches.created_requests
    assert {request["params"]["model"] for request in sent} == {
        WORKHORSE_MODEL,
        JUDGE_MODEL,
    }
    for request in sent:
        assert request["params"]["system"][0]["text"] == SYSTEM_PROMPT
        assert rr.REVISED_CLAUSE not in request["params"]["system"][0]["text"]


def test_the_candidate_pass_refuses_before_spending_when_the_clause_drifted(
    tmp_path, monkeypatch
):
    """The digest guard runs ahead of make_client, so a drift costs nothing."""
    _batch_env(tmp_path, monkeypatch, ["s301"])
    monkeypatch.setattr(rr, "REVISED_CLAUSE", "- a different clause entirely.")

    def _explode():  # pragma: no cover - must never be reached
        raise AssertionError("a client was built despite the drift")

    monkeypatch.setattr(rr, "make_client", _explode)
    with pytest.raises(ValueError, match="NOT the one ADR-023 measured"):
        rr.run_candidate(batch=True)


def test_a_resume_across_a_classifier_change_is_refused_not_blended(
    tmp_path, monkeypatch
):
    """Half yesterday's prompt and half today's is a blend no fingerprint describes."""
    _batch_env(tmp_path, monkeypatch, ["s301", "s302"])
    _arm(["s301"], judge=False).to_csv(rr.EXT_CANDIDATE_PATH, index=False)
    provenance.write(
        provenance.fingerprint("yesterday's prompt", WORKHORSE_MODEL, JUDGE_MODEL),
        rr.EXT_CANDIDATE_PATH,
        path=rr.EXT_CANDIDATE_PROVENANCE_PATH,
    )
    with pytest.raises(ValueError, match="Cannot resume"):
        rr.run_candidate(batch=True)


def test_a_complete_extension_makes_no_calls(tmp_path, monkeypatch, capsys):
    """Re-running a finished pass must not re-buy it."""
    _batch_env(tmp_path, monkeypatch, ["s301"])
    _arm(["s301"], judge=False).to_csv(rr.EXT_CANDIDATE_PATH, index=False)
    provenance.write(
        rr.candidate_fingerprint(),
        rr.EXT_CANDIDATE_PATH,
        path=rr.EXT_CANDIDATE_PROVENANCE_PATH,
    )

    def _explode():  # pragma: no cover - must never be reached
        raise AssertionError("a client was built for an already-complete pass")

    monkeypatch.setattr(rr, "make_client", _explode)
    rr.run_candidate(batch=True)
    assert "already complete" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The report, and the pre-registered floor it enforces.
# ---------------------------------------------------------------------------


def _report_env(tmp_path, monkeypatch, n, fixed=0, broken=0):
    """A complete two-arm environment of `n` rows, with a controllable region effect.

    The first `fixed` rows are answer-key `global` that the baseline pulls to
    `americas` and the candidate fixes; the next `broken` rows are correct `americas`
    that the candidate drags to `global`. Everything else agrees.
    """
    ids = [f"s{i:03d}" for i in range(1, n + 1)]
    snippets = _snippets(ids)
    scale = tmp_path / "scale.csv"
    snippets.to_csv(scale, index=False)
    monkeypatch.setattr(rr, "SCALE_SET_PATH", str(scale))
    monkeypatch.setattr(rr, "EXT_SET_PATH", str(tmp_path / "absent.csv"))

    baseline, candidate = [], []
    for index, row_id in enumerate(ids):
        if index < fixed:
            judge, base, cand = "global", "americas", "global"
        elif index < fixed + broken:
            judge, base, cand = "americas", "americas", "global"
        else:
            judge, base, cand = "europe", "europe", "europe"
        baseline.append(
            {
                "id": row_id,
                "pred_category": "operations",
                "pred_operational_domain": "sea",
                "pred_region": base,
                "judge_category": "operations",
                "judge_operational_domain": "sea",
                "judge_region": judge,
            }
        )
        candidate.append(
            {
                "id": row_id,
                "pred_category": "operations",
                "pred_operational_domain": "sea",
                "pred_region": cand,
            }
        )

    key_path, cand_path = tmp_path / "key.csv", tmp_path / "cand.csv"
    pd.DataFrame(baseline).to_csv(key_path, index=False)
    pd.DataFrame(candidate).to_csv(cand_path, index=False)
    monkeypatch.setattr(rr, "FROZEN_KEY_PATH", str(key_path))
    monkeypatch.setattr(rr, "FROZEN_CANDIDATE_PATH", str(cand_path))
    monkeypatch.setattr(rr, "EXT_KEY_PATH", str(tmp_path / "absent_key.csv"))
    monkeypatch.setattr(rr, "EXT_CANDIDATE_PATH", str(tmp_path / "absent_cand.csv"))
    monkeypatch.setattr(rr, "REPORT_PATH", str(tmp_path / "report.txt"))
    monkeypatch.setattr(rr, "assert_frozen_arms_are_still_ours", lambda: None)


def test_the_report_refuses_below_the_pre_registered_floor(tmp_path, monkeypatch):
    """An underpowered run cannot decide the question, so the rule says do not spend.

    Enforced rather than printed: ADR-007's standing rule in this repo is that an
    unrun gate is not a pass, and a floor that only appears in prose is one of those.
    """
    _report_env(tmp_path, monkeypatch, n=rr.MIN_EFFECTIVE_N - 1, fixed=12, broken=7)
    with pytest.raises(ValueError, match="below the pre-registered floor"):
        rr.report()


def test_the_report_scores_the_combined_arms_once_the_floor_is_cleared(
    tmp_path, monkeypatch
):
    """The happy path, and the numbers a reader would check first."""
    _report_env(tmp_path, monkeypatch, n=rr.MIN_EFFECTIVE_N, fixed=20, broken=4)
    text = rr.report()
    assert "HIGHER-POWER RE-RUN" in text
    assert f"Snippets scored   : {rr.MIN_EFFECTIVE_N}" in text
    assert "F (named pulls fixed)           : 20" in text
    assert "B (correct rows dragged global) : 4" in text
    assert "Design power" in text
    assert rr.ADR023_CANDIDATE_PROMPT_SHA256[:16] in text
    with open(rr.REPORT_PATH, encoding="utf-8") as handle:
        assert handle.read() == text


def test_the_report_refuses_a_partial_arm_rather_than_scoring_it(tmp_path, monkeypatch):
    """Rule 4 of every version of this experiment: harness health is a gate."""
    _report_env(tmp_path, monkeypatch, n=rr.MIN_EFFECTIVE_N, fixed=20, broken=4)
    trimmed = pd.read_csv(rr.FROZEN_CANDIDATE_PATH).iloc[:-1]
    trimmed.to_csv(rr.FROZEN_CANDIDATE_PATH, index=False)
    with pytest.raises(ValueError, match="does not cover the snippet set"):
        rr.report()


# ---------------------------------------------------------------------------
# The gold arm (step 5 / rule 3).
#
# Three properties carry this whole path, and each has its own test below:
#   1. it runs under the CLAUSE, never the shipped prompt (the old step 5's defect);
#   2. it CANNOT write the published gold record (the old step 5's blast radius);
#   3. it makes NO judge call (the old step 5's doubled cost).
# ---------------------------------------------------------------------------


# (human label, baseline prediction, candidate prediction) per row, region axis.
_FIXED = ("global", "americas", "global")  # named pull the clause fixes
_UNFIXED = ("global", "americas", "americas")  # named pull it misses
_BROKEN = ("americas", "americas", "global")  # correct row dragged to `global`
_AGREE = ("europe", "europe", "europe")

# candidate region = 9/10 = 90.0% >= the 87.0% bar
_PASS_SPEC = [_FIXED] * 3 + [_AGREE] * 6 + [_BROKEN]
# candidate region = 7/10 = 70.0% < the 87.0% bar
_FAIL_SPEC = [_FIXED] * 3 + [_AGREE] * 4 + [_BROKEN] * 3


def _gold_env(tmp_path, monkeypatch, spec, write_candidate=True):
    """A complete gold environment: human labels, published baseline, clause arm.

    Every path this arm reads or writes is repointed into tmp_path, so a test can
    never touch the real published record even if a guard were removed.
    """
    ids = [f"g{i:03d}" for i in range(1, len(spec) + 1)]
    gold, baseline, candidate = [], [], []
    for row_id, (human, base, cand) in zip(ids, spec):
        gold.append(
            {
                "id": row_id,
                "text": f"a snippet about a carrier strike group {row_id}",
                "category": "operations",
                "domain": "sea",
                "region": human,
            }
        )
        baseline.append(
            {
                "id": row_id,
                "pred_category": "operations",
                "pred_operational_domain": "sea",
                "pred_region": base,
                "judge_category": "operations",
                "judge_operational_domain": "sea",
                "judge_region": human,
            }
        )
        candidate.append(
            {
                "id": row_id,
                "pred_category": "operations",
                "pred_operational_domain": "sea",
                "pred_region": cand,
            }
        )

    gold_path = tmp_path / "gold.csv"
    base_path = tmp_path / "gold_base.csv"
    base_prov = tmp_path / "gold_base.provenance.json"
    cand_path = tmp_path / "gold_cand.csv"
    cand_prov = tmp_path / "gold_cand.provenance.json"
    pd.DataFrame(gold).to_csv(gold_path, index=False)
    pd.DataFrame(baseline).to_csv(base_path, index=False)
    provenance.write(
        provenance.fingerprint(SYSTEM_PROMPT, WORKHORSE_MODEL, JUDGE_MODEL),
        str(base_path),
        path=str(base_prov),
    )
    if write_candidate:
        pd.DataFrame(candidate).to_csv(cand_path, index=False)
        provenance.write(
            rr.candidate_fingerprint(), str(cand_path), path=str(cand_prov)
        )

    monkeypatch.setattr(rr, "GOLD_SET_PATH", str(gold_path))
    monkeypatch.setattr(rr, "GOLD_BASELINE_PATH", str(base_path))
    monkeypatch.setattr(rr, "GOLD_BASELINE_PROVENANCE_PATH", str(base_prov))
    monkeypatch.setattr(rr, "GOLD_CANDIDATE_PATH", str(cand_path))
    monkeypatch.setattr(rr, "GOLD_CANDIDATE_PROVENANCE_PATH", str(cand_prov))
    monkeypatch.setattr(rr, "GOLD_REPORT_PATH", str(tmp_path / "gold_report.txt"))
    monkeypatch.setattr(
        rr, "ADR023_GOLD_CANDIDATE_PATH", str(tmp_path / "no_prior_round.csv")
    )
    return gold_path


# --- property 1: the clause, never the shipped prompt ----------------------


def test_the_gold_pass_sends_the_clause_applied_prompt(
    tmp_path, monkeypatch, batch_client
):
    """The arm under test must carry the clause on the wire, or it measures nothing.

    This is the defect the old step 5 had: it re-ran `gold_eval` under the SHIPPED
    prompt, which on `main` carries no clause, so it would have re-measured the
    baseline and reported it as the candidate.
    """
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC, write_candidate=False)
    ids = [f"g{i:03d}" for i in range(1, len(_PASS_SPEC) + 1)]
    client = batch_client({row_id: _payload() for row_id in ids})
    monkeypatch.setattr(rr, "make_client", lambda: client)

    rr.run_gold(batch=True)

    sent = client.messages.batches.created_requests
    for request in sent:
        assert request["params"]["system"][0]["text"] == rr.candidate_prompt()
        assert rr.REVISED_CLAUSE in request["params"]["system"][0]["text"]
        assert request["params"]["system"][0]["text"] != SYSTEM_PROMPT
    recorded = provenance.load(rr.GOLD_CANDIDATE_PROVENANCE_PATH)["recorded"]
    assert recorded["prompt_sha256"] == rr.ADR023_CANDIDATE_PROMPT_SHA256


def test_the_clause_assertion_refuses_the_shipped_prompt_outright():
    """The assertion itself, isolated from the digest pin that also guards it."""
    with pytest.raises(ValueError, match="does not carry the clause"):
        rr.assert_prompt_carries_the_clause(SYSTEM_PROMPT)
    with pytest.raises(ValueError, match="does not carry the clause"):
        rr.assert_prompt_carries_the_clause("some other prompt entirely")
    rr.assert_prompt_carries_the_clause(rr.candidate_prompt())


def test_the_gold_pass_refuses_before_spending_when_the_clause_drifted(
    tmp_path, monkeypatch
):
    """The digest pin runs ahead of make_client, so a drift costs nothing."""
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC, write_candidate=False)
    monkeypatch.setattr(rr, "REVISED_CLAUSE", "- a different clause entirely.")

    def _explode():  # pragma: no cover - must never be reached
        raise AssertionError("a client was built despite the drift")

    monkeypatch.setattr(rr, "make_client", _explode)
    with pytest.raises(ValueError, match="NOT the one ADR-023 measured"):
        rr.run_gold()


def test_the_gold_report_refuses_an_arm_produced_by_the_shipped_prompt(
    tmp_path, monkeypatch
):
    """The report-side half of "this cannot run under the shipped prompt".

    A CSV hand-placed at the candidate path, or left behind by some other harness,
    is refused at scoring time even though no call was made to produce it.
    """
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC)
    provenance.write(
        provenance.fingerprint(SYSTEM_PROMPT, WORKHORSE_MODEL, JUDGE_MODEL),
        rr.GOLD_CANDIDATE_PATH,
        path=rr.GOLD_CANDIDATE_PROVENANCE_PATH,
    )
    with pytest.raises(ValueError, match="not produced by the clause-applied prompt"):
        rr.gold_report()


def test_the_gold_report_refuses_a_baseline_the_shipped_prompt_did_not_make(
    tmp_path, monkeypatch
):
    """Rule 3 compares to the PUBLISHED 87.0%, so that half must be the shipped arm."""
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC)
    provenance.write(
        provenance.fingerprint("some other prompt", WORKHORSE_MODEL, JUDGE_MODEL),
        rr.GOLD_BASELINE_PATH,
        path=rr.GOLD_BASELINE_PROVENANCE_PATH,
    )
    with pytest.raises(ValueError, match="different prompt or model"):
        rr.gold_report()


# --- property 2: the published gold record is unwritable -------------------


@pytest.mark.parametrize("frozen", rr.FROZEN_GOLD_ARTIFACTS)
def test_no_frozen_or_published_gold_artifact_can_be_written(frozen):
    """Every published/frozen destination is refused, by resolved path not by string."""
    with pytest.raises(ValueError, match="published or frozen record"):
        rr.assert_writable_gold_artifact(frozen)


def test_the_published_record_is_refused_however_the_path_is_spelled():
    """A guard that only compares literals is one `./` away from being bypassed."""
    for spelling in (
        "evals/../evals/gold_predictions_v3.csv",
        "./evals/gold_predictions_v3.csv",
        os.path.abspath("evals/gold_predictions_v3.csv"),
    ):
        with pytest.raises(ValueError, match="published or frozen record"):
            rr.assert_writable_gold_artifact(spelling)


@pytest.mark.skipif(
    os.sep != "\\", reason="backslash is a path separator on Windows only"
)
def test_the_published_record_is_refused_in_windows_spellings_too():
    r"""Separator and case only fold on Windows.

    Deliberately NOT asserted cross-platform: on POSIX a backslash is a legal
    character *inside* a filename, so ``evals\\gold_predictions_v3.csv`` really is a
    different file there and refusing it would be the bug.
    """
    for spelling in (
        "evals\\gold_predictions_v3.csv",
        "EVALS/GOLD_PREDICTIONS_V3.CSV",
    ):
        with pytest.raises(ValueError, match="published or frozen record"):
            rr.assert_writable_gold_artifact(spelling)


def test_this_rounds_gold_paths_are_new_and_collide_with_nothing_frozen():
    """The naming claim, checked rather than asserted in a docstring."""
    for path in (
        rr.GOLD_CANDIDATE_PATH,
        rr.GOLD_CANDIDATE_PROVENANCE_PATH,
        rr.GOLD_REPORT_PATH,
    ):
        rr.assert_writable_gold_artifact(path)
        assert path.startswith("evals/region_clause_gold_rerun")
    assert rr.GOLD_CANDIDATE_PATH != rr.ADR023_GOLD_CANDIDATE_PATH
    assert rr.GOLD_BASELINE_PATH == gold_eval.PREDS_PATH


def test_the_gold_pass_refuses_before_spending_if_it_would_write_the_published_record(
    tmp_path, monkeypatch
):
    """The end-to-end version: a mis-set constant stops the run, it does not delete."""
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC, write_candidate=False)
    monkeypatch.setattr(rr, "GOLD_CANDIDATE_PATH", gold_eval.PREDS_PATH)

    def _explode():  # pragma: no cover - must never be reached
        raise AssertionError(
            "a client was built for a run aimed at the published record"
        )

    monkeypatch.setattr(rr, "make_client", _explode)
    with pytest.raises(ValueError, match="published or frozen record"):
        rr.run_gold()


def test_the_published_gold_record_is_untouched_by_a_whole_run_and_report(
    tmp_path, monkeypatch, batch_client
):
    """The property San actually cares about: the bytes on disk do not move."""
    before = {
        path: open(path, "rb").read()
        for path in (gold_eval.PREDS_PATH, provenance.PROVENANCE_PATH)
    }
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC, write_candidate=False)
    ids = [f"g{i:03d}" for i in range(1, len(_PASS_SPEC) + 1)]
    monkeypatch.setattr(
        rr, "make_client", lambda: batch_client({i: _payload() for i in ids})
    )
    rr.run_gold(batch=True)
    rr.gold_report()
    for path, content in before.items():
        assert open(path, "rb").read() == content


# --- property 3: no judge call, ever ---------------------------------------


def test_the_gold_pass_makes_one_workhorse_call_per_row_and_no_judge_call(
    tmp_path, monkeypatch, batch_client
):
    """54 calls, not 108. The judge answers no part of a human-graded check."""
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC, write_candidate=False)
    ids = [f"g{i:03d}" for i in range(1, len(_PASS_SPEC) + 1)]
    client = batch_client({row_id: _payload() for row_id in ids})
    monkeypatch.setattr(rr, "make_client", lambda: client)

    rr.run_gold(batch=True)

    sent = client.messages.batches.created_requests
    assert len(sent) == len(ids)  # exactly one request per row, not two
    assert {request["params"]["model"] for request in sent} == {WORKHORSE_MODEL}
    assert JUDGE_MODEL not in {request["params"]["model"] for request in sent}


def test_the_synchronous_gold_pass_also_never_reaches_the_judge(tmp_path, monkeypatch):
    """The batch and sync paths are different call builders; both need the pin."""
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC, write_candidate=False)
    calls = []

    def _record(client, text, model, **kwargs):
        calls.append((model, kwargs.get("system_prompt")))
        return _payload()

    monkeypatch.setattr(ab, "classify_retry", _record)
    monkeypatch.setattr(ab, "SLEEP_BETWEEN_CALLS", 0)
    monkeypatch.setattr(rr, "make_client", lambda: object())

    rr.run_gold()

    assert len(calls) == len(_PASS_SPEC)
    assert {model for model, _ in calls} == {WORKHORSE_MODEL}
    assert {prompt for _, prompt in calls} == {rr.candidate_prompt()}


# --- rule 3 itself ---------------------------------------------------------


def test_rule_three_is_computed_against_the_human_labels(tmp_path, monkeypatch):
    """The arithmetic, on a fixture whose expected answer is countable by hand."""
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC)
    gold = gold_eval.load_gold(rr.GOLD_SET_PATH)
    import paired_compare

    scores = rr.gold_comparison(
        gold,
        paired_compare.read_predictions(rr.GOLD_BASELINE_PATH),
        paired_compare.read_predictions(rr.GOLD_CANDIDATE_PATH),
    )
    assert scores["n"] == 10
    assert scores["region_baseline"] == pytest.approx(0.7)  # 6 agree + 1 broken-row
    assert scores["region_candidate"] == pytest.approx(0.9)  # 3 fixed + 6 agree
    assert scores["fixed_ids"] == ["g001", "g002", "g003"]
    assert scores["broken_ids"] == ["g010"]
    assert scores["named_pulls"] == 3
    assert scores["B_ids"] == ["g010"]
    # Category and domain are untouched in the fixture -- secondary context only.
    assert scores["category_candidate"] == pytest.approx(1.0)


def test_the_gold_report_states_the_bar_the_verdict_and_the_adoption_caveat(
    tmp_path, monkeypatch
):
    """A pass, and every claim a reader would check first."""
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC)
    text = rr.gold_report()
    assert "RULE 3 (first half): PASSES" in text
    assert "90.0%" in text and "87.0%" in text
    assert "ZERO judge calls" in text
    assert "ADOPTION-time questions" in text
    assert "g001, g002, g003" in text  # fixed ids
    assert rr.ADR023_CANDIDATE_PROMPT_SHA256[:16] in text
    with open(rr.GOLD_REPORT_PATH, encoding="utf-8") as handle:
        assert handle.read() == text


def test_the_gold_report_says_FAILS_when_the_bar_is_missed(tmp_path, monkeypatch):
    """The bar has to be able to fail, or reporting it is decoration."""
    _gold_env(tmp_path, monkeypatch, _FAIL_SPEC)
    text = rr.gold_report()
    assert "RULE 3 (first half): FAILS" in text
    assert "70.0%" in text


def test_the_gold_report_carries_the_prior_rounds_number_when_it_is_present(
    tmp_path, monkeypatch
):
    """ADR-023 already measured this byte-identical clause on these same rows."""
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC)
    prior = pd.read_csv(rr.GOLD_CANDIDATE_PATH)
    prior_path = tmp_path / "prior_round.csv"
    prior.to_csv(prior_path, index=False)
    monkeypatch.setattr(rr, "ADR023_GOLD_CANDIDATE_PATH", str(prior_path))
    assert "Prior round, same byte-identical clause" in rr.gold_report()


def test_the_gold_report_refuses_a_partial_arm_rather_than_scoring_it(
    tmp_path, monkeypatch
):
    """Same rule-4 logic as the scale arm: a short arm is a shrunken comparison."""
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC)
    pd.read_csv(rr.GOLD_CANDIDATE_PATH).iloc[:-1].to_csv(
        rr.GOLD_CANDIDATE_PATH, index=False
    )
    with pytest.raises(ValueError, match="does not cover the snippet set"):
        rr.gold_report()


def test_a_complete_gold_arm_makes_no_calls(tmp_path, monkeypatch, capsys):
    """Re-running a finished pass must not re-buy it."""
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC)

    def _explode():  # pragma: no cover - must never be reached
        raise AssertionError("a client was built for an already-complete pass")

    monkeypatch.setattr(rr, "make_client", _explode)
    rr.run_gold()
    assert "already complete" in capsys.readouterr().out


# --- the CLI ---------------------------------------------------------------


def test_neither_report_flag_ever_builds_a_client(tmp_path, monkeypatch):
    """The offline guarantee, checked through main() rather than the functions."""
    _report_env(tmp_path, monkeypatch, n=rr.MIN_EFFECTIVE_N, fixed=20, broken=4)
    _gold_env(tmp_path, monkeypatch, _PASS_SPEC)

    def _explode():  # pragma: no cover - must never be reached
        raise AssertionError("an offline report built an API client")

    monkeypatch.setattr(rr, "make_client", _explode)
    monkeypatch.setattr(
        sys, "argv", ["region_clause_rerun.py", "--report", "--gold-report"]
    )
    rr.main()


def test_the_cli_rejects_batch_without_a_live_flag(monkeypatch):
    """`--batch --gold-report` would read as "cheaper report" and mean nothing."""
    monkeypatch.setattr(
        sys, "argv", ["region_clause_rerun.py", "--batch", "--gold-report"]
    )
    with pytest.raises(SystemExit):
        rr.main()


def test_the_cli_still_refuses_to_do_nothing(monkeypatch):
    """And its message now names the two new flags."""
    monkeypatch.setattr(sys, "argv", ["region_clause_rerun.py"])
    with pytest.raises(SystemExit):
        rr.main()
