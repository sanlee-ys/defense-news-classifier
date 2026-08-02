"""The higher-power re-run of the ADR-023 `global`-boundary clause A/B.

WHAT ADR-023 LEFT OPEN. The clause fixed 12 of 17 named `global` pulls and moved
scale region 88.5% -> 92.2%, but landed at **McNemar p=0.0522** against a
pre-registered p<0.05, so the rule said revert and the rule was honored. The ADR
then named its own condition for re-testing: *"a higher-power ruler, and
essentially nothing else."* ``src/mcnemar_power.py`` turns that phrase into
numbers -- at n=295 the completed design had about **49%** power against the
effect it observed, which is a coin flip. This module is the harness that runs the
same clause against an expanded ruler.

THE FOUR THINGS THAT MAKE THIS DECIDABLE RATHER THAN A RE-ROLL
==============================================================

**1. The clause is applied at run time, and `main` never carries it.** ADR-023's
arm was produced on a branch that edited ``classify.SYSTEM_PROMPT``, which cost
that branch a red CI (four provenance-pinned tests plus the offline gate) and made
"is the clause shipped?" a question about which commit you were standing on. Here
:func:`candidate_prompt` composes the candidate arm's prompt in memory from the
live ``SYSTEM_PROMPT`` plus :data:`REVISED_CLAUSE`, and passes it down the shared
call path. ``classify.SYSTEM_PROMPT`` is byte-identical to the shipped prompt on
this branch and on every branch. ``tests/test_region_clause_ab.py`` still pins the
clause's *absence* from the shipped prompt, and that pin is now unconditional
rather than a thing that had to be restored after an experiment.

**2. The clause is not retyped -- it is proven identical to the one that ran.**
:data:`ADR023_CANDIDATE_PROMPT_SHA256` is the fingerprint
``evals/region_clause_candidate.provenance.json`` recorded during the paid ADR-023
run. :func:`assert_clause_reproduces_the_recorded_arm` recomputes
``sha256(candidate_prompt())`` and refuses to run if it differs. So the clause
under test is not "the clause as I remember typing it" -- it is, byte for byte,
the prompt that produced the 19/8 discordants this follow-up is powered against.
That check is also what makes reuse of the frozen arms legitimate (point 3), and
it fires if a future edit to ``SYSTEM_PROMPT`` silently changes the composition.

**3. The 295 rows already measured are reused, not re-bought.** Both arms and the
answer key for ``s001..s300`` are committed artifacts produced by exactly the
prompts and models this run uses, so re-running them would spend ~900 calls to
reproduce numbers already on disk -- and, worse, would let run-to-run sampling
noise move the half of the experiment that is supposed to be fixed. Only the NEW
snippets are classified: three calls each (baseline workhorse, Opus judge,
candidate workhorse). The reuse is guarded, not assumed --
:func:`assert_frozen_arms_are_still_ours` checks both sidecars against the live
fingerprints before a single row is scored.

**4. The judge configuration is untouched.** New answer-key rows go through
``gold_eval.run_predictions`` unchanged, under the *baseline* prompt -- the same
configuration that scored 100.0% region agreement against the human gold 54 and
earned the judge its answer-key role (ADR-014). This is the second, quieter reason
the clause must not live in ``SYSTEM_PROMPT``: ``classify()`` defaults BOTH models
to it, so a run with the clause installed globally would grade the new rows under
the candidate prompt while the frozen 295 stayed graded under the baseline. The
answer key would then mean two different things in one file.

WHAT IS NEVER TOUCHED. ``data/scale/scale_set.csv``, ``evals/scale_predictions_v3.csv``
and its sidecar, ``evals/region_clause_candidate.csv`` and its sidecar,
``evals/region_clause_ab.txt``, the gold set, ``evals/metrics.json``,
``evals/thresholds.toml``, and ``classify.SYSTEM_PROMPT``. New snippets land in a
NEW file (``data/scale/scale_set_ext.csv``) rather than being appended to the
frozen set, because appending would silently redefine what every committed
``s001..s300`` artifact is a measurement *of* -- and would break
``region_clause_ab``'s answer-key completeness guard, which requires the key to
cover exactly the committed scale set.

Run -- every live pass is owner-driven; the report is free and offline:

    uv run --env-file .env python src/region_clause_rerun.py --run-key --batch
    uv run --env-file .env python src/region_clause_rerun.py --run-candidate --batch
    uv run python src/region_clause_rerun.py --report

The decision rule this measures against is pre-registered in
``docs/specs/global-boundary-clause-rerun.md`` and is canonical there.
"""

