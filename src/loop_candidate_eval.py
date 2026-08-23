"""Powered A/B of the Ralph loop's category-boundary clauses (loop run 2's candidate).

WHERE THE CANDIDATE COMES FROM. The Ralph outer loop's second live run
(2026-08-23, ADR-026/ADR-027; log ``evals/loop/run_20260823T182804Z.jsonl``,
branch ``loop/prompt-optimize-2`` commit ``951aa83``) accepted two additions to
the category rubric: a procurement-vs-technology sentence ("marketing is not a
buyer") and an industry-vs-technology block ("the deal vs the joint
demonstration"). Best-by-B was B 0.868 -> 0.974 (+0.106) with held-out C
0.914 -> 0.925 (+0.011) -- but B is judge-labeled synthetic text and C is n=54,
where +0.011 is half a row. Neither number can carry an adoption. This module is
the powered, pre-registered measurement that can.

The decision rule is pre-registered in
``docs/specs/loop-candidate-category-eval.md`` and is canonical there.

THE DESIGN, IN FOUR REUSES
==========================

**1. The clauses are applied at run time, and `main` never carries them.** Same
mechanism as ``region_clause_rerun``: :func:`candidate_prompt` composes the live
``SYSTEM_PROMPT`` plus the two clauses in memory and pins the result to
:data:`LOOP_CANDIDATE_PROMPT_SHA256` -- the fingerprint of the prompt the loop
actually measured (recorded by the provenance gate against commit ``951aa83``).
A drift in ``SYSTEM_PROMPT``, the clause text, or the anchors refuses loudly
instead of measuring a different classifier under this one's name.

**2. The baseline arm is already paid for.** ADR-024's adoption made the
ADR-023 candidate arm (``evals/region_clause_candidate.csv`` +
``evals/region_clause_ext_candidate.csv``, prompt ``b0202d06...``) into
predictions of the SHIPPED classifier over the full 600-row combined scale set.
:func:`assert_baseline_arm_is_the_shipped_prompt` checks both sidecars against
the live fingerprint before any number is computed, so the reuse is guarded,
not assumed.

**3. The answer key is frozen and shared by both arms.**
``evals/scale_predictions_v3.csv`` + ``evals/scale_ext_predictions.csv`` carry
the Opus judge's labels for all three axes over the same rows. The judge ran
under the v3.0.0-era configuration (prompt ``a59689e8...``); that is a fixed
ruler, not a live one, and both arms are graded against the SAME key, which is
what a paired comparison needs. The category axis is untouched by the ADR-024
region clause, so the key's age is a caveat for absolute numbers, not for the
paired lift.

**4. A truncated or refused row is a sentinel, never a crash and never a miss.**
Run 2 hit six ``max_tokens`` truncations; the shared batch runner in
``region_clause_ab`` would crash on one. The runners here record
``paired_compare``'s sentinels (``__incomplete__`` / ``__refused__`` /
``__unclassified__``) instead, and ``paired_compare`` scores those pairs as
errored -- excluded from every metric, named in the harness-health block
(ADR-021).

WHAT IS NEVER TOUCHED. ``classify.SYSTEM_PROMPT``, both scale sets, both frozen
key files and their sidecars, both frozen baseline-arm files and their sidecars,
the gold set, the published gold record, ``evals/metrics.json``, and every
``region_clause_*`` artifact. Everything this module writes is new and
``loop_candidate_*``-named.

Run -- every live pass is owner-driven; both reports are free and offline:

    uv run --env-file .env python src/loop_candidate_eval.py --run-candidate --batch
    uv run python src/loop_candidate_eval.py --report
    uv run --env-file .env python src/loop_candidate_eval.py --run-gold
    uv run python src/loop_candidate_eval.py --gold-report
"""

from __future__ import annotations

import argparse
import hashlib
import os
import time

import pandas as pd

import gold_eval
import mcnemar_power
import paired_compare
import provenance
import region_clause_ab as ab
import region_clause_rerun as rerun
from classify import (
    SYSTEM_PROMPT,
    BatchItemError,
    ClassificationRefusalError,
    IncompleteResponseError,
    InvalidLabelError,
    build_batch_request,
    make_client,
    parse_batch_result,
)
from gold_eval import JUDGE_MODEL, WORKHORSE_MODEL, classify_retry
from run_isolation import atomic_write_text

# ---------------------------------------------------------------------------
# The clauses under test, and their proof of identity.
# ---------------------------------------------------------------------------

# Anchors are quoted from the shipped prompt and must occur exactly once; the
# clause is appended immediately after its anchor. Spelled out in full so a
# reword of either bullet fails loudly here instead of silently relocating a
# clause -- and the digest pin below catches everything the anchors cannot.
PROC_TECH_ANCHOR = (
    "If the money event is the story, choose procurement; if the machine is the "
    "story, choose technology."
)

