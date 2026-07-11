"""Rung-1 prompt-optimization loop for the classifier's system prompt.

Iterates the prompt against the eval until an explicit done-signal fires,
with zero human input mid-run. This is Level 3 of the autonomy ladder
(docs/specs/autonomy-ladder.md) and
implements docs/specs/prompt-optimization-loop.md -- see that spec for the
full design (the loop shape, the 3-way A/B/C split as the overfitting guard,
the done-signal precedence, and the run-log schema this module writes).

Everything the loop needs to talk to an LLM is behind a 2-method `backend`
(score a split, propose a revision) that the orchestrator (`run_optimization`)
is handed, rather than calling the Anthropic client directly. That single
seam does two things at once:

- It makes the Goodhart guard STRUCTURAL: the proposer only ever receives
  feedback text built from set A (`build_feedback`). B and C's DataFrames are
  never passed into anything that reaches the proposer, so they cannot leak
  into the prompt-revision process through this code path -- not just "we
  tested that they don't," but "there is no line of code through which they
  could."
- It makes a zero-API dry-run mode fall out for free: `DryRunBackend`
  implements the same two methods with a deterministic offline mock, so the
  entire loop -- split, score, feedback, propose, re-score, done-signal,
  run-log -- runs end-to-end with no key and no tokens spent.

Usage:
    # Zero-API mock run -- no ANTHROPIC_API_KEY needed, safe to run anytime:
    uv run python src/optimize.py --dry-run

    # A real optimization run (spends real tokens -- see README.md for the
    # call-count math before running this):
    uv run --env-file .env python src/optimize.py --max-iterations 8 --token-budget 200000

Each run writes an append-only JSONL log to evals/optimize/run_<UTC>.jsonl:
one run-metadata line, one line per iteration, one run-summary trailer line.
See evals/optimize/README.md for the schema.
"""

import argparse
import difflib
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, cast

import anthropic
import pandas as pd
from anthropic.types import ToolParam, ToolUseBlock

from classify import (
    CATEGORIES,
    MODEL,
    SYSTEM_PROMPT,
    InvalidLabelError,
    classify,
    make_client,
)
from eval import compute_metrics, macro_average
from gold_eval import GOLD_PATH, load_gold

DATA_PATH = "data/synthetic_articles.csv"
RUN_LOG_DIR = "evals/optimize"

# Sentinel prediction recorded for a row that classify() still cannot get a
# valid label for after exhausting its own re-sample budget (classify.py's
# `for _ in range(4)`). Set on BOTH the category and domain prediction
# columns so the row scores as wrong on both axes -- San's explicit choice
# to count an unclassifiable row as a miss rather than drop it, since
# dropping would silently shrink the split and change what macro-F1 is being
# averaged over mid-run. The value can never collide with a real label: it
# is not a member of CATEGORIES or DOMAINS, so eval.py's compute_metrics /
# macro_average / confusion_matrix (which key off the ground-truth label
# set) treat it as simply an incorrect prediction, never crash on it.
UNCLASSIFIED = "__unclassified__"

# --- tunable defaults (all overridable via CLI flags; see main()) ----------
DEFAULT_SPLIT_RATIO = 0.7  # spec's proposed ~210/90 split of the 300 synthetic rows
DEFAULT_SEED = 42
DEFAULT_PLATEAU_N = 3  # spec section 5.4: plateau = no B-improvement for N=3 iterations
DEFAULT_MAX_ITERATIONS = 8
# Sized so the ITERATION cap is the binding stop and the token budget stays
# what F8 means it to be: the runaway backstop. One scoring pass over the
# default split (A=210 + B=90 + C=54 = 354 classify calls) estimates at
# ~185k tokens (see _estimate_tokens), and a full default run is 9 scoring
# passes (baseline + 8 iterations) plus 8 proposer calls -- ~1.7M estimated
# tokens. 2M gives that run headroom; a budget below ~1.7M silently turns
# every default run into a "budget_tokens" stop after iteration 1, which is
# a degenerate loop, not an optimization.
DEFAULT_TOKEN_BUDGET = 2_000_000
# The spec (section 13) leaves the exact target unconfirmed. 0.90 is a
# deliberately conservative placeholder -- clearly above the current v1
# category macro-F1 baseline (0.765, evals/metrics.txt) without assuming a
# ceiling the loop hasn't earned yet. Tune with --target-f1 once a live
# baseline is in hand. See decisions/005 "Resolved during implementation".
DEFAULT_TARGET_F1 = 0.90
MAX_FEEDBACK_EXAMPLES = 12  # spec section 5.3: "up to ~10-15"; plan pins ~12

# --- AnthropicBackend scoring-call token estimate ---------------------------
# classify()'s return contract is pinned to exactly {category,
# operational_domain} by tests/test_classify.py and tests/test_contract.py,
# so it does not surface response.usage. Rather than change that pinned
# contract or bypass classify() and duplicate its request/validation logic,
# scoring-call tokens are a documented character-count estimate. For the
# --token-budget fail-safe (F8) to trip early rather than late, the estimate
# must lean HIGH, which means counting more than just the prose: every
# classify() request also bills the CLASSIFY_TOOL JSON schema, the
# message/tool_choice framing, and the tool-call output (~120-190 real tokens
# per call that len(prompt)+len(text) never sees). _PER_CALL_OVERHEAD_TOKENS
# covers all of that with margin -- deliberately generous, so the estimate
# overshoots real billed tokens instead of undershooting them. The
# proposer/optimizer call is NOT estimated -- AnthropicBackend.propose()
# calls the client directly and reads exact counts from response.usage.
_CHARS_PER_TOKEN = 4
_ESTIMATED_OUTPUT_TOKENS = 60
_PER_CALL_OVERHEAD_TOKENS = 250


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Split:
    """The 3-way A/B/C split (spec section 5.2) plus reproducibility hashes."""

    a: pd.DataFrame
    b: pd.DataFrame
    c: pd.DataFrame
    hashes: dict