from __future__ import annotations

import argparse
import hashlib
import os

import pandas as pd

import mcnemar_power
import paired_compare
import provenance
import region_clause_ab as ab
import scale_eval
from classify import SYSTEM_PROMPT, make_client
from gold_eval import (
    JUDGE_MODEL,
    WORKHORSE_MODEL,
    run_predictions,
    run_predictions_batch,
)
from run_isolation import atomic_write_text

# ---------------------------------------------------------------------------
# The clause under test, and its proof of identity.
# ---------------------------------------------------------------------------

# The bullet the clause is inserted AFTER. Placement is load-bearing and was
# argued in the ADR-023 spec: `l4_pipeline` embeds extract_region_block(...)
# verbatim and `optimize.region_rubric_violations` freezes that same block, so a
# clause outside the region rules would be invisible to both. Spelled out in full
# rather than matched by a prefix, so a reword of the anchor bullet fails loudly
# here instead of silently relocating the clause.
ANCHOR_BULLET = (
    "- A concrete identifiable location makes an anchor even at home: training at a "
    "named US base or waters off a named US coast is americas. No-anchor means the "
    "story has no meaningful geography at all -- a budget line, a doctrine change, an "
    'enterprise-wide program -- not "the geography is the United States".'
)

# The revised clause, verbatim as ADR-023 ran it (spec section 3). Sentence 1 is
# the fix, narrowed to institutional-only geography; sentence 2 is the
# anti-overcorrection gate, and ADR-020 is the measured precedent for why it has
# to be there. Note the `--` : the shipped prompt uses double hyphens, not em
# dashes, and the digest check below is what caught that the first time.
REVISED_CLAUSE = (
    "- A US institution is not an American theater. Naming a service, command, "
    "program office, contractor, unit, or official identifies the actor, not a "
    "place: a story whose only geography is institutional has no anchor, so it is "
    "global rather than americas. This does not narrow the evidence above -- a "
    "named command's or fleet's area of operations or responsibility names a "
    "theater, and so do a named base, installation, city, country, or body of "
    "water, wherever the story places the activity."
)

# The prompt fingerprint the PAID ADR-023 candidate run recorded, copied from
# evals/region_clause_candidate.provenance.json. This is the load-bearing
# constant of this module: it is what turns "the clause, as best I recall it"
# into "the clause that produced the 19/8 discordants".
ADR023_CANDIDATE_PROMPT_SHA256 = (
    "b0202d06a876cc0641f50e8910368d7c8a4eb0295f662ac472f9fdd6abf4e963"
)


def apply_clause(prompt: str = SYSTEM_PROMPT) -> str:
    """Insert the revised clause into a prompt's region-rules block.

    Args:
        prompt: The base prompt. Defaults to the live shipped ``SYSTEM_PROMPT``.

    Returns:
        The prompt with :data:`REVISED_CLAUSE` on its own line immediately after
        :data:`ANCHOR_BULLET`.

    Raises:
        ValueError: If the anchor bullet is not present exactly once. Both zero
            matches (the rubric was reworded) and several (an ambiguous insertion
            point) mean the placement claim no longer holds, and a clause in the
            wrong place is a different experiment wearing this one's name.
    """
    occurrences = prompt.count(ANCHOR_BULLET)
    if occurrences != 1:
        raise ValueError(
            f"Expected the anchor bullet exactly once in the prompt, found "
            f"{occurrences}. The clause's placement inside the region-rules block "
            "is load-bearing (l4_pipeline and optimize both freeze that block), so "
            "this refuses rather than guessing where it belongs. If the rubric was "
            "deliberately reworded, ANCHOR_BULLET must be updated -- and the "
            "ADR-023 digest pin will then fail, which is correct: the clause would "
            "no longer be composing the same prompt that was measured."
        )
    return prompt.replace(ANCHOR_BULLET, ANCHOR_BULLET + "\n" + REVISED_CLAUSE)