PROC_TECH_CLAUSE = (
    " A company unveiling, rolling out, or marketing a new system at a launch or "
    "trade show is technology even when the story uses sales language such as "
    '"marketed for export" -- procurement needs an actual buyer, award, or '
    "contract named in the story, not just a system being offered or promoted "
    "for sale."
)

INDUSTRY_TECH_ANCHOR = (
    "industry when the business result (revenue, market position, a merger) is "
    "the point."
)

INDUSTRY_TECH_CLAUSE = (
    " A partnership, teaming agreement, joint venture, or MoU between two or "
    "more parties is industry only when the news is the arrangement's formation "
    "-- the deal, the teaming, the MoU signing itself -- even when the resulting "
    "system is described in technical detail. When two or more parties are "
    "instead shown jointly demonstrating, testing, deploying, or operating a "
    "system, label technology: the capability being proven is the story, not "
    "the alliance that produced it. Label technology only when a single "
    "system's own capabilities, performance, or unveiling -- not the deal that "
    "will produce it -- is the actual news."
)

# The fingerprint of the prompt the loop's accepted iterations actually ran
# (worktree src/classify.py at commit 951aa83 on loop/prompt-optimize-2). This
# is the load-bearing constant: it turns "the clauses, as extracted from a
# diff" into "the classifier that produced B +0.106 / C +0.011".
LOOP_CANDIDATE_PROMPT_SHA256 = (
    "7386953ca9365855c06866551b394ca620b69722b9ecf298cde4c89118a7ea32"
)

# ---------------------------------------------------------------------------
# Paths. Everything frozen is opened read-only; everything this module writes
# is new and `loop_candidate_*`-named.
# ---------------------------------------------------------------------------

# The baseline arm: the shipped classifier's predictions over the combined
# scale set -- ADR-024 turned ADR-023's candidate arm into exactly that.
BASELINE_ARM_PATH = rerun.FROZEN_CANDIDATE_PATH
BASELINE_ARM_PROVENANCE_PATH = rerun.FROZEN_CANDIDATE_PROVENANCE_PATH
BASELINE_EXT_ARM_PATH = rerun.EXT_CANDIDATE_PATH
BASELINE_EXT_ARM_PROVENANCE_PATH = rerun.EXT_CANDIDATE_PROVENANCE_PATH

# The frozen judge answer key over the same rows.
KEY_PATH = rerun.FROZEN_KEY_PATH
EXT_KEY_PATH = rerun.EXT_KEY_PATH

CANDIDATE_PATH = "evals/loop_candidate_scale.csv"
CANDIDATE_PROVENANCE_PATH = "evals/loop_candidate_scale.provenance.json"
REPORT_PATH = "evals/loop_candidate_scale_eval.txt"

GOLD_CANDIDATE_PATH = "evals/loop_candidate_gold.csv"
GOLD_CANDIDATE_PROVENANCE_PATH = "evals/loop_candidate_gold.provenance.json"
GOLD_REPORT_PATH = "evals/loop_candidate_gold_eval.txt"

# Rule 3's pre-registered bar: the published v3.2.1 human-graded gold category
# accuracy (51/54). A constant rather than a recomputation, because the bar is
# pre-registered text and must not silently follow the file it was derived from.
GOLD_CATEGORY_BAR = 0.944

# Rule 0's floor: the full effective reuse. The combined set holds 600 rows of
# which 5 are exact-duplicate snippets, so 595 is "every paid row participated".
# Anything lower means an arm is incomplete, and the report must not quietly
# shrink the experiment it was registered as.
MIN_EFFECTIVE_N = 595

PRIMARY_AXIS = "category"

# (axis, judge/answer-key column). Category is the target; the other two are
# guardrails, for the same ADR-020 reason region_clause_ab documents: an
# experiment that fixes its named target while damaging a sibling axis is a
# failure wearing a success's headline number.
AXES = [
    ("category", "judge_category"),
    ("operational_domain", "judge_operational_domain"),
    ("region", "judge_region"),
]

# The design-power scenarios the report re-states next to the result. Grid, not
# a single anchor: unlike ADR-023 there is no prior discordant structure on real
# text for THIS candidate, so the spec registers a sensitivity band instead.
POWER_SCENARIOS = [
    ("net +1% @ 5% discordant", 0.01, 0.05),
    ("net +2% @ 5% discordant", 0.02, 0.05),
    ("net +3% @ 5% discordant", 0.03, 0.05),
]

_SENTINEL_BY_ERROR = {
    IncompleteResponseError: paired_compare.INCOMPLETE,
    ClassificationRefusalError: paired_compare.REFUSED,
    InvalidLabelError: paired_compare.UNCLASSIFIED,
}


# ---------------------------------------------------------------------------
# Composition and identity guards.
# ---------------------------------------------------------------------------


def clauses_are_adopted() -> bool:
    """Whether the shipped prompt already carries either clause.

    Returns:
        ``True`` once either clause is part of ``classify.SYSTEM_PROMPT``.
    """
    return PROC_TECH_CLAUSE in SYSTEM_PROMPT or INDUSTRY_TECH_CLAUSE in SYSTEM_PROMPT