@dataclass(frozen=True)
class OptimizationConfig:
    """Tunable knobs for one optimization run -- all CLI-configurable."""

    start_prompt: str = SYSTEM_PROMPT
    model: str = MODEL
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    token_budget: int = DEFAULT_TOKEN_BUDGET
    target_f1: float = DEFAULT_TARGET_F1
    plateau_n: int = DEFAULT_PLATEAU_N
    max_feedback_examples: int = MAX_FEEDBACK_EXAMPLES
    seed: int = DEFAULT_SEED


@dataclass(frozen=True)
class ScoreOutcome:
    """What a backend's `score()` returns: predictions plus tokens spent.

    `unclassified_ids` lists the row ids (if any) that classify() could not
    get a valid label for after exhausting its retries -- always `[]` for
    `DryRunBackend`, which never produces an invalid label.
    """

    merged: pd.DataFrame
    tokens: int
    unclassified_ids: list = field(default_factory=list)


@dataclass(frozen=True)
class ProposeOutcome:
    """What a backend's `propose()` returns: a candidate revision plus tokens spent."""

    revised_prompt: str
    rationale: str
    edit_summary: str
    tokens: int


@dataclass(frozen=True)
class SplitScore:
    """One split's scores under one prompt, plus the merged predictions.

    `merged` is deliberately excluded from `as_dict()` -- it carries raw
    article text and is only ever used in-process (to build set-A feedback);
    it is never written to the run log.
    """

    merged: pd.DataFrame
    macro_f1: float
    accuracy: float
    domain_macro_f1: float
    domain_accuracy: float
    per_class_f1: dict
    tokens: int
    unclassified_ids: list = field(default_factory=list)

    def as_dict(self) -> dict:
        """JSON-serializable view for the run log (drops the predictions DataFrame)."""
        return {
            "macro_f1": self.macro_f1,
            "accuracy": self.accuracy,
            "domain_macro_f1": self.domain_macro_f1,
            "domain_accuracy": self.domain_accuracy,
            "per_class_f1": self.per_class_f1,
        }


class OptimizerBackend(Protocol):
    """The 2-method seam the orchestrator talks to instead of the Anthropic client.

    `DryRunBackend` implements this with zero API calls; `AnthropicBackend`
    implements it against the real Anthropic API. The orchestrator
    (`run_optimization`) never knows or cares which one it was handed --
    that is what makes the dry-run mode a real end-to-end exercise of the
    loop mechanics rather than a separate code path.
    """

    def score(self, prompt: str, df: pd.DataFrame) -> ScoreOutcome:
        """Classify every row of `df` under `prompt`."""
        ...

    def propose(self, current_prompt: str, feedback: str) -> ProposeOutcome:
        """Propose a revised prompt given set-A-only feedback text."""
        ...


# ---------------------------------------------------------------------------
# Pure functions -- offline-tested, no network I/O of their own. score_split
# and build_feedback take a `backend`/DataFrame as input rather than calling
# the Anthropic client directly, which is what makes them testable with a
# fake backend instead of a live key.
# ---------------------------------------------------------------------------


def _hash_ids(ids: pd.Series) -> str:
    """Stable short hash of a split's sorted id list (for `Split.hashes`).

    Args:
        ids: The `id` column of one split (A, B, or C).

    Returns:
        A 16-character hex digest. Two runs with the same hash used
        provably the same set of rows; this is what lets a run log claim
        the sets were disjoint without re-shipping the full id lists.
    """
    joined = ",".join(str(i) for i in sorted(ids.tolist()))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def make_split(
    df_synth: pd.DataFrame,
    df_gold: pd.DataFrame,
    ratio: float = DEFAULT_SPLIT_RATIO,
    seed: int = DEFAULT_SEED,
) -> Split:
    """Build the seeded, reproducible 3-way A/B/C split (spec section 5.2).

    A and B are a shuffled split of the synthetic set -- the overfitting
    guard hinges on them being disjoint, since optimizing and detecting
    plateau on the same rows would bias stop-detection toward looking
    healthier than it is. C is the entire real gold set, used only for
    reporting.

    Args:
        df_synth: The 300-row synthetic dataset (columns `id`, `text`,
            `category`, `operational_domain`).
        df_gold: The gold dataset, already normalized with an
            `operational_domain` column -- i.e. after
            `load_gold().rename(columns={"domain": "operational_domain"})`,
            matching gold_eval.py's own convention. This function does not
            do that rename itself.
        ratio: Fraction of the synthetic set assigned to A. Defaults to 0.7
            (~210/90), the spec's proposed split.
        seed: RNG seed for the shuffle, so a run's split is reproducible
            from `--seed` alone.

    Returns:
        A `Split` with `.a`, `.b`, `.c` DataFrames and `.hashes`.
    """
    shuffled = df_synth.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    cut = int(len(shuffled) * ratio)
    a = shuffled.iloc[:cut].reset_index(drop=True)
    b = shuffled.iloc[cut:].reset_index(drop=True)
    c = df_gold.reset_index(drop=True)
    hashes = {"A": _hash_ids(a["id"]), "B": _hash_ids(b["id"]), "C": _hash_ids(c["id"])}
    return Split(a=a, b=b, c=c, hashes=hashes)


def score_split(prompt: str, backend: OptimizerBackend, df: pd.DataFrame) -> SplitScore:
    """Score `prompt` on `df` via `backend` and compute category + domain metrics.

    Reuses eval.py's `compute_metrics` / `macro_average` (N1 -- no metric
    reimplementation). The backend seam (not a direct Anthropic call) is
    what makes this offline-testable: pass a fake or `DryRunBackend` in
    tests, `AnthropicBackend` for a real run.

    Args:
        prompt: System prompt to score.
        backend: Object implementing `OptimizerBackend`.
        df: Ground-truth DataFrame with columns `id`, `text`, `category`,
            `operational_domain`.

    Returns:
        A `SplitScore` with category/domain macro-F1 + accuracy, per-class
        F1, tokens spent, and the merged predictions DataFrame (used to
        build set-A agent feedback; never itself written to the run log).
    """
    outcome = backend.score(prompt, df)
    merged = outcome.merged
    cat_metrics = compute_metrics(merged, "category")
    dom_metrics = compute_metrics(merged, "operational_domain")
    cat_macro = macro_average(cat_metrics)
    dom_macro = macro_average(dom_metrics)
    cat_acc = float((merged["category"] == merged["pred_category"]).mean())
    dom_acc = float(
        (merged["operational_domain"] == merged["pred_operational_domain"]).mean()
    )
    per_class_f1 = {str(k): float(v) for k, v in cat_metrics["f1"].to_dict().items()}
    return SplitScore(
        merged=merged,
        macro_f1=cat_macro["f1"],
        accuracy=round(cat_acc, 4),
        domain_macro_f1=dom_macro["f1"],
        domain_accuracy=round(dom_acc, 4),
        per_class_f1=per_class_f1,
        tokens=int(outcome.tokens),
        unclassified_ids=list(outcome.unclassified_ids),
    )