def candidate_prompt() -> str:
    """The candidate arm's prompt: the live shipped prompt plus the clause."""
    return apply_clause(SYSTEM_PROMPT)


def candidate_fingerprint() -> dict[str, str]:
    """Provenance fingerprint for the candidate arm.

    The prompt hashed here is the *composed* one, not ``SYSTEM_PROMPT`` -- which is
    the whole point. The sidecar this produces therefore records the classifier
    that actually answered, so ``assert_arms_differ``-style checks and any later
    reader see two genuinely different prompts, even though only one of them has
    ever existed in ``classify.py``.

    Returns:
        A ``provenance.fingerprint`` mapping for the candidate arm.
    """
    return provenance.fingerprint(candidate_prompt(), WORKHORSE_MODEL, JUDGE_MODEL)


def assert_clause_reproduces_the_recorded_arm() -> None:
    """Refuse to run unless the composed prompt is ADR-023's, byte for byte.

    This is the check that lets the 295 already-measured rows be reused. If the
    shipped prompt has moved, or the clause text or its placement has drifted by a
    single character, the composed prompt is a *different* classifier -- and
    splicing its new rows onto ADR-023's frozen rows would produce a clean-looking
    n=600 report of two experiments averaged together.

    Raises:
        ValueError: If the composed prompt's digest is not the recorded one, with
            the remedy (re-run both arms in full) spelled out.
    """
    live = hashlib.sha256(candidate_prompt().encode("utf-8")).hexdigest()
    if live == ADR023_CANDIDATE_PROMPT_SHA256:
        return
    raise ValueError(
        "The composed candidate prompt is NOT the one ADR-023 measured.\n"
        f"  recorded (evals/region_clause_candidate.provenance.json): "
        f"{ADR023_CANDIDATE_PROMPT_SHA256}\n"
        f"  composed now                                            : {live}\n\n"
        "Something moved: classify.SYSTEM_PROMPT, REVISED_CLAUSE, or ANCHOR_BULLET. "
        "The frozen 295-row arms can no longer be reused, because they were produced "
        "by a classifier this checkout cannot reconstruct. Either restore the prompt, "
        "or re-run BOTH arms over the whole combined set and re-register the rule -- "
        "do not splice."
    )


# ---------------------------------------------------------------------------
# Paths. Everything read from the ADR-022/ADR-023 era is frozen and opened
# read-only; everything this module writes is new and `_ext`/`_rerun`-named.
# ---------------------------------------------------------------------------

SCALE_SET_PATH = scale_eval.SCALE_SET_PATH
EXT_SET_PATH = "data/scale/scale_set_ext.csv"

FROZEN_KEY_PATH = "evals/scale_predictions_v3.csv"
FROZEN_KEY_PROVENANCE_PATH = "evals/scale_predictions_v3.provenance.json"
FROZEN_CANDIDATE_PATH = ab.CANDIDATE_PREDS_PATH
FROZEN_CANDIDATE_PROVENANCE_PATH = ab.CANDIDATE_PROVENANCE_PATH

EXT_KEY_PATH = "evals/scale_ext_predictions.csv"
EXT_KEY_PROVENANCE_PATH = "evals/scale_ext_predictions.provenance.json"
EXT_CANDIDATE_PATH = "evals/region_clause_ext_candidate.csv"
EXT_CANDIDATE_PROVENANCE_PATH = "evals/region_clause_ext_candidate.provenance.json"

REPORT_PATH = "evals/region_clause_rerun.txt"

AXES = ab.AXES
GLOBAL = ab.GLOBAL
PRIMARY_AXIS = ab.PRIMARY_AXIS