def assert_the_clauses_have_not_shipped_yet() -> None:
    """Refuse every run and report path once a clause is part of the shipped prompt.

    Same closure ``region_clause_rerun`` applies after ADR-024: adoption ends the
    experiment. Post-adoption, the baseline arm this module reuses no longer
    describes a prompt distinct from the candidate, so any comparison re-derived
    from here would compare the shipped classifier against itself.

    Raises:
        ValueError: If either clause is already in ``classify.SYSTEM_PROMPT``.
    """
    if not clauses_are_adopted():
        return
    raise ValueError(
        "A loop-candidate clause is already part of classify.SYSTEM_PROMPT, so "
        "this experiment is over. The committed reports are the record:\n"
        f"  {REPORT_PATH}\n  {GOLD_REPORT_PATH}\n"
        "Re-deriving a comparison from here would compare the shipped "
        "classifier against itself."
    )


def apply_clauses(prompt: str = SYSTEM_PROMPT) -> str:
    """Append both loop clauses to their anchor bullets in a prompt.

    Args:
        prompt: The base prompt. Defaults to the live shipped ``SYSTEM_PROMPT``.

    Returns:
        The prompt with each clause appended immediately after its anchor.

    Raises:
        ValueError: If either clause is already present (a double application
            composes a prompt no arm was measured under), or if either anchor
            is not present exactly once (the rubric was reworded, so the
            placement claim no longer holds).
    """
    for clause in (PROC_TECH_CLAUSE, INDUSTRY_TECH_CLAUSE):
        if clause in prompt:
            raise ValueError(
                "The base prompt already carries a loop-candidate clause, so "
                "applying it again would compose a double-clause prompt that no "
                "arm was ever measured under. If this is classify.SYSTEM_PROMPT, "
                "the clauses have shipped and this experiment is over."
            )
    for anchor in (PROC_TECH_ANCHOR, INDUSTRY_TECH_ANCHOR):
        occurrences = prompt.count(anchor)
        if occurrences != 1:
            raise ValueError(
                f"Expected the anchor {anchor[:40]!r}... exactly once in the "
                f"prompt, found {occurrences}. The clauses' placement inside "
                "the category rubric is what the loop measured, so this refuses "
                "rather than guessing where they belong. If the rubric was "
                "deliberately reworded, the anchors must be updated -- and the "
                "digest pin will then fail, which is correct: the composition "
                "would no longer be the prompt the loop ran."
            )
    return prompt.replace(
        PROC_TECH_ANCHOR, PROC_TECH_ANCHOR + PROC_TECH_CLAUSE
    ).replace(INDUSTRY_TECH_ANCHOR, INDUSTRY_TECH_ANCHOR + INDUSTRY_TECH_CLAUSE)


def candidate_prompt() -> str:
    """The candidate arm's prompt: the live shipped prompt plus both clauses.

    Returns:
        The composed clause-carrying prompt.
    """
    return apply_clauses(SYSTEM_PROMPT)


def candidate_fingerprint() -> dict[str, str]:
    """Provenance fingerprint for the candidate arm (the COMPOSED prompt).

    Returns:
        A ``provenance.fingerprint`` mapping for the candidate arm.
    """
    return provenance.fingerprint(candidate_prompt(), WORKHORSE_MODEL, JUDGE_MODEL)


def assert_clauses_reproduce_the_loop_arm() -> None:
    """Refuse to run unless the composed prompt is the loop's, byte for byte.

    Raises:
        ValueError: If the composed prompt's digest is not the recorded one.
    """
    live = hashlib.sha256(candidate_prompt().encode("utf-8")).hexdigest()
    if live == LOOP_CANDIDATE_PROMPT_SHA256:
        return
    raise ValueError(
        "The composed candidate prompt is NOT the one the loop measured.\n"
        f"  recorded (loop/prompt-optimize-2 @ 951aa83): "
        f"{LOOP_CANDIDATE_PROMPT_SHA256}\n"
        f"  composed now                               : {live}\n\n"
        "Something moved: classify.SYSTEM_PROMPT, a clause constant, or an "
        "anchor. The candidate under test would then be a different classifier "
        "than the one that earned this measurement -- re-derive the candidate "
        "from the loop branch and re-register, do not patch the pin."
    )


def assert_prompt_carries_the_clauses(prompt: str) -> None:
    """Refuse to send a live arm out under a prompt missing either clause.

    The composition guard proves what :func:`candidate_prompt` returns; this
    checks the exact string a runner is about to put on the wire, so a caller
    that passes the shipped prompt by accident measures nothing silently.

    Args:
        prompt: The system prompt about to be sent.

    Raises:
        ValueError: If either clause is absent from the prompt.
    """
    if PROC_TECH_CLAUSE not in prompt or INDUSTRY_TECH_CLAUSE not in prompt:
        raise ValueError(
            "The candidate arm was about to run under a prompt that does not "
            "carry both clauses. That measures the BASELINE and reports it as "
            "the candidate. The prompt must come from candidate_prompt()."
        )