def _confusion_stats(merged: pd.DataFrame) -> dict:
    """Off-diagonal confusion pairs with count > 0, sorted highest-count first.

    Deliberately does NOT reuse eval.py's `confusion_matrix()` here: that
    function reindexes both axes to the *true*-label set, so a predicted
    label that never occurs as a ground-truth label in this split would be
    silently dropped from the table -- a real risk once errors on a small
    split concentrate onto one systematically-overpredicted label, not just
    a theoretical one. A direct groupby over mismatched rows has no such
    blind spot. This is the one place `build_feedback` diverges from N1's
    reuse list; `compute_metrics`/`macro_average` (the actual scoring math)
    are still reused verbatim everywhere else.

    Args:
        merged: Ground-truth + prediction DataFrame for one split.

    Returns:
        Dict mapping `"{true_label}->{predicted_label}"` to a count, e.g.
        `{"industry->procurement": 8}`, most-confused pair first.
    """
    wrong = merged[merged["category"] != merged["pred_category"]]
    counts = (
        wrong.groupby(["category", "pred_category"]).size().reset_index(name="count")
    )
    pairs = {
        f"{row['category']}->{row['pred_category']}": int(row["count"])
        for _, row in counts.iterrows()
    }
    return dict(sorted(pairs.items(), key=lambda kv: kv[1], reverse=True))


def build_feedback(
    merged_a: pd.DataFrame, max_examples: int = MAX_FEEDBACK_EXAMPLES
) -> tuple:
    """Build the agent's feedback text from set A only.

    Set A is the ONLY set this function -- and therefore the proposer --
    ever sees. B and C's DataFrames are never passed here anywhere in the
    orchestrator. That is the Goodhart guard, enforced structurally by the
    call graph rather than merely by convention.

    Args:
        merged_a: Set A's ground-truth + prediction DataFrame (from
            `score_split(...).merged`).
        max_examples: Cap on the number of raw misclassified examples
            included (spec: ~10-15; default 12).

    Returns:
        Tuple of `(feedback_text, failures_read, confusion_stats)`:
            - feedback_text: human-readable string sent to the proposer.
            - failures_read: list of dicts (`id`, `text_snippet`,
              `true_label`, `predicted_label`), capped at `max_examples` --
              logged verbatim in the run log's `failures_read` field.
            - confusion_stats: dict of `"{true}->{pred}": count` for every
              off-diagonal confusion pair with count > 0.
    """
    wrong = merged_a[merged_a["category"] != merged_a["pred_category"]]
    failures_read = [
        {
            "id": int(row["id"]),
            "text_snippet": str(row["text"])[:200],
            "true_label": row["category"],
            "predicted_label": row["pred_category"],
        }
        for _, row in wrong.head(max_examples).iterrows()
    ]
    confusion_stats = _confusion_stats(merged_a)
    cat_f1 = macro_average(compute_metrics(merged_a, "category"))["f1"]

    lines = [
        f"Set A: {len(wrong)} of {len(merged_a)} misclassified "
        f"(category macro-F1 {cat_f1:.3f}).",
        "",
        "Confusion patterns (true -> predicted, count):",
    ]
    if confusion_stats:
        lines += [
            f"  {k.replace('->', ' -> ')}  x{v}" for k, v in confusion_stats.items()
        ]
    else:
        lines.append("  (none -- every miss is a one-off, no systematic pattern)")
    lines.append("")
    lines.append(f"Misclassified examples (up to {max_examples}):")
    for f in failures_read:
        lines.append(
            f"  id={f['id']}  true={f['true_label']}  predicted={f['predicted_label']}"
        )
        lines.append(f"    {f['text_snippet']}")

    return "\n".join(lines), failures_read, confusion_stats


def plateau_detected(b_f1_history: list, n: int = DEFAULT_PLATEAU_N) -> bool:
    """True if the last `n` entries of `b_f1_history` set no new best.

    Standard "patience" early-stopping semantics: track the running best and
    a stall counter that resets on any STRICT improvement. A tie does not
    reset the counter -- matching a new best exactly is not progress.
    Needs at least `n + 1` points (a baseline before the plateau window can
    even be evaluated).

    Args:
        b_f1_history: B-split category macro-F1, one entry per iteration
            (index 0 = the baseline).
        n: Consecutive non-improving iterations required to call it a
            plateau. Spec section 5.4: N=3.

    Returns:
        True if a plateau of length `n` has occurred by the end of the
        history.
    """
    if len(b_f1_history) < n + 1:
        return False
    best_so_far = b_f1_history[0]
    stall = 0
    for v in b_f1_history[1:]:
        if v > best_so_far:
            best_so_far = v
            stall = 0
        else:
            stall += 1
        if stall >= n:
            return True
    return False