# The pre-registered floor from the spec: below this many EFFECTIVE (deduplicated)
# pairs, the follow-up is not worth its own cost, because the design would still
# be under 80% power against the effect it is chasing. Enforced, not printed --
# an unrun gate is not a pass, and this repo has said so in writing since ADR-007.
MIN_EFFECTIVE_N = 545


# ---------------------------------------------------------------------------
# Loading and guards.
# ---------------------------------------------------------------------------


def load_combined_set() -> pd.DataFrame:
    """The frozen 300 plus the extension snippets, in one frame.

    Returns:
        Frame with ``id`` and ``text``, frozen rows first.

    Raises:
        ValueError: If the extension reuses an id from the frozen set. Ids are the
            join key for every artifact here, so a collision would silently pair a
            new snippet's prediction against an old snippet's answer.
    """
    frozen = scale_eval.load_scale_set(SCALE_SET_PATH)
    if not os.path.exists(EXT_SET_PATH):
        return frozen
    extension = scale_eval.load_scale_set(EXT_SET_PATH)
    clash = sorted(set(extension["id"].astype(str)) & set(frozen["id"].astype(str)))
    if clash:
        raise ValueError(
            f"{EXT_SET_PATH} reuses {len(clash)} id(s) from {SCALE_SET_PATH} "
            f"(e.g. {clash[:5]}). Ids join every artifact in this experiment; a "
            "collision pairs a new snippet's prediction with an old snippet's "
            "answer key. Rebuild the extension with scripts/extend_scale_set.py, "
            "which numbers from the end of the frozen set."
        )
    return pd.concat([frozen, extension], ignore_index=True)


def extension_set() -> pd.DataFrame:
    """Just the extension snippets -- the only rows any live pass classifies.

    Raises:
        FileNotFoundError: If the extension set has not been built yet.
    """
    if not os.path.exists(EXT_SET_PATH):
        raise FileNotFoundError(
            f"{EXT_SET_PATH} does not exist. Build it first (free, no LLM calls):\n"
            "  uv run --env-file .env python scripts/extend_scale_set.py --target N"
        )
    return scale_eval.load_scale_set(EXT_SET_PATH)


def assert_frozen_arms_are_still_ours() -> None:
    """Refuse to splice new rows onto frozen rows a different classifier produced.

    Two sidecars, two different questions. The answer key's sidecar must match the
    LIVE prompt, because the new key rows are graded under it. The candidate arm's
    sidecar must match the COMPOSED prompt, because the new candidate rows are
    classified under that. Checking only one of them would leave the other half of
    the splice unverified.

    Raises:
        ValueError: If either frozen arm was produced by a prompt or model this
            checkout no longer reproduces.
    """
    live = provenance.fingerprint(SYSTEM_PROMPT, WORKHORSE_MODEL, JUDGE_MODEL)
    key_recorded = provenance.load(FROZEN_KEY_PROVENANCE_PATH)["recorded"]
    drift = provenance.divergences(key_recorded, live)
    if drift:
        raise ValueError(
            f"{FROZEN_KEY_PATH} was produced by a different prompt or model than "
            "this checkout, so the new answer-key rows would be graded by a "
            "different ruler than the frozen ones:\n" + "\n".join(drift)
        )
    candidate_recorded = provenance.load(FROZEN_CANDIDATE_PROVENANCE_PATH)["recorded"]
    drift = provenance.divergences(candidate_recorded, candidate_fingerprint())
    if drift:
        raise ValueError(
            f"{FROZEN_CANDIDATE_PATH} was produced by a different classifier than "
            "the one this module composes:\n" + "\n".join(drift)
        )