def assert_baseline_arm_is_the_shipped_prompt() -> None:
    """Refuse a baseline arm the shipped classifier did not produce.

    ADR-024 is what makes the reuse legal: the ADR-023 candidate arm's recorded
    prompt became the shipped prompt. If ``SYSTEM_PROMPT`` moves again, the
    frozen arm stops being a baseline and this refuses.

    Raises:
        ValueError: If either frozen sidecar diverges from the live fingerprint.
    """
    live = provenance.fingerprint(SYSTEM_PROMPT, WORKHORSE_MODEL, JUDGE_MODEL)
    for path, sidecar in (
        (BASELINE_ARM_PATH, BASELINE_ARM_PROVENANCE_PATH),
        (BASELINE_EXT_ARM_PATH, BASELINE_EXT_ARM_PROVENANCE_PATH),
    ):
        recorded = provenance.load(sidecar)["recorded"]
        drift = provenance.divergences(recorded, live)
        if drift:
            raise ValueError(
                f"{path} was not produced by the shipped classifier, so it is "
                "not a baseline arm for this comparison:\n" + "\n".join(drift)
            )


def assert_candidate_artifact_is_the_loop_arm(sidecar: str, path: str) -> None:
    """Refuse to score a candidate artifact some other classifier produced.

    Args:
        sidecar: The artifact's provenance sidecar.
        path: The artifact, for the error message.

    Raises:
        FileNotFoundError: If the sidecar is absent.
        ValueError: If the recorded fingerprint is not the composed candidate's.
    """
    recorded = provenance.load(sidecar)["recorded"]
    drift = provenance.divergences(recorded, candidate_fingerprint())
    if drift:
        raise ValueError(
            f"{path} was not produced by the loop-candidate prompt this module "
            "composes:\n" + "\n".join(drift) + f"\n\nDelete {path} and {sidecar} "
            "and re-run."
        )


# ---------------------------------------------------------------------------
# The live passes.
# ---------------------------------------------------------------------------


def _sentinel_for(exc: Exception) -> str:
    """The paired_compare sentinel for a per-row harness failure."""
    for error_type, sentinel in _SENTINEL_BY_ERROR.items():
        if isinstance(exc, error_type):
            return sentinel
    raise TypeError(f"no sentinel for {type(exc).__name__}")


def _append_row(preds_path: str, row: dict) -> None:
    """Append one prediction row, writing the header only on first touch."""
    write_header = not os.path.exists(preds_path)
    pd.DataFrame([row])[ab.CANDIDATE_COLUMNS].to_csv(
        preds_path, mode="a", header=write_header, index=False
    )


def _run_sync(client, todo: pd.DataFrame, prompt: str, preds_path: str) -> None:
    """Classify rows one call at a time, sentinelling per-row harness failures.

    ADR-021's rule, applied at the runner: a truncated, refused, or
    persistently-invalid response is recorded as a sentinel the scoring layer
    excludes and names -- never scored as a miss, and never allowed to abort
    the run (the failure that cost run 2's first baseline pass).

    Args:
        client: Authenticated Anthropic client.
        todo: Rows still to classify (``id``, ``text``).
        prompt: The clause-carrying candidate prompt.
        preds_path: CSV to append predictions to.
    """
    for i, (_, row) in enumerate(todo.iterrows()):
        print(f"[{i + 1:3d}/{len(todo)}] {row['id']}", flush=True)
        try:
            pred = classify_retry(
                client, row["text"], WORKHORSE_MODEL, system_prompt=prompt
            )
            result = {
                "id": row["id"],
                "pred_category": pred["category"],
                "pred_operational_domain": pred["operational_domain"],
                "pred_region": pred["region"],
            }
        except (
            IncompleteResponseError,
            ClassificationRefusalError,
            InvalidLabelError,
        ) as exc:
            sentinel = _sentinel_for(exc)
            print(f"  [{sentinel}] id={row['id']}: {exc}", flush=True)
            result = {
                "id": row["id"],
                "pred_category": sentinel,
                "pred_operational_domain": sentinel,
                "pred_region": sentinel,
            }
        _append_row(preds_path, result)
        time.sleep(ab.SLEEP_BETWEEN_CALLS)