def check_done_signal(
    b_f1_history: list,
    target_f1: float,
    iteration: int,
    iteration_cap: int,
    tokens_spent: int,
    token_budget: int,
    plateau_n: int = DEFAULT_PLATEAU_N,
) -> str | None:
    """Evaluate the done-signal in fixed precedence order (spec section 5.4).

    Precedence: THRESHOLD, then PLATEAU, then BUDGET (iteration cap or token
    budget -- whichever binds first). BUDGET is checked last so it is the
    guaranteed backstop (F8): even if the threshold/plateau logic has a bug,
    a runaway loop still halts.

    THRESHOLD never fires at iteration 0: the baseline is scored before any
    prompt edit exists, so a target at or below the starting B score would
    otherwise stop the run with zero proposals and report a "successful"
    threshold convergence on the un-optimized prompt -- a vacuous signal.
    A run must make at least one edit before it may declare done-by-target.
    The BUDGET backstop still applies at iteration 0 (F8 is unconditional).

    Reads only `b_f1_history` -- set A is never consulted here, which is
    what keeps the stop condition honest (the Goodhart guard: optimizing and
    detecting "done" on the same set would make the signal optimistically
    biased).

    Args:
        b_f1_history: B-split category macro-F1 per iteration so far.
        target_f1: THRESHOLD target for the primary metric on B.
        iteration: Current iteration number.
        iteration_cap: Hard cap on iteration number (F8).
        tokens_spent: Cumulative tokens spent so far.
        token_budget: Hard cap on cumulative tokens (F8).
        plateau_n: Consecutive non-improving iterations that count as a
            plateau. Spec section 5.4: N=3.

    Returns:
        `"threshold"`, `"plateau"`, `"budget_iterations"`, `"budget_tokens"`,
        or `None` if the loop should continue.
    """
    if iteration >= 1 and b_f1_history and b_f1_history[-1] >= target_f1:
        return "threshold"
    if plateau_detected(b_f1_history, plateau_n):
        return "plateau"
    if iteration >= iteration_cap:
        return "budget_iterations"
    if tokens_spent >= token_budget:
        return "budget_tokens"
    return None


def select_best_iteration(records: list) -> int:
    """Return the iteration number with the highest B macro-F1.

    Never reads C (that would consume the held-out set for a decision) and
    never defaults to "last iteration" -- a plateau-stop's last prompt is,
    by definition, not the best: the loop kept trying for `plateau_n` more
    iterations after the peak and none of them improved. Ties keep the
    earliest iteration (Python's `max()` returns the first max on a tie),
    matching the intuition that the simplest prompt reaching peak B-F1
    should win over a later, more-edited one that only matched it.

    Args:
        records: Iteration records, each with an `"iteration"` int and a
            `"scores"` dict containing a `"B"` sub-dict with `"macro_f1"`.

    Returns:
        The iteration number (int) of the best-scoring record.

    Raises:
        ValueError: If `records` is empty.
    """
    if not records:
        raise ValueError("records must contain at least one iteration")
    best = max(records, key=lambda r: r["scores"]["B"]["macro_f1"])
    return best["iteration"]


def prompt_diff(old: str, new: str) -> str:
    """Unified diff between two prompt versions, for the run log + replay.

    Args:
        old: Previous iteration's prompt.
        new: This iteration's (revised) prompt.

    Returns:
        Unified-diff text (empty string if the two prompts are identical).
    """
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile="prev",
        tofile="revised",
    )
    return "".join(diff)