def assert_complete(frame: pd.DataFrame, snippets: pd.DataFrame, path: str) -> None:
    """Refuse a predictions frame that is not exactly one row per snippet.

    The batch path skips a row it cannot parse and leaves it todo, so an
    interrupted run otherwise yields a well-formed report over fewer rows than the
    experiment was powered for -- which is precisely the failure the power
    analysis exists to rule out.

    Args:
        frame: The loaded predictions frame.
        snippets: The snippet set it must cover.
        path: Where the frame came from, for the error message.

    Raises:
        ValueError: If ids repeat, or the id sets differ in either direction.
    """
    ids = [str(row_id) for row_id in frame["id"]]
    duplicated = sorted({row_id for row_id in ids if ids.count(row_id) > 1})
    if duplicated:
        raise ValueError(
            f"{path} repeats {len(duplicated)} id(s) ({duplicated[:5]}) -- an "
            "appended re-run over rows already present? Pairing drops every one."
        )
    expected = {str(row_id) for row_id in snippets["id"]}
    missing, extra = sorted(expected - set(ids)), sorted(set(ids) - expected)
    if missing or extra:
        raise ValueError(
            f"{path} does not cover the snippet set: {len(missing)} missing "
            f"(e.g. {missing[:5]}), {len(extra)} unexpected (e.g. {extra[:5]}). "
            "Re-run the relevant pass -- it is resume-safe and skips rows already "
            "present."
        )


def assert_no_blank_labels(frame: pd.DataFrame, path: str) -> None:
    """Refuse an answer key or arm with holes in it.

    Frames load through ``paired_compare.read_predictions`` (``dtype=str``,
    ``keep_default_na=False``) precisely so a blank cell arrives as ``""`` and this
    check can fire; with a bare ``read_csv`` it would be comparing ``"nan"`` to
    ``""`` and could never fail.

    Args:
        frame: The loaded frame.
        path: Where it came from, for the error message.

    Raises:
        ValueError: If any present label column holds a blank.
    """
    columns = [c for c in frame.columns if c.startswith(("pred_", "judge_"))]
    for column in columns:
        blank = int((frame[column].astype(str).str.strip() == "").sum())
        if blank:
            raise ValueError(
                f"{path} has {blank} blank {column!r} cells. A key or arm with "
                "holes silently shrinks the comparison instead of failing it."
            )


def read_arm(frozen_path: str, ext_path: str) -> pd.DataFrame:
    """Load a frozen arm and its extension into one frame.

    Args:
        frozen_path: The committed ADR-022/ADR-023 artifact.
        ext_path: The extension artifact, which need not exist yet.

    Returns:
        The concatenated frame, string-typed throughout.
    """
    frozen = paired_compare.read_predictions(frozen_path)
    if not os.path.exists(ext_path):
        return frozen
    return pd.concat(
        [frozen, paired_compare.read_predictions(ext_path)], ignore_index=True
    )


# ---------------------------------------------------------------------------
# The live passes. Only the extension rows are ever classified.
# ---------------------------------------------------------------------------


def run_key(batch: bool = False) -> None:
    """Extend the answer key: workhorse + judge over the new snippets only.

    Spends 2 calls per new snippet. Runs under the LIVE prompt via
    ``gold_eval.run_predictions`` unchanged -- the validated judge configuration,
    untouched, which is what lets the new key rows sit beside the frozen ones.

    Args:
        batch: Submit via the Message Batches API instead of synchronous calls.

    Raises:
        ValueError: If resuming would blend two classifiers.
    """
    os.makedirs("evals", exist_ok=True)
    snippets = extension_set()
    live = provenance.fingerprint(SYSTEM_PROMPT, WORKHORSE_MODEL, JUDGE_MODEL)
    done = _resume_guard(EXT_KEY_PATH, EXT_KEY_PROVENANCE_PATH, live)
    remaining = set(snippets["id"].astype(str)) - done
    if not remaining:
        print("Answer-key extension already complete -- no calls made.\n")
        return

    print(
        f"Extending the answer key over {len(remaining)} new snippets "
        f"({2 * len(remaining)} calls: workhorse + judge).\n",
        flush=True,
    )
    client = make_client()
    runner = run_predictions_batch if batch else run_predictions
    runner(client, snippets, done, preds_path=EXT_KEY_PATH)
    provenance.write(live, EXT_KEY_PATH, path=EXT_KEY_PROVENANCE_PATH)
    _report_partial(EXT_KEY_PATH, snippets)