def _run_batch(
    client,
    todo: pd.DataFrame,
    prompt: str,
    preds_path: str,
    poll_interval: float = 30.0,
) -> None:
    """Classify rows via the Message Batches API, sentinelling harness failures.

    ``region_clause_ab.run_workhorse_batch`` leaves ``BatchItemError`` and
    ``InvalidLabelError`` rows todo and would CRASH on a truncated or refused
    item. Here a batch-level failure (``BatchItemError``) still stays todo --
    those are transient -- but the response-level failures get sentinels,
    because re-sending the same request meets the same truncation (ADR-021).

    Args:
        client: Authenticated Anthropic client.
        todo: Rows still to classify.
        prompt: The clause-carrying candidate prompt.
        preds_path: CSV to append predictions to.
        poll_interval: Seconds between status polls.
    """
    requests = [
        build_batch_request(
            str(row["id"]), row["text"], model=WORKHORSE_MODEL, system_prompt=prompt
        )
        for _, row in todo.iterrows()
    ]
    print(f"Submitting a batch of {len(requests)} workhorse requests...", flush=True)
    batch = client.messages.batches.create(requests=requests)
    print(
        f"Batch {batch.id} submitted; polling every {poll_interval:.0f}s...", flush=True
    )
    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        print(
            f"  status={batch.processing_status}  "
            f"processing={batch.request_counts.processing}",
            flush=True,
        )
        time.sleep(poll_interval)

    print("Batch ended; retrieving results...", flush=True)
    rows: list[dict] = []
    for result in client.messages.batches.results(batch.id):
        try:
            pred = parse_batch_result(result)
            rows.append(
                {
                    "id": result.custom_id,
                    "pred_category": pred["category"],
                    "pred_operational_domain": pred["operational_domain"],
                    "pred_region": pred["region"],
                }
            )
        except BatchItemError as exc:
            # Batch-plumbing failures are transient: leave the row todo.
            print(f"  [skip] id={result.custom_id}: {exc}", flush=True)
        except (
            IncompleteResponseError,
            ClassificationRefusalError,
            InvalidLabelError,
        ) as exc:
            sentinel = _sentinel_for(exc)
            print(f"  [{sentinel}] id={result.custom_id}: {exc}", flush=True)
            rows.append(
                {
                    "id": result.custom_id,
                    "pred_category": sentinel,
                    "pred_operational_domain": sentinel,
                    "pred_region": sentinel,
                }
            )
    for row in rows:
        _append_row(preds_path, row)


def run_candidate(batch: bool = False) -> None:
    """Classify the combined scale set under the loop-candidate prompt.

    Spends one workhorse call per not-yet-done row (600 on a fresh run). The
    baseline arm and the answer key are frozen artifacts; this is the only
    scale-side spend in the whole experiment.

    Args:
        batch: Submit via the Message Batches API instead of synchronous calls.

    Raises:
        ValueError: If a guard finds the run would not measure what it claims.
    """
    assert_the_clauses_have_not_shipped_yet()
    assert_clauses_reproduce_the_loop_arm()
    assert_baseline_arm_is_the_shipped_prompt()
    os.makedirs("evals", exist_ok=True)
    snippets = rerun.load_combined_set()
    live = candidate_fingerprint()
    done = rerun._resume_guard(CANDIDATE_PATH, CANDIDATE_PROVENANCE_PATH, live)
    todo = snippets[~snippets["id"].astype(str).isin(done)].reset_index(drop=True)
    if todo.empty:
        print("Candidate arm already complete -- no calls made.\n")
        return

    prompt = candidate_prompt()
    assert_prompt_carries_the_clauses(prompt)
    print(
        f"Classifying {len(todo)} snippets under the loop candidate "
        f"({len(todo)} calls, workhorse only).\n",
        flush=True,
    )
    client = make_client()
    if batch:
        _run_batch(client, todo, prompt, CANDIDATE_PATH)
    else:
        _run_sync(client, todo, prompt, CANDIDATE_PATH)
    provenance.write(live, CANDIDATE_PATH, path=CANDIDATE_PROVENANCE_PATH)
    rerun._report_partial(CANDIDATE_PATH, snippets)


def run_gold(batch: bool = False) -> None:
    """Classify the 54 gold snippets under the loop-candidate prompt (rule 3).

    Spends one workhorse call per gold snippet and nothing else -- the answer
    key is the frozen human labels, so no judge call exists to make.

    Args:
        batch: Submit via the Message Batches API. At n=54 synchronous is
            usually the better trade, so this defaults off.

    Raises:
        ValueError: If a guard finds the run would not measure what it claims.
    """
    assert_the_clauses_have_not_shipped_yet()
    assert_clauses_reproduce_the_loop_arm()
    for destination in (GOLD_CANDIDATE_PATH, GOLD_CANDIDATE_PROVENANCE_PATH):
        rerun.assert_writable_gold_artifact(destination)
    os.makedirs("evals", exist_ok=True)
    snippets = gold_eval.load_gold(rerun.GOLD_SET_PATH)
    live = candidate_fingerprint()
    done = rerun._resume_guard(
        GOLD_CANDIDATE_PATH, GOLD_CANDIDATE_PROVENANCE_PATH, live
    )
    todo = snippets[~snippets["id"].astype(str).isin(done)].reset_index(drop=True)
    if todo.empty:
        print("Gold arm already complete -- no calls made.\n")
        return

    prompt = candidate_prompt()
    assert_prompt_carries_the_clauses(prompt)
    print(
        f"Classifying {len(todo)} gold snippets under the loop candidate "
        f"({len(todo)} calls, workhorse only -- NO judge call: the answer key "
        "is the frozen human labels).\n",
        flush=True,
    )
    client = make_client()
    if batch:
        _run_batch(client, todo, prompt, GOLD_CANDIDATE_PATH)
    else:
        _run_sync(client, todo, prompt, GOLD_CANDIDATE_PATH)
    provenance.write(live, GOLD_CANDIDATE_PATH, path=GOLD_CANDIDATE_PROVENANCE_PATH)
    rerun._report_partial(GOLD_CANDIDATE_PATH, snippets)