def make_run_metadata(
    model: str,
    token_budget: int,
    iteration_cap: int,
    split_hashes: dict,
    start_prompt: str,
    seed: int,
) -> dict:
    """Build the run log's first line: the run-level metadata record.

    Args:
        model: Anthropic model id used for both scoring and proposing.
        token_budget: Configured token budget (F8 fail-safe).
        iteration_cap: Configured hard iteration cap (F8 fail-safe).
        split_hashes: `{"A":.., "B":.., "C":..}` id-list hashes from
            `make_split`, so a reader can confirm two runs used the same
            (or provably different) split.
        start_prompt: The prompt iteration 0 was scored with.
        seed: Split RNG seed, for reproducibility.

    Returns:
        A `type: "run_metadata"` dict, JSON-serializable.
    """
    return {
        "type": "run_metadata",
        "model": model,
        "token_budget": int(token_budget),
        "iteration_cap": int(iteration_cap),
        "split_hashes": split_hashes,
        "start_prompt": start_prompt,
        "seed": int(seed),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def make_iteration_record(
    iteration: int,
    prompt: str,
    prompt_diff_text: str | None,
    scores: dict,
    failures_read: list,
    confusion_stats: dict,
    agent_rationale: str | None,
    edit_summary: str | None,
    tokens_spent: int,
    done_signal: str | None,
    unclassified: dict | None = None,
) -> dict:
    """Build one run-log iteration record (spec section 8 schema).

    Args:
        iteration: Iteration number (0 = baseline, no edit).
        prompt: The full prompt text scored this iteration.
        prompt_diff_text: Unified diff vs. the previous iteration's prompt,
            or `None` at iteration 0 (no previous prompt to diff against).
        scores: `{"A": {...}, "B": {...}, "C": {...}}`, each a
            `SplitScore.as_dict()`.
        failures_read: Misclassified examples from set A that this
            iteration's proposal was based on (`[]` at iteration 0).
        confusion_stats: Set-A confusion pairs behind that proposal (`{}`
            at iteration 0).
        agent_rationale: The proposer's stated reasoning, or `None` at
            iteration 0.
        edit_summary: One-line summary of the edit, or `None` at
            iteration 0.
        tokens_spent: Cumulative tokens spent through this iteration.
        done_signal: Name of the fired stop condition, or `None` if the
            loop continues past this iteration.
        unclassified: Per-split count of rows that never got a valid label
            from `classify()` even after its own retries, e.g.
            `{"A": 1, "B": 0, "C": 0}`. Additive/optional: defaults to all
            zeros when not passed, so a record with no unclassified rows is
            still schema-valid and existing readers (the portfolio viewer,
            older run logs) are unaffected.

    Returns:
        A `type: "iteration"` dict, JSON-serializable.
    """
    return {
        "type": "iteration",
        "iteration": int(iteration),
        "prompt": prompt,
        "prompt_diff": prompt_diff_text,
        "scores": scores,
        "failures_read": failures_read,
        "confusion_stats": confusion_stats,
        "agent_rationale": agent_rationale,
        "edit_summary": edit_summary,
        "tokens_spent": int(tokens_spent),
        "done_signal": done_signal,
        "unclassified": unclassified or {"A": 0, "B": 0, "C": 0},
    }


def iteration_records(records: list) -> list:
    """Filter a full run-log record list down to just the iteration records.

    Args:
        records: All records as read back by `read_run_log` (metadata +
            iterations + summary).

    Returns:
        Just the `type == "iteration"` records, in order.
    """
    return [r for r in records if r.get("type") == "iteration"]


def make_run_summary(records: list, done_signal: str | None) -> dict:
    """Build the run log's trailer line: winner + overfitting headline.

    Everything here is a pure function of `records` -- recomputable
    standalone from the log alone, nothing here is new information. Kept as
    a trailer rather than folded into the leading metadata record, because
    metadata is written before iteration 0 runs and `best_iteration` is not
    known yet at that point. See decisions/005 "Resolved during
    implementation".

    Args:
        records: All iteration records from this run, in order (index 0 is
            the baseline).
        done_signal: The condition that stopped the run.

    Returns:
        A `type: "run_summary"` dict, JSON-serializable.
    """
    best_iteration = select_best_iteration(records)
    first, last = records[0], records[-1]
    best = next(r for r in records if r["iteration"] == best_iteration)
    # Deltas and the overfitting headline are measured baseline -> BEST, not
    # baseline -> final: on a plateau or budget stop the final prompt is by
    # construction not the winner, and reporting the discarded prompt's gap
    # next to best_iteration would attribute the wrong number to the prompt
    # actually being shipped.
    delta = {
        split: round(
            best["scores"][split]["macro_f1"] - first["scores"][split]["macro_f1"], 4
        )
        for split in ("A", "B", "C")
    }
    return {
        "type": "run_summary",
        "best_iteration": best_iteration,
        "final_iteration": last["iteration"],
        "done_signal": done_signal,
        "delta_macro_f1": delta,
        "overfitting_gap_a_vs_c": round(delta["A"] - delta["C"], 4),
        "total_tokens_spent": last["tokens_spent"],
    }


def new_run_log_path(directory: str = RUN_LOG_DIR) -> str:
    """Build a fresh timestamped run-log path and ensure its directory exists.

    Args:
        directory: Directory the run log lives under. Defaults to
            `evals/optimize/`.

    Returns:
        Path like `evals/optimize/run_20260710T153000Z.jsonl`.
    """
    os.makedirs(directory, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join(directory, f"run_{ts}.jsonl")


def append_run_log(path: str, record: dict) -> None:
    """Append one record as a JSON line to the run-log file (creates it if new).

    Appending -- never rewriting the whole file -- is what makes the run's
    DATA crash-safe (N4): a crash mid-run loses at most the in-progress
    iteration's record, never any already-completed one. Note the guarantee
    is about the log, not the process: unlike `eval.py`'s per-row resume,
    a re-run after a crash starts a fresh run from iteration 0 (and, live,
    re-spends the tokens). Continuing a partial run from its log is future
    work, recorded in decisions/005.

    Args:
        path: Run-log JSONL file path.
        record: JSON-serializable dict (a run_metadata, iteration, or
            run_summary record).
    """
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_run_log(path: str) -> list:
    """Read a run-log JSONL file back into a list of records, in file order.

    The run reconstructs entirely from this: index 0 is the run_metadata
    record, the last is the run_summary trailer (if the run completed
    normally), and everything between is one dict per iteration (F5). Use
    `iteration_records()` to filter to just the per-iteration records.

    Args:
        path: Run-log JSONL file path.

    Returns:
        List of record dicts, in the order they were written.
    """
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Backend -- everything that talks to the Anthropic API, or fakes doing so.
# ---------------------------------------------------------------------------


def _estimate_tokens(system_prompt: str, text: str) -> int:
    """Rough token-count estimate for one classify() scoring call.

    See the module-level comment above `_CHARS_PER_TOKEN` for why this is
    an estimate rather than an exact count.

    Args:
        system_prompt: The prompt being scored.
        text: The article snippet being classified.

    Returns:
        Estimated input tokens (~4 chars/token, rounded up) plus fixed
        allowances for the structured-output tool call and the per-request
        overhead (tool schema + message framing) that character counting
        never sees.
    """
    input_chars = len(system_prompt) + len(text)
    estimated_input = -(-input_chars // _CHARS_PER_TOKEN)  # ceil div
    return estimated_input + _ESTIMATED_OUTPUT_TOKENS + _PER_CALL_OVERHEAD_TOKENS


OPTIMIZER_SYSTEM_PROMPT = """You are optimizing the system prompt for a defense-news \
classifier. The classifier assigns each article snippet a `category` (procurement, \
operations, policy, technology, industry) and an `operational_domain` (air, land, sea, \
cyber, space, multi).

You will be shown the classifier's CURRENT system prompt and a feedback report describing \
where it is failing on a held-out set of examples: raw misclassified cases (true label vs. \
predicted label) and aggregate confusion patterns (e.g. "industry -> procurement x8" means \
industry articles are systematically mistaken for procurement).

Propose a REVISED system prompt that addresses the failure patterns you see. Keep the label \
definitions intact -- the five categories and six domains are fixed; do not add, remove, or \
rename any label. Tighten the instructions, add disambiguating guidance, or clarify boundary \
cases between labels that are being confused. Return the full revised prompt text (not a \
diff), a short rationale for what you changed and why, and a one-line summary of the edit."""

PROPOSE_TOOL: ToolParam = {
    "name": "propose_revision",
    "description": "Return a revised classifier system prompt plus rationale.",
    "input_schema": {
        "type": "object",
        "properties": {
            "revised_prompt": {
                "type": "string",
                "description": "The complete revised system prompt text.",
            },
            "rationale": {
                "type": "string",
                "description": "Why these changes should fix the observed failure patterns.",
            },
            "edit_summary": {
                "type": "string",
                "description": "One-line summary of what changed.",
            },
        },
        "required": ["revised_prompt", "rationale", "edit_summary"],
    },
}


def _build_proposer_message(current_prompt: str, feedback: str) -> str:
    """Assemble the user-turn content sent to the optimizer model.

    Args:
        current_prompt: The prompt being revised.
        feedback: Set-A-only feedback text from `build_feedback`.

    Returns:
        The message string.
    """
    return (
        f"CURRENT SYSTEM PROMPT:\n{current_prompt}\n\n"
        f"FEEDBACK FROM SET A (failures only; this is the only set you ever see):\n{feedback}"
    )


def _classify_retry(
    client: anthropic.Anthropic,
    text: str,
    model: str,
    system_prompt: str,
    max_retries: int = 3,
) -> dict:
    """classify() with exponential backoff on transient API errors.

    Mirrors `gold_eval.classify_retry` (which cannot be reused directly
    because it does not take a `system_prompt`, and the loop scores a
    different prompt every iteration). A live run makes ~354 scoring calls
    per iteration for many iterations unattended; without this, a single
    429/500 mid-run aborts the whole loop and forfeits every already-paid
    iteration.

    Args:
        client: Authenticated Anthropic client.
        text: Article snippet to classify.
        model: Model id for the call.
        system_prompt: The (iteration-specific) prompt being scored.
        max_retries: Maximum number of attempts before re-raising.

    Only retries the transient API errors below -- `classify.InvalidLabelError`
    (the model persistently returning an out-of-enum label) is a different
    failure mode with its own retry budget already spent inside `classify()`
    itself, so it is deliberately NOT caught here; it propagates to the
    caller, which is `AnthropicBackend.score()`'s job to handle (record the
    `UNCLASSIFIED` sentinel and keep going, rather than aborting the run).

    Returns:
        Dict with keys ``category`` and ``operational_domain``.

    Raises:
        anthropic.InternalServerError: If all retries are exhausted on a 500.
        anthropic.RateLimitError: If all retries are exhausted on a 429.
        classify.InvalidLabelError: If classify() itself exhausts its own
            re-sample budget on an out-of-enum label. Not retried here.
    """
    for attempt in range(max_retries):
        try:
            return classify(client, text, model=model, system_prompt=system_prompt)
        except (anthropic.InternalServerError, anthropic.RateLimitError):
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise ValueError("max_retries must be >= 1")


class AnthropicBackend:
    """Live backend: scores via classify(), proposes via a direct tool-use call.

    Every method call here spends real tokens against a real Anthropic key.
    Only ever constructed from the live CLI path (`main()` without
    `--dry-run`) -- never from tests, never from `--dry-run`.
    """

    def __init__(self, client: anthropic.Anthropic, model: str = MODEL) -> None:
        """Build the live backend.

        Args:
            client: Authenticated Anthropic client (see `classify.make_client`).
            model: Model id for both scoring (classify calls) and proposing.
        """
        self.client = client
        self.model = model

    def score(self, prompt: str, df: pd.DataFrame) -> ScoreOutcome:
        """Classify every row of `df` under `prompt` via `classify()`.

        Reuses `classify()` itself rather than a hand-rolled duplicate
        request, so the loop inherits its label-validation and
        re-sample-on-invalid-label safety net for free -- wrapped in
        `_classify_retry` so a transient 429/500 backs off and retries
        instead of aborting the whole unattended run.

        A row that is STILL unclassifiable after classify()'s own retries
        (an `InvalidLabelError`, e.g. the model returning a domain value
        like "cyber" in the category field) is not allowed to abort the
        run either: it is recorded with the `UNCLASSIFIED` sentinel on both
        prediction columns -- guaranteed wrong on both axes, San's chosen
        "count it as a miss" semantics -- and scoring continues. This is
        never silent: a warning line prints per occurrence, and the caller
        surfaces the count via `ScoreOutcome.unclassified_ids` into the run
        log's `unclassified` field.

        Args:
            prompt: System prompt to score.
            df: Ground-truth DataFrame with `id` and `text` columns.

        Returns:
            `ScoreOutcome` with the merged predictions DataFrame, an
            estimated token count (see `_estimate_tokens`), and the ids of
            any rows that fell back to the unclassified sentinel.
        """
        rows = []
        tokens = 0
        unclassified_ids: list = []
        total = len(df)
        for i, (_, row) in enumerate(df.iterrows()):
            try:
                pred = _classify_retry(
                    self.client, row["text"], model=self.model, system_prompt=prompt
                )
                pred_category = pred["category"]
                pred_domain = pred["operational_domain"]
            except InvalidLabelError:
                pred_category = UNCLASSIFIED
                pred_domain = UNCLASSIFIED
                unclassified_ids.append(row["id"])
                print(
                    f"    row {row['id']}: unclassified after retries, "
                    "counting as a miss",
                    flush=True,
                )
            rows.append(
                {
                    "id": row["id"],
                    "pred_category": pred_category,
                    "pred_operational_domain": pred_domain,
                }
            )
            tokens += _estimate_tokens(prompt, row["text"])
            if (i + 1) % 25 == 0 or i + 1 == total:
                print(f"    scored {i + 1:3d}/{total}", flush=True)
        merged = df.merge(pd.DataFrame(rows), on="id")
        return ScoreOutcome(
            merged=merged, tokens=tokens, unclassified_ids=unclassified_ids
        )

    def propose(self, current_prompt: str, feedback: str) -> ProposeOutcome:
        """Ask the optimizer model for a revised prompt, with exact token usage.

        Args:
            current_prompt: The prompt being revised.
            feedback: Set-A-only feedback text from `build_feedback`.

        Returns:
            `ProposeOutcome` with the revised prompt, rationale, edit
            summary, and exact input+output token count from
            `response.usage`.
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=OPTIMIZER_SYSTEM_PROMPT,
            tools=[PROPOSE_TOOL],
            tool_choice={"type": "tool", "name": "propose_revision"},
            messages=[
                {
                    "role": "user",
                    "content": _build_proposer_message(current_prompt, feedback),
                }
            ],
        )
        tool_block = next(b for b in response.content if isinstance(b, ToolUseBlock))
        payload = cast(dict, tool_block.input)
        tokens = int(response.usage.input_tokens) + int(response.usage.output_tokens)
        return ProposeOutcome(
            revised_prompt=payload["revised_prompt"],
            rationale=payload["rationale"],
            edit_summary=payload["edit_summary"],
            tokens=tokens,
        )


_DRYRUN_EDIT_MARKER = "[dry-run edit"


def _next_category(true_category: str) -> str:
    """Deterministic 'wrong' label: the next category in the fixed CATEGORIES cycle.

    Args:
        true_category: The ground-truth category.

    Returns:
        A different, fixed category (cycles through `CATEGORIES`), so
        `DryRunBackend`'s simulated errors spread evenly rather than always
        landing on one label.
    """
    idx = CATEGORIES.index(true_category)
    return CATEGORIES[(idx + 1) % len(CATEGORIES)]


class DryRunBackend:
    """Deterministic, zero-API backend for `--dry-run` and offline testing.

    Both methods are pure functions of their inputs -- no network, no
    wall-clock randomness. `score()` derives each row's simulated
    correctness from a stable hash of (row id, prompt), so the same
    prompt+split always scores identically, and accuracy improves as more
    `propose()` edits accumulate in the prompt -- enough for a `--dry-run`
    run to demonstrate a real threshold/plateau path end-to-end.
    `propose()` mutates the prompt by appending a numbered marker line, so
    `prompt_diff` and the run log are real and inspectable, never fabricated
    after the fact. Tokens are always 0 -- no call was made to spend any.
    Domain is always scored correct: the primary metric (spec section 5.5)
    is category macro-F1 only, so simulating domain confusion would add
    nothing but noise to the mock.
    """

    def __init__(
        self,
        start_accuracy: float = 0.55,
        improvement_per_edit: float = 0.08,
        ceiling: float = 0.93,
    ) -> None:
        """Build the mock backend.

        Args:
            start_accuracy: Simulated category accuracy at iteration 0.
            improvement_per_edit: Accuracy gained per accumulated dry-run
                edit marker in the prompt.
            ceiling: Cap on simulated accuracy, so the curve plateaus
                (exercising the PLATEAU done-signal) rather than climbing
                forever.
        """
        self.start_accuracy = start_accuracy
        self.improvement_per_edit = improvement_per_edit
        self.ceiling = ceiling

    def _accuracy_for(self, prompt: str) -> float:
        """Simulated accuracy for `prompt`, based on its accumulated edit count."""
        edits = prompt.count(_DRYRUN_EDIT_MARKER)
        return min(
            self.start_accuracy + self.improvement_per_edit * edits, self.ceiling
        )

    @staticmethod
    def _correct(row_id, prompt: str, accuracy: float) -> bool:
        """Stable pseudo-random correct/incorrect draw for one (id, prompt) pair.

        Uses a content hash rather than Python's built-in `hash()` (salted
        per-process for strings) so the same (id, prompt) always yields the
        same simulated outcome, run after run.
        """
        digest = hashlib.md5(f"{row_id}:{prompt}".encode()).hexdigest()
        draw = int(digest[:8], 16) / 0xFFFFFFFF
        return draw < accuracy

    def score(self, prompt: str, df: pd.DataFrame) -> ScoreOutcome:
        """Deterministic mock scoring -- see class docstring.

        Args:
            prompt: System prompt to score.
            df: Ground-truth DataFrame with `id`, `category`,
                `operational_domain` columns.

        Returns:
            `ScoreOutcome` with simulated predictions and `tokens=0`.
        """
        accuracy = self._accuracy_for(prompt)
        rows = []
        for _, row in df.iterrows():
            correct = self._correct(row["id"], prompt, accuracy)
            pred_category = (
                row["category"] if correct else _next_category(row["category"])
            )
            rows.append(
                {
                    "id": row["id"],
                    "pred_category": pred_category,
                    "pred_operational_domain": row["operational_domain"],
                }
            )
        merged = df.merge(pd.DataFrame(rows), on="id")
        return ScoreOutcome(merged=merged, tokens=0)

    def propose(self, current_prompt: str, feedback: str) -> ProposeOutcome:
        """Deterministic mock proposal: appends a numbered edit marker.

        Args:
            current_prompt: The prompt being revised.
            feedback: Unused by the mock (accepted to match the interface);
                a real run's feedback is what `AnthropicBackend.propose`
                reasons over.

        Returns:
            `ProposeOutcome` with the mutated prompt and `tokens=0`.
        """
        edits = current_prompt.count(_DRYRUN_EDIT_MARKER) + 1
        marker = (
            f"{_DRYRUN_EDIT_MARKER} #{edits}: tightened boundary guidance "
            "from set-A feedback.]"
        )
        revised = f"{current_prompt}\n{marker}"
        return ProposeOutcome(
            revised_prompt=revised,
            rationale=(
                "[dry-run] Deterministic mock proposer: appended a synthetic "
                "edit marker rather than reasoning over feedback text. Not a "
                "real prompt improvement -- see evals/optimize/README.md."
            ),
            edit_summary=f"Appended dry-run edit marker #{edits}.",
            tokens=0,
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_optimization(
    backend: OptimizerBackend,
    split: Split,
    config: OptimizationConfig,
    run_log_path: str | None = None,
) -> str:
    """Run the prompt-optimization loop end-to-end and return the run-log path.

    Iteration 0 scores `config.start_prompt` on A/B/C with no edit (the
    baseline). Each iteration after that: build feedback from set A's
    failures only, ask `backend.propose()` for a revised prompt, re-score
    A/B/C under the revision, append a run-log record, and check the
    done-signal (fixed precedence -- see `check_done_signal`). The loop
    always halts, even on a logic bug elsewhere, because the budget check is
    the unconditional backstop (F8).

    Args:
        backend: `DryRunBackend` for a zero-API run/test; `AnthropicBackend`
            for a real run.
        split: The A/B/C split + hashes from `make_split`.
        config: Tunable run parameters (see `OptimizationConfig`).
        run_log_path: Where to write the JSONL run log. Defaults to a fresh
            timestamped path under `evals/optimize/`.

    Returns:
        Path to the completed run-log JSONL file.
    """
    if run_log_path is None:
        run_log_path = new_run_log_path()
    else:
        parent = os.path.dirname(run_log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    metadata = make_run_metadata(
        model=config.model,
        token_budget=config.token_budget,
        iteration_cap=config.max_iterations,
        split_hashes=split.hashes,
        start_prompt=config.start_prompt,
        seed=config.seed,
    )
    append_run_log(run_log_path, metadata)

    prompt = config.start_prompt
    tokens_spent = 0
    b_f1_history: list = []
    records: list = []

    # --- iteration 0: baseline, no edit -------------------------------
    print(
        f"Iteration 0 (baseline): scoring A={len(split.a)} B={len(split.b)} "
        f"C={len(split.c)}...",
        flush=True,
    )
    score_a = score_split(prompt, backend, split.a)
    score_b = score_split(prompt, backend, split.b)
    score_c = score_split(prompt, backend, split.c)
    tokens_spent += score_a.tokens + score_b.tokens + score_c.tokens
    b_f1_history.append(score_b.macro_f1)

    signal = check_done_signal(
        b_f1_history,
        config.target_f1,
        0,
        config.max_iterations,
        tokens_spent,
        config.token_budget,
        config.plateau_n,
    )
    print(
        f"  A macro-F1={score_a.macro_f1:.3f}  B macro-F1={score_b.macro_f1:.3f}  "
        f"C macro-F1={score_c.macro_f1:.3f}  tokens={tokens_spent}",
        flush=True,
    )
    record = make_iteration_record(
        iteration=0,
        prompt=prompt,
        prompt_diff_text=None,
        scores={"A": score_a.as_dict(), "B": score_b.as_dict(), "C": score_c.as_dict()},
        failures_read=[],
        confusion_stats={},
        agent_rationale=None,
        edit_summary=None,
        tokens_spent=tokens_spent,
        done_signal=signal,
        unclassified={
            "A": len(score_a.unclassified_ids),
            "B": len(score_b.unclassified_ids),
            "C": len(score_c.unclassified_ids),
        },
    )
    append_run_log(run_log_path, record)
    records.append(record)

    # --- iterations 1..N: propose, re-score, check ---------------------
    iteration = 0
    while signal is None:
        feedback_text, failures_read, confusion_stats = build_feedback(
            score_a.merged, config.max_feedback_examples
        )
        iteration += 1
        print(
            f"Iteration {iteration}: proposing a revision from set-A feedback...",
            flush=True,
        )
        proposal = backend.propose(prompt, feedback_text)
        tokens_spent += int(proposal.tokens)

        previous_prompt = prompt
        prompt = proposal.revised_prompt
        diff_text = prompt_diff(previous_prompt, prompt)

        score_a = score_split(prompt, backend, split.a)
        score_b = score_split(prompt, backend, split.b)
        score_c = score_split(prompt, backend, split.c)
        tokens_spent += score_a.tokens + score_b.tokens + score_c.tokens
        b_f1_history.append(score_b.macro_f1)

        signal = check_done_signal(
            b_f1_history,
            config.target_f1,
            iteration,
            config.max_iterations,
            tokens_spent,
            config.token_budget,
            config.plateau_n,
        )
        print(
            f"  A macro-F1={score_a.macro_f1:.3f}  B macro-F1={score_b.macro_f1:.3f}  "
            f"C macro-F1={score_c.macro_f1:.3f}  tokens={tokens_spent}",
            flush=True,
        )
        if signal:
            print(f"  done-signal: {signal}", flush=True)
        record = make_iteration_record(
            iteration=iteration,
            prompt=prompt,
            prompt_diff_text=diff_text,
            scores={
                "A": score_a.as_dict(),
                "B": score_b.as_dict(),
                "C": score_c.as_dict(),
            },
            failures_read=failures_read,
            confusion_stats=confusion_stats,
            agent_rationale=proposal.rationale,
            edit_summary=proposal.edit_summary,
            tokens_spent=tokens_spent,
            done_signal=signal,
            unclassified={
                "A": len(score_a.unclassified_ids),
                "B": len(score_b.unclassified_ids),
                "C": len(score_c.unclassified_ids),
            },
        )
        append_run_log(run_log_path, record)
        records.append(record)

    summary = make_run_summary(records, signal)
    append_run_log(run_log_path, summary)
    print(
        f"\nStopped: {signal}. Best iteration: {summary['best_iteration']} "
        f"(B macro-F1 history: {[round(v, 3) for v in b_f1_history]}).",
        flush=True,
    )

    return run_log_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point: run one optimization loop and print a short summary.

    Raises:
        EnvironmentError: If not `--dry-run` and `ANTHROPIC_API_KEY` is not
            set (via `make_client`).
    """
    parser = argparse.ArgumentParser(description="Rung-1 prompt-optimization loop.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="zero-API deterministic mock run (no key needed)",
    )
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    parser.add_argument("--target-f1", type=float, default=DEFAULT_TARGET_F1)
    parser.add_argument(
        "--plateau",
        type=int,
        default=DEFAULT_PLATEAU_N,
        help="iterations without a new best-B before stopping",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--split-ratio", type=float, default=DEFAULT_SPLIT_RATIO)
    parser.add_argument("--model", type=str, default=MODEL)
    args = parser.parse_args()

    df_synth = pd.read_csv(DATA_PATH)
    df_gold = load_gold(GOLD_PATH).rename(columns={"domain": "operational_domain"})
    split = make_split(df_synth, df_gold, ratio=args.split_ratio, seed=args.seed)

    config = OptimizationConfig(
        start_prompt=SYSTEM_PROMPT,
        model=args.model,
        max_iterations=args.max_iterations,
        token_budget=args.token_budget,
        target_f1=args.target_f1,
        plateau_n=args.plateau,
        seed=args.seed,
    )

    if args.dry_run:
        print("Dry run: zero API calls, deterministic mock backend.\n")
        backend: OptimizerBackend = DryRunBackend()
    else:
        n_calls_per_iter = len(split.a) + len(split.b) + len(split.c) + 1
        print(
            f"LIVE run: ~{n_calls_per_iter} API calls per iteration, up to "
            f"{args.max_iterations} iterations, model={args.model}. This spends "
            f"real tokens -- see README.md before running unattended.\n"
        )
        client = make_client()
        backend = AnthropicBackend(client, model=args.model)

    path = run_optimization(backend, split, config)
    print(f"\nRun log written to {path}")


if __name__ == "__main__":
    main()