def run_candidate(batch: bool = False) -> None:
    """Classify the new snippets under the clause-applied prompt.

    Spends 1 call per new snippet. The clause is composed in memory and passed
    down; ``classify.SYSTEM_PROMPT`` is not consulted for the arm's content beyond
    being the base it is composed from.

    Args:
        batch: Submit via the Message Batches API instead of synchronous calls.

    Raises:
        ValueError: If the composed prompt is not ADR-023's, or resuming would
            blend two classifiers.
    """
    assert_clause_reproduces_the_recorded_arm()
    os.makedirs("evals", exist_ok=True)
    snippets = extension_set()
    live = candidate_fingerprint()
    done = _resume_guard(EXT_CANDIDATE_PATH, EXT_CANDIDATE_PROVENANCE_PATH, live)
    remaining = set(snippets["id"].astype(str)) - done
    if not remaining:
        print("Candidate extension already complete -- no calls made.\n")
        return

    print(
        f"Classifying {len(remaining)} new snippets under the clause "
        f"({len(remaining)} calls, workhorse only).\n",
        flush=True,
    )
    client = make_client()
    prompt = candidate_prompt()
    if batch:
        ab.run_workhorse_batch(
            client,
            snippets,
            done,
            preds_path=EXT_CANDIDATE_PATH,
            system_prompt=prompt,
        )
    else:
        ab.run_workhorse(
            client, snippets, done, preds_path=EXT_CANDIDATE_PATH, system_prompt=prompt
        )
    provenance.write(live, EXT_CANDIDATE_PATH, path=EXT_CANDIDATE_PROVENANCE_PATH)
    _report_partial(EXT_CANDIDATE_PATH, snippets)


def _resume_guard(
    preds_path: str, provenance_path: str, live: dict[str, str]
) -> set[str]:
    """Ids already present, after refusing a resume across a classifier change.

    Runs BEFORE the "nothing to do" early return in both callers, because a
    complete-but-stale CSV is the case that most needs catching: it would
    otherwise be silently adopted as this run's arm.

    Args:
        preds_path: The predictions CSV.
        provenance_path: Its sidecar.
        live: The fingerprint the new rows would be produced under.

    Returns:
        Ids already recorded.

    Raises:
        ValueError: If the existing rows came from a different prompt or model.
    """
    if not os.path.exists(preds_path):
        return set()
    done = {str(row_id) for row_id in pd.read_csv(preds_path)["id"]}
    if not done or not os.path.exists(provenance_path):
        return done
    drift = provenance.divergences(provenance.load(provenance_path)["recorded"], live)
    if drift:
        raise ValueError(
            f"Cannot resume {preds_path}: its {len(done)} existing rows were "
            "produced by a different prompt or model.\n"
            + "\n".join(drift)
            + f"\n\nDelete {preds_path} and {provenance_path} and re-run."
        )
    print(f"Resuming: {len(done)} rows already present in {preds_path}.\n")
    return done


def _report_partial(preds_path: str, snippets: pd.DataFrame) -> None:
    """Say plainly when a pass did not land every row.

    The sidecar is written even on a partial pass, because the resume guard needs
    it to exist before the next append can be checked -- so the partiality has to
    be stated out loud rather than inferred from a file that looks complete.

    Args:
        preds_path: The predictions CSV just written.
        snippets: The snippet set the pass was over.
    """
    landed = {str(row_id) for row_id in pd.read_csv(preds_path)["id"]}
    missing = sorted(set(snippets["id"].astype(str)) - landed)
    if missing:
        print(
            f"PARTIAL RUN -- {len(missing)} of {len(snippets)} rows did not land "
            f"(e.g. {missing[:5]}). Re-run to finish; --report refuses until it is "
            "complete.\n",
            flush=True,
        )


# ---------------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------------