# ---------------------------------------------------------------------------
# Reports.
# ---------------------------------------------------------------------------


def _power_block(n: int) -> list[str]:
    """The design-power lines the report restates next to the result.

    Args:
        n: The effective (deduplicated) pair count.

    Returns:
        Report lines.
    """
    lines = [
        "-- Design power, stated before the numbers -----------------",
        "Computed by src/mcnemar_power.py at this exact n. Unlike ADR-023",
        "there is no prior discordant structure on real text for THIS",
        "candidate, so the registered figures are a sensitivity band, not",
        "an anchor. A null here rules out the top of the band, not the",
        "bottom -- see the spec's rule 0.",
        "",
    ]
    for label, net, rate in POWER_SCENARIOS:
        scenario = mcnemar_power.Scenario(
            label=label, p_b=(rate + net) / 2, p_c=(rate - net) / 2
        )
        lines.append(f"  power at {label:<26}: {mcnemar_power.power(n, scenario):.3f}")
    return lines


def _fixed_and_broken(
    baseline: pd.DataFrame, candidate: pd.DataFrame, judge_column: str
) -> tuple[list[str], list[str]]:
    """Category rows the candidate fixed and broke, against the judge key.

    Args:
        baseline: Baseline frame carrying ``judge_*`` and ``pred_*`` columns.
        candidate: Candidate frame carrying ``pred_*`` columns.
        judge_column: The answer-key column for the primary axis.

    Returns:
        ``(fixed_ids, broken_ids)`` in id order.
    """
    merged = baseline.merge(candidate, on="id", suffixes=("_base", "_cand"))
    base_ok = merged[judge_column] == merged[f"pred_{PRIMARY_AXIS}_base"]
    cand_ok = merged[judge_column] == merged[f"pred_{PRIMARY_AXIS}_cand"]
    fixed = sorted(merged[~base_ok & cand_ok]["id"].astype(str))
    broken = sorted(merged[base_ok & ~cand_ok]["id"].astype(str))
    return fixed, broken


def report() -> str:
    """Score the frozen baseline against the candidate arm and write the report.

    Offline; no key, no calls.

    Returns:
        The report text.

    Raises:
        ValueError: If a guard finds the comparison would not mean what it
            claims, or if the effective n is below the pre-registered floor.
    """
    assert_the_clauses_have_not_shipped_yet()
    assert_clauses_reproduce_the_loop_arm()
    assert_baseline_arm_is_the_shipped_prompt()
    assert_candidate_artifact_is_the_loop_arm(CANDIDATE_PROVENANCE_PATH, CANDIDATE_PATH)
    os.makedirs("evals", exist_ok=True)

    snippets = rerun.load_combined_set()
    key = rerun.read_arm(KEY_PATH, EXT_KEY_PATH)
    baseline_arm = rerun.read_arm(BASELINE_ARM_PATH, BASELINE_EXT_ARM_PATH)
    candidate = paired_compare.read_predictions(CANDIDATE_PATH)

    rerun.assert_complete(key, snippets, KEY_PATH)
    rerun.assert_complete(baseline_arm, snippets, BASELINE_ARM_PATH)
    rerun.assert_complete(candidate, snippets, CANDIDATE_PATH)
    rerun.assert_no_blank_labels(key, KEY_PATH)
    rerun.assert_no_blank_labels(baseline_arm, BASELINE_ARM_PATH)
    rerun.assert_no_blank_labels(candidate, CANDIDATE_PATH)

    excluded = ab.duplicate_snippet_ids(snippets)
    judge_columns = ["id"] + [column for _axis, column in AXES]
    baseline = key[judge_columns].merge(baseline_arm, on="id")
    baseline = baseline[~baseline["id"].astype(str).isin(excluded)]
    candidate = candidate[~candidate["id"].astype(str).isin(excluded)]

    if len(baseline) < MIN_EFFECTIVE_N:
        raise ValueError(
            f"Effective n is {len(baseline)}, below the pre-registered floor of "
            f"{MIN_EFFECTIVE_N}. The floor is the full paid reuse -- fewer rows "
            "means an arm is incomplete, and a report over a shrunken set is a "
            "different experiment than the registered one."
        )

    comparisons = [
        (axis, *ab.axis_comparison(baseline, candidate, axis, column))
        for axis, column in AXES
    ]
    fixed, broken = _fixed_and_broken(baseline, candidate, AXES[0][1])

    primary_lift = comparisons[0][2]
    rule1 = (
        primary_lift.lift is not None
        and primary_lift.lift > 0
        and primary_lift.p_value < 0.05
    )
    guard_harm = [
        axis
        for axis, _result, lift in comparisons[1:]
        if lift.lift is not None and lift.lift < 0 and lift.p_value < 0.05
    ]

    lines = [
        "=" * 62,
        "LOOP-CANDIDATE CATEGORY CLAUSES -- POWERED A/B (loop run 2)",
        "=" * 62,
        "",
        f"Snippets scored   : {len(baseline)}   (effective, after duplicate removal)",
        f"  excluded as exact duplicates: {len(excluded)}",
        f"Workhorse         : {WORKHORSE_MODEL}",
        f"Answer key        : {JUDGE_MODEL} judge labels, FROZEN (v3.0.0-era",
        "                    configuration; both arms graded against the same key,",
        "                    so the paired lift is internally consistent)",
        f"Answer-key digest : {ab.judge_digest(baseline)}",
        f"Baseline arm      : the SHIPPED prompt ({rerun.ADR023_CANDIDATE_PROMPT_SHA256[:16]}...),",
        f"                    reused from {BASELINE_ARM_PATH} (+ ext)",
        f"Candidate arm     : the loop prompt ({LOOP_CANDIDATE_PROMPT_SHA256[:16]}...),",
        "                    composed at run time and pinned to the run-2 arm",
        "",
    ]
    lines += _power_block(len(baseline))
    lines += [
        "",
        "-- Paired comparison, per axis -----------------------------",
        "Category is the target. Domain and region are GUARDRAILS (ADR-020).",
        "McNemar p is over ALL discordant pairs on the axis.",
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
    lines += [
        "",
        "-- Pre-registered rules, as measured -----------------------",
        f"  rule 1 (category lift > 0 at p < 0.05): "
        f"{'PASSES' if rule1 else 'FAILS'}",
        "  rule 2 (no guardrail harmed at p < 0.05): "
        + ("PASSES" if not guard_harm else f"FAILS ({', '.join(guard_harm)})"),
        "  rule 3 (gold non-regression) is the gold arm's question -- run",
        "  --run-gold / --gold-report only if rules 1 and 2 pass.",
        "",
        "-- Per-claim rows, category vs the judge key ---------------",
        f"Fixed  (baseline wrong -> candidate right): {len(fixed)}",
        "  " + (", ".join(fixed) or "(none)"),
        f"Broken (baseline right -> candidate wrong): {len(broken)}",
        "  " + (", ".join(broken) or "(none)"),
        "",
        "-- Harness health ------------------------------------------",
        "A lift computed over a harness that dropped rows is not a finding.",
        "Sentinel rows (__incomplete__/__refused__/__unclassified__) pair as",
        "errored: excluded from every metric, counted here.",
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
        "Accuracy is agreement with the JUDGE, not with a human. The paired",
        "lift is the finding; the absolute numbers inherit the key's",
        "documented self-inconsistencies (ADR-023 section 2.1). Rule 3's",
        "human-graded arm is the non-regression check, not the headline.",
        "",
        "The decision rule is pre-registered in",
        "docs/specs/loop-candidate-category-eval.md and is canonical there.",
        "=" * 62,
    ]
    text = "\n".join(lines) + "\n"
    atomic_write_text(REPORT_PATH, text)
    return text


def gold_report() -> str:
    """Score the gold arm against the human labels and write the rule-3 report.

    Offline; no key, no calls.

    Returns:
        The report text.

    Raises:
        ValueError: If a guard finds the comparison would not mean what it claims.
    """
    assert_the_clauses_have_not_shipped_yet()
    assert_clauses_reproduce_the_loop_arm()
    assert_candidate_artifact_is_the_loop_arm(
        GOLD_CANDIDATE_PROVENANCE_PATH, GOLD_CANDIDATE_PATH
    )
    rerun.assert_gold_baseline_is_the_shipped_arm()
    rerun.assert_writable_gold_artifact(GOLD_REPORT_PATH)
    os.makedirs("evals", exist_ok=True)

    gold = gold_eval.load_gold(rerun.GOLD_SET_PATH)
    baseline = paired_compare.read_predictions(rerun.GOLD_BASELINE_PATH)
    candidate = paired_compare.read_predictions(GOLD_CANDIDATE_PATH)
    rerun.assert_complete(baseline, gold, rerun.GOLD_BASELINE_PATH)
    rerun.assert_complete(candidate, gold, GOLD_CANDIDATE_PATH)
    rerun.assert_no_blank_labels(baseline, rerun.GOLD_BASELINE_PATH)
    rerun.assert_no_blank_labels(candidate, GOLD_CANDIDATE_PATH)

    merged = (
        gold.rename(columns={"domain": "operational_domain"})
        .merge(baseline, on="id")
        .merge(candidate, on="id", suffixes=("_base", "_cand"))
    )
    scores: dict[str, float] = {}
    for axis in ("category", "operational_domain", "region"):
        scores[f"{axis}_base"] = float(
            (merged[axis] == merged[f"pred_{axis}_base"]).mean()
        )
        scores[f"{axis}_cand"] = float(
            (merged[axis] == merged[f"pred_{axis}_cand"]).mean()
        )
    base_ok = merged["category"] == merged["pred_category_base"]
    cand_ok = merged["category"] == merged["pred_category_cand"]
    fixed = sorted(merged[~base_ok & cand_ok]["id"].astype(str))
    broken = sorted(merged[base_ok & ~cand_ok]["id"].astype(str))
    passes = scores["category_cand"] >= GOLD_CATEGORY_BAR

    lines = [
        "=" * 62,
        "LOOP-CANDIDATE CATEGORY CLAUSES -- GOLD ARM, RULE 3",
        "=" * 62,
        "",
        f"Snippets scored   : {len(merged)}   (human labels; no judge call made)",
        f"Candidate arm     : {GOLD_CANDIDATE_PATH}",
        f"Baseline arm      : {rerun.GOLD_BASELINE_PATH}   (published record,",
        "                    read-only; this run does not and cannot write it)",
        "",
        "-- Rule 3: gold category does not regress ------------------",
        f"Pre-registered bar: human-graded category accuracy >= "
        f"{GOLD_CATEGORY_BAR:.1%} (the published v3.2.1 figure).",
        "",
        f"  category accuracy, baseline (published) : {scores['category_base']:.1%}",
        f"  category accuracy, candidate (clauses)  : {scores['category_cand']:.1%}",
        f"  RULE 3: {'PASSES' if passes else 'FAILS'}"
        f"   -- {scores['category_cand']:.1%} "
        f"{'>=' if passes else '<'} {GOLD_CATEGORY_BAR:.1%}",
        "",
        f"Fixed  (baseline wrong -> candidate right): {len(fixed)}",
        "  " + (", ".join(fixed) or "(none)"),
        f"Broken (baseline right -> candidate wrong): {len(broken)}",
        "  " + (", ".join(broken) or "(none)"),
        "",
        "-- Secondary context, NOT gates ----------------------------",
        "The pre-registered guardrail test is rule 2 and it runs on the scale",
        "arm (n=595, where it has power). These n=54 figures are context only.",
        "",
        f"  domain accuracy : {scores['operational_domain_base']:.1%} -> "
        f"{scores['operational_domain_cand']:.1%}",
        f"  region accuracy : {scores['region_base']:.1%} -> "
        f"{scores['region_cand']:.1%}",
        "",
        "Rule 3 is a NON-REGRESSION check by design: it can veto the clauses,",
        "it cannot carry them. The gated floors and judge-agreement numbers",
        "are ADOPTION-time questions -- they move only when the clauses enter",
        "SYSTEM_PROMPT and the full gold re-run happens (ADR-024 shape).",
        "",
        "The decision rule is pre-registered in",
        "docs/specs/loop-candidate-category-eval.md and is canonical there.",
        "=" * 62,
    ]
    text = "\n".join(lines) + "\n"
    atomic_write_text(GOLD_REPORT_PATH, text)
    return text


def main() -> None:
    """CLI entrypoint. ``--run-*`` spend API budget; the ``*report`` flags never do."""
    parser = argparse.ArgumentParser(
        description="Powered A/B of the Ralph loop's category-boundary clauses."
    )
    parser.add_argument(
        "--run-candidate",
        action="store_true",
        help="LIVE: workhorse over the combined scale set under the "
        "loop-candidate prompt (1 call per row, 600 on a fresh run).",
    )
    parser.add_argument(
        "--run-gold",
        action="store_true",
        help="LIVE: workhorse over the 54 GOLD snippets under the "
        "loop-candidate prompt (1 call per snippet; NO judge call). Rule 3.",
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
        help="OFFLINE: score the arms and write the report.",
    )
    parser.add_argument(
        "--gold-report",
        action="store_true",
        help="OFFLINE: score the gold arm against the human labels and write "
        "the rule-3 report.",
    )
    args = parser.parse_args()

    live_flags = (args.run_candidate, args.run_gold)
    if not (any(live_flags) or args.report or args.gold_report):
        parser.error(
            "nothing to do: pass --run-candidate, --run-gold, --report and/or "
            "--gold-report"
        )
    if args.batch and not any(live_flags):
        parser.error("--batch only applies to a --run-* flag")
    if args.run_candidate:
        run_candidate(batch=args.batch)
    if args.run_gold:
        run_gold(batch=args.batch)
    if args.report:
        print(report())
    if args.gold_report:
        print(gold_report())


if __name__ == "__main__":
    main()