def build_report(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    comparisons: list,
    excluded: list[str],
    key_digest: str,
    frozen_n: int,
    extension_n: int,
) -> str:
    """Assemble the higher-power A/B report.

    Args:
        baseline: Deduplicated baseline arm (workhorse + judge columns).
        candidate: Deduplicated candidate arm.
        comparisons: ``(axis, pairing result, correctness lift)`` per axis.
        excluded: Ids dropped from the pairing as exact-duplicate snippets.
        key_digest: Content fingerprint of the answer key actually used.
        frozen_n: Rows contributed by the frozen ADR-022 set, before dedup.
        extension_n: Rows contributed by the extension, before dedup.

    Returns:
        The report text.
    """
    delta = ab.cluster_delta(baseline, candidate)
    n = delta["n"]
    observed = mcnemar_power.scale_effect(1.00, "observed")
    three_quarters = mcnemar_power.scale_effect(0.75, "75% of observed")
    lines = [
        "=" * 62,
        "`global`-BOUNDARY CLAUSE -- HIGHER-POWER RE-RUN (ADR-023 follow-up)",
        "=" * 62,
        "",
        f"Snippets scored   : {n}   (effective, after duplicate removal)",
        f"  frozen ADR-022 set          : {frozen_n}   ({SCALE_SET_PATH})",
        f"  extension                   : {extension_n}   ({EXT_SET_PATH})",
        f"  excluded as exact duplicates: {len(excluded)}"
        + (f"  ({', '.join(excluded[:12])}{'...' if len(excluded) > 12 else ''})"),
        f"Workhorse         : {WORKHORSE_MODEL}",
        f"Answer key        : {JUDGE_MODEL} judge labels, baseline prompt",
        f"Answer-key digest : {key_digest}   (recomputable from the committed CSVs)",
        "",
        "-- Design power, stated before the numbers -----------------",
        "Computed by src/mcnemar_power.py at this exact n, under the",
        "ADR-023 discordant rates. This is a DESIGN figure: it says what",
        "this n can decide, not how much to believe the result below.",
        "",
        f"  power at the observed effect (19/8) : "
        f"{mcnemar_power.power(n, observed):.3f}",
        f"  power if the true effect is 75% of it: "
        f"{mcnemar_power.power(n, three_quarters):.3f}",
        f"  (ADR-023 ran at n=295, power "
        f"{mcnemar_power.power(mcnemar_power.OBSERVED_N, observed):.3f})",
        "",
        "The clause is applied at RUN TIME from a recorded source, and its",
        "composed prompt is pinned to the fingerprint the paid ADR-023 run",
        f"recorded ({ADR023_CANDIDATE_PROMPT_SHA256[:16]}...). classify.SYSTEM_PROMPT",
        "is the shipped prompt here and on main -- no branch carries the clause.",
        "",
        "-- Paired comparison, per axis -----------------------------",
        "Region is the target. Category and domain are GUARDRAILS (ADR-020).",
        "McNemar p is over ALL discordant pairs on the axis, not only F and B.",
        "",
        f"{'axis':<20}{'base':>8}{'cand':>8}{'lift':>9}"
        f"{'c/b/tie':>13}{'McNemar p':>12}",
    ]
    for axis, _result, lift in comparisons:
        lines.append(
            f"{axis:<20}"
            f"{ab.optional_format(lift.baseline_pass_rate, '.1%'):>8}"
            f"{ab.optional_format(lift.candidate_pass_rate, '.1%'):>8}"
            f"{ab.optional_format(lift.lift, '+.1%'):>9}"
            f"{f'{lift.candidate_wins}/{lift.baseline_wins}/{lift.ties}':>13}"
            f"{lift.p_value:>12.4f}"
        )
    lines += ab.cluster_block(delta)
    lines += [
        "",
        "-- Harness health ------------------------------------------",
        "A lift computed over a harness that dropped rows is not a finding.",
        "",
    ]
    for axis, result, lift in comparisons:
        counts = paired_compare.diagnostic_counts(result.diagnostics)
        summary = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
        lines.append(
            f"  {axis:<20} groups={result.total_groups}  pairs={lift.total_pairs}  "
            f"eligible={lift.eligible_pairs}"
        )
        lines.append(
            f"  {'':<20} {summary or 'clean -- every group paired and scored'}"
        )
    lines += [
        "",
        "-- How to read this ----------------------------------------",
        "Accuracy is agreement with the JUDGE, not with a human. ADR-022's",
        "caveat carries: the judge's measured disagreement with humans on",
        "region was 0/54, itself a wide interval. More rows buy power, not",
        "a better-calibrated ruler -- the answer key's documented",
        "self-inconsistencies (ADR-023 section 2.1) reproduce at the same",
        "rate in a larger sample from the same source.",
        "",
        "The decision rule is pre-registered in",
        "docs/specs/global-boundary-clause-rerun.md and is canonical there.",
        "=" * 62,
    ]
    return "\n".join(lines)


def report() -> str:
    """Score the combined arms and write the report. Offline; no key, no calls.

    Returns:
        The report text.

    Raises:
        ValueError: If a guard finds the comparison would not mean what it claims.
    """
    os.makedirs("evals", exist_ok=True)
    assert_clause_reproduces_the_recorded_arm()
    assert_frozen_arms_are_still_ours()

    snippets = load_combined_set()
    baseline = read_arm(FROZEN_KEY_PATH, EXT_KEY_PATH)
    candidate = read_arm(FROZEN_CANDIDATE_PATH, EXT_CANDIDATE_PATH)

    assert_complete(baseline, snippets, EXT_KEY_PATH)
    assert_complete(candidate, snippets, EXT_CANDIDATE_PATH)
    assert_no_blank_labels(baseline, EXT_KEY_PATH)
    assert_no_blank_labels(candidate, EXT_CANDIDATE_PATH)

    excluded = ab.duplicate_snippet_ids(snippets)
    baseline = baseline[~baseline["id"].astype(str).isin(excluded)]
    candidate = candidate[~candidate["id"].astype(str).isin(excluded)]

    if len(baseline) < MIN_EFFECTIVE_N:
        raise ValueError(
            f"Effective n is {len(baseline)}, below the pre-registered floor of "
            f"{MIN_EFFECTIVE_N}. At that n the design is under 80% power against "
            "the very effect it is chasing, so the run cannot decide the question "
            "either way and the rule says do not spend on it. Extend the snippet "
            "set further (scripts/extend_scale_set.py) before reporting. Lowering "
            "this floor after seeing the data is the outcome-switching the "
            "pre-registration exists to prevent."
        )

    comparisons = [
        (axis, *ab.axis_comparison(baseline, candidate, axis, col))
        for axis, col in AXES
    ]
    frozen_ids = set(scale_eval.load_scale_set(SCALE_SET_PATH)["id"].astype(str))
    in_frozen = baseline["id"].astype(str).isin(frozen_ids)
    text = (
        build_report(
            baseline,
            candidate,
            comparisons,
            excluded,
            ab.judge_digest(baseline),
            int(in_frozen.sum()),
            int((~in_frozen).sum()),
        )
        + "\n"
    )
    atomic_write_text(REPORT_PATH, text)
    return text


def main() -> None:
    """CLI entrypoint. ``--run-*`` spend API budget; ``--report`` never does."""
    parser = argparse.ArgumentParser(
        description="Higher-power re-run of the ADR-023 `global`-boundary clause A/B."
    )
    parser.add_argument(
        "--run-key",
        action="store_true",
        help="LIVE: workhorse + judge over the NEW snippets under the shipped "
        "prompt (2 calls per new snippet).",
    )
    parser.add_argument(
        "--run-candidate",
        action="store_true",
        help="LIVE: workhorse over the NEW snippets under the clause-applied "
        "prompt (1 call per new snippet).",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="with a --run-* flag, submit via the Message Batches API "
        "(~50%% cheaper, non-interactive).",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="OFFLINE: score the combined arms and write the report.",
    )
    args = parser.parse_args()

    if not (args.run_key or args.run_candidate or args.report):
        parser.error("nothing to do: pass --run-key, --run-candidate and/or --report")
    if args.batch and not (args.run_key or args.run_candidate):
        parser.error("--batch only applies to a --run-* flag")
    if args.run_key:
        run_key(batch=args.batch)
    if args.run_candidate:
        run_candidate(batch=args.batch)
    if args.report:
        print(report())


if __name__ == "__main__":
    main()
