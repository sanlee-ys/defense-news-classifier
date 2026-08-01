"""Rung 2 of the autonomy ladder: the agent-driven ML loop.

Rung 1 (``src/optimize.py``) put an agent in charge of a *prompt*; this puts the
same loop architecture in charge of a *classical ML model* -- the TF-IDF +
logistic-regression baseline ADR-017 measured. The inner loop is mechanical
(sklearn fits to convergence, no judgment); the outer loop is agentic: the
proposer reads misclassified examples and confusion statistics, decides the next
experiment (vectorizer changes, regularization, error-driven keyword features),
and iterates until an explicit done-signal fires. The judgment -- *which*
experiment to run next, based on *reading the errors* -- is what distinguishes
this from a grid search.

What is deliberately reused from rung 1, so the two rungs share one honesty
architecture (ADR-005):

- The 3-way split. A (~210 of the 300 judge-graded rows) is what the agent sees:
  its feedback is misclassified examples + confusion stats. B (~90) drives the
  done-signal and best-iteration selection; the agent never sees a B row. C (the
  54-row human gold set) is scored each iteration but read by NO decision --
  ``check_done_signal`` and ``select_best_iteration`` are imported from
  ``optimize`` unchanged, and both consume B only.
- The done-signal: threshold OR plateau (N consecutive non-improving B scores)
  OR budget, in that precedence, with budget as the unconditional backstop.
- The append-only JSONL run log with the same metadata/iteration/summary record
  shapes, so the replay viewer's format carries over.
- The deterministic, zero-cost proposal guard: an invalid experiment is caught
  by ``validate_experiment`` BEFORE any fitting, retried, and a proposer that
  cannot produce a valid experiment raises ``ProposalError`` rather than letting
  the run score garbage (the same shape as rung 1's region-rubric freeze).

What is different, and why:

- Scoring is free and local (sklearn on 300 rows), so only the PROPOSER spends
  tokens. The token budget therefore gates proposer calls; scoring is unmetered.
- The agent's feedback comes from OUT-OF-FOLD predictions on A (5-fold CV inside
  A), not from the fitted model's predictions on its own training rows. A model
  scoring its own training set memorizes it (~100% on A) and would hand the
  agent an empty failure list; the OOF view is the honest generalization signal.
- Two axes only (category, operational_domain): the judge-graded training data
  has no region labels until the scaled region eval ships -- same disclosed
  limit as ADR-017.

The Goodhart read, mirrored from rung 1: A-vs-B separates "memorized the
feedback set" from real improvement; B-vs-C separates "fit the judge's labeling
style" from agreement with humans. Both gaps are in every run log.

Run offline (no API key, deterministic canned proposer):
    uv run python src/ml_loop.py --dry-run

Run live (proposer = the SYS-002 default Sonnet; San drives live runs):
    uv run --env-file .env python src/ml_loop.py --max-iterations 8 --token-budget 100000

Each run writes an append-only JSONL log to evals/ml_loop/run_<UTC>.jsonl
(gitignored, like rung 1's evals/optimize/ logs).
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from typing import Protocol, cast

import anthropic
import numpy as np
import pandas as pd
from anthropic.types import ToolParam, ToolUseBlock
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold

import api_retry
from baseline_ml import AXES, load_train
from classify import MODEL
from eval import compute_metrics, macro_average
from optimize import (
    ProposalError,
    append_run_log,
    check_done_signal,
    new_run_log_path,
    select_best_iteration,
)

GOLD_PATH = "data/gold/gold.csv"
RUN_LOG_DIR = "evals/ml_loop"

DEFAULT_SEED = 42
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_TOKEN_BUDGET = 100_000
DEFAULT_PLATEAU_N = 3
MAX_FEEDBACK_EXAMPLES = 12
FEEDBACK_SNIPPET_CHARS = 280

# Threshold target for the done-signal, on the primary metric: the MEAN of the
# two axes' macro-F1 on split B. ADR-017's baseline landed around 0.53/0.71
# macro-F1 on gold; 0.85 on B is deliberately out of easy reach so live runs
# stop on plateau or budget and the threshold only fires on a genuine jump.
# CLI-tunable via --target-f1, same caveat as rung 1's placeholder.
DEFAULT_TARGET_F1 = 0.85

# ---------------------------------------------------------------------------
# The experiment space -- the bounded set of moves the agent may make.
# ---------------------------------------------------------------------------

# The starting experiment IS the ADR-017 shipped configuration, so iteration 0
# of every run log is the measured baseline and improvements are read against a
# published anchor rather than an arbitrary start.
DEFAULT_EXPERIMENT: dict = {
    "vectorizer": {
        "analyzer": "word",
        "ngram_min": 1,
        "ngram_max": 2,
        "min_df": 2,
        "max_features": None,
        "sublinear_tf": False,
        "stop_words": "english",
    },
    "model": {"C": 1.0, "class_weight": "balanced"},
    "keyword_features": [],
}

_ANALYZERS = ("word", "char_wb")
_STOP_WORDS = ("english", "none")
_CLASS_WEIGHTS = ("balanced", "none")
MAX_KEYWORD_GROUPS = 20
MAX_PATTERNS_PER_GROUP = 8
MAX_PATTERN_CHARS = 30


def validate_experiment(exp: object) -> list[str]:
    """Return every rule the proposed experiment violates (empty = valid).

    This is the rung-2 counterpart of rung 1's region-rubric guard:
    deterministic and free, run BEFORE any fitting, so a malformed proposal
    costs a retry rather than a scored-garbage iteration. The bounds exist to
    keep the search inside configurations sklearn will accept and a reader can
    audit -- not to steer the agent toward good ones; picking well is its job.

    Args:
        exp: The proposed experiment (any JSON-decoded object).

    Returns:
        List of human-readable violation strings; empty when valid.
    """
    problems: list[str] = []
    if not isinstance(exp, dict):
        return ["experiment must be a JSON object"]
    extra = set(exp) - {"vectorizer", "model", "keyword_features"}
    if extra:
        problems.append(f"unknown top-level keys: {sorted(extra)}")

    vec = exp.get("vectorizer")
    if not isinstance(vec, dict):
        problems.append("'vectorizer' must be an object")
        vec = {}
    if vec.get("analyzer") not in _ANALYZERS:
        problems.append(f"vectorizer.analyzer must be one of {_ANALYZERS}")
    ngram_min, ngram_max = vec.get("ngram_min"), vec.get("ngram_max")
    max_ngram = 6 if vec.get("analyzer") == "char_wb" else 3
    if not (isinstance(ngram_min, int) and 1 <= ngram_min <= max_ngram):
        problems.append(f"vectorizer.ngram_min must be an int in [1, {max_ngram}]")
    if not (isinstance(ngram_max, int) and 1 <= ngram_max <= max_ngram):
        problems.append(f"vectorizer.ngram_max must be an int in [1, {max_ngram}]")
    if (
        isinstance(ngram_min, int)
        and isinstance(ngram_max, int)
        and ngram_min > ngram_max
    ):
        problems.append("vectorizer.ngram_min must be <= ngram_max")
    if not (isinstance(vec.get("min_df"), int) and 1 <= vec["min_df"] <= 10):
        problems.append("vectorizer.min_df must be an int in [1, 10]")
    max_features = vec.get("max_features", None)
    if max_features is not None and not (
        isinstance(max_features, int) and 1_000 <= max_features <= 200_000
    ):
        problems.append(
            "vectorizer.max_features must be null or an int in [1000, 200000]"
        )
    if not isinstance(vec.get("sublinear_tf"), bool):
        problems.append("vectorizer.sublinear_tf must be a bool")
    if vec.get("stop_words") not in _STOP_WORDS:
        problems.append(f"vectorizer.stop_words must be one of {_STOP_WORDS}")

    model = exp.get("model")
    if not isinstance(model, dict):
        problems.append("'model' must be an object")
        model = {}
    c_value = model.get("C")
    if not (isinstance(c_value, (int, float)) and 0.01 <= c_value <= 100):
        problems.append("model.C must be a number in [0.01, 100]")
    if model.get("class_weight") not in _CLASS_WEIGHTS:
        problems.append(f"model.class_weight must be one of {_CLASS_WEIGHTS}")

    groups = exp.get("keyword_features", [])
    if not isinstance(groups, list) or len(groups) > MAX_KEYWORD_GROUPS:
        problems.append(
            f"keyword_features must be a list of at most {MAX_KEYWORD_GROUPS} groups"
        )
        groups = []
    names_seen: set[str] = set()
    for i, group in enumerate(groups):
        if not isinstance(group, dict) or set(group) != {"name", "patterns"}:
            problems.append(f"keyword_features[{i}] must be {{name, patterns}}")
            continue
        name = group["name"]
        if not (isinstance(name, str) and name.isidentifier()):
            problems.append(f"keyword_features[{i}].name must be an identifier")
        elif name in names_seen:
            problems.append(f"keyword_features[{i}].name duplicates '{name}'")
        else:
            names_seen.add(name)
        patterns = group["patterns"]
        if (
            not isinstance(patterns, list)
            or not patterns
            or len(patterns) > MAX_PATTERNS_PER_GROUP
            or not all(
                isinstance(p, str) and 0 < len(p) <= MAX_PATTERN_CHARS for p in patterns
            )
        ):
            problems.append(
                f"keyword_features[{i}].patterns must be 1-{MAX_PATTERNS_PER_GROUP} "
                f"strings of at most {MAX_PATTERN_CHARS} chars"
            )
    return problems


def experiment_diff(old: dict, new: dict) -> str:
    """One-line summary of what changed between two experiments, for the log.

    Args:
        old: Previous iteration's experiment.
        new: This iteration's experiment.

    Returns:
        Comma-separated ``path: old -> new`` fragments (or ``"(no change)"``).
    """
    changes = []
    for section in ("vectorizer", "model"):
        keys = set(old.get(section, {})) | set(new.get(section, {}))
        for key in sorted(keys):
            before = old.get(section, {}).get(key)
            after = new.get(section, {}).get(key)
            if before != after:
                changes.append(f"{section}.{key}: {before} -> {after}")
    old_groups = {g["name"] for g in old.get("keyword_features", [])}
    new_groups = {g["name"] for g in new.get("keyword_features", [])}
    for name in sorted(new_groups - old_groups):
        changes.append(f"+keyword_features.{name}")
    for name in sorted(old_groups - new_groups):
        changes.append(f"-keyword_features.{name}")
    return ", ".join(changes) if changes else "(no change)"


# ---------------------------------------------------------------------------
# The mechanical inner loop: build, fit, predict.
# ---------------------------------------------------------------------------


def _keyword_matrix(texts: pd.Series, groups: list) -> csr_matrix:
    """Binary indicator columns: does any of the group's substrings appear.

    Args:
        texts: Article snippets.
        groups: ``keyword_features`` list from a validated experiment.

    Returns:
        Sparse (len(texts) x len(groups)) 0/1 matrix.
    """
    lowered = texts.str.lower()
    columns = [
        lowered.map(lambda t, pats=g["patterns"]: any(p.lower() in t for p in pats))
        for g in groups
    ]
    if not columns:
        return csr_matrix((len(texts), 0), dtype=np.int64)
    stacked = np.column_stack([c.astype(int).to_numpy() for c in columns])
    return csr_matrix(stacked)


@dataclass
class FittedExperiment:
    """A fitted vectorizer + per-axis models for one experiment config."""

    experiment: dict
    vectorizer: TfidfVectorizer
    models: dict[str, LogisticRegression]

    def _features(self, texts: pd.Series) -> csr_matrix:
        tfidf = self.vectorizer.transform(texts)
        keywords = _keyword_matrix(texts, self.experiment["keyword_features"])
        return cast(csr_matrix, hstack([tfidf, keywords], format="csr"))

    def predict(self, texts: pd.Series) -> pd.DataFrame:
        """Predict both axes; columns named ``pred_*`` to match the harness."""
        feats = self._features(texts)
        return pd.DataFrame(
            {f"pred_{axis}": self.models[axis].predict(feats) for axis in AXES},
            index=texts.index,
        )


def fit_experiment(
    experiment: dict, train: pd.DataFrame, seed: int = DEFAULT_SEED
) -> FittedExperiment:
    """Fit one experiment configuration on the given rows (and nothing else).

    Args:
        experiment: A VALIDATED experiment dict.
        train: Rows to fit on (``text`` + axis label columns).
        seed: Random state for the logistic regressions.

    Returns:
        The fitted experiment.
    """
    vec_cfg = experiment["vectorizer"]
    vectorizer = TfidfVectorizer(
        analyzer=vec_cfg["analyzer"],
        ngram_range=(vec_cfg["ngram_min"], vec_cfg["ngram_max"]),
        min_df=vec_cfg["min_df"],
        max_features=vec_cfg["max_features"],
        sublinear_tf=vec_cfg["sublinear_tf"],
        stop_words=None if vec_cfg["stop_words"] == "none" else vec_cfg["stop_words"],
        lowercase=True,
    )
    tfidf = vectorizer.fit_transform(train["text"])
    keywords = _keyword_matrix(train["text"], experiment["keyword_features"])
    features = hstack([tfidf, keywords], format="csr")
    model_cfg = experiment["model"]
    class_weight = None if model_cfg["class_weight"] == "none" else "balanced"
    models = {}
    for axis in AXES:
        model = LogisticRegression(
            C=float(model_cfg["C"]),
            class_weight=class_weight,
            max_iter=1000,
            random_state=seed,
        )
        model.fit(features, train[axis])
        models[axis] = model
    return FittedExperiment(experiment=experiment, vectorizer=vectorizer, models=models)


# ---------------------------------------------------------------------------
# Splits and scoring.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Split:
    """A/B from the 300 judge-graded rows, C = the human gold set."""

    a: pd.DataFrame
    b: pd.DataFrame
    c: pd.DataFrame
    hashes: dict


def _hash_ids(ids: pd.Series) -> str:
    import hashlib

    joined = ",".join(sorted(ids.astype(str)))
    return hashlib.sha256(joined.encode()).hexdigest()[:12]


def make_split(seed: int = DEFAULT_SEED, b_fraction: float = 0.3) -> Split:
    """Build the A/B/C split, deterministic under ``seed``.

    A/B partition the 300 judge-graded rows (agent-visible / done-signal);
    C is the human gold set, loaded here but consumed only by scoring --
    never by feedback or any stop/select decision.

    Args:
        seed: Shuffle seed; recorded in the run metadata via the id hashes.
        b_fraction: Fraction of the 300 held out as B (~90 rows at 0.3,
            mirroring rung 1's 210/90 proportions).

    Returns:
        The split with reproducibility hashes.
    """
    train = load_train().sample(frac=1.0, random_state=seed).reset_index(drop=True)
    n_b = int(round(len(train) * b_fraction))
    b, a = train.iloc[:n_b], train.iloc[n_b:]
    c = pd.read_csv(GOLD_PATH).rename(columns={"domain": "operational_domain"})
    return Split(
        a=a.reset_index(drop=True),
        b=b.reset_index(drop=True),
        c=c,
        hashes={
            "A": _hash_ids(a["id"]),
            "B": _hash_ids(b["id"]),
            "C": _hash_ids(c["id"]),
        },
    )


def score_frame(merged: pd.DataFrame) -> dict:
    """Two-axis scores for a frame carrying truth + ``pred_*`` columns.

    ``macro_f1`` is the PRIMARY metric -- the mean of the two axes' macro-F1.
    It carries that name (not ``mean_macro_f1``) deliberately, so rung 1's
    ``select_best_iteration``, which reads ``scores["B"]["macro_f1"]``, works
    on rung-2 records unchanged.

    Args:
        merged: Frame with truth columns and ``pred_*`` predictions.

    Returns:
        Dict with ``accuracy``/``macro_f1`` per axis and the primary metric.
    """
    out: dict = {}
    per_axis_f1 = []
    for axis in AXES:
        metrics = compute_metrics(merged, axis)
        macro = macro_average(metrics)
        correct = int((merged[axis] == merged[f"pred_{axis}"]).sum())
        out[axis] = {
            "accuracy": round(correct / len(merged), 4),
            "macro_f1": macro["f1"],
        }
        per_axis_f1.append(macro["f1"])
    out["macro_f1"] = round(sum(per_axis_f1) / len(per_axis_f1), 4)
    return out


def oof_predictions(
    experiment: dict, a: pd.DataFrame, seed: int = DEFAULT_SEED, folds: int = 5
) -> pd.DataFrame:
    """Out-of-fold predictions on A: the honest error signal for feedback.

    A model predicting its own training rows memorizes them and yields a
    near-empty failure list; each row here is predicted by a model that never
    saw it. This is what the agent reads -- still strictly inside A.

    Args:
        experiment: Validated experiment to evaluate.
        a: Split A.
        seed: Fold shuffle seed.
        folds: Number of CV folds.

    Returns:
        Copy of A with ``pred_*`` columns from the fold-held-out models.
    """
    preds = pd.DataFrame(index=a.index, columns=[f"pred_{axis}" for axis in AXES])
    for train_idx, val_idx in KFold(folds, shuffle=True, random_state=seed).split(a):
        fitted = fit_experiment(experiment, a.iloc[train_idx], seed=seed)
        fold_preds = fitted.predict(a.iloc[val_idx]["text"])
        preds.iloc[val_idx] = fold_preds.values
    merged = a.copy()
    for axis in AXES:
        merged[f"pred_{axis}"] = preds[f"pred_{axis}"].values
    return merged


# ---------------------------------------------------------------------------
# Feedback -- built from A only.
# ---------------------------------------------------------------------------


def _confusion_stats(merged: pd.DataFrame) -> dict:
    """Off-diagonal confusion counts per axis, e.g. ``{"category": {"policy->operations": 4}}``."""
    stats: dict = {}
    for axis in AXES:
        wrong = merged[merged[axis] != merged[f"pred_{axis}"]]
        pairs = (wrong[axis] + "->" + wrong[f"pred_{axis}"]).value_counts()
        stats[axis] = {pair: int(count) for pair, count in pairs.items()}
    return stats


def build_feedback(
    oof_merged: pd.DataFrame,
    max_examples: int = MAX_FEEDBACK_EXAMPLES,
    seed: int = DEFAULT_SEED,
) -> tuple[str, list, dict]:
    """Assemble the proposer's feedback from A's out-of-fold results only.

    Args:
        oof_merged: Output of ``oof_predictions``.
        max_examples: Cap on raw misclassified examples included.
        seed: Sampling seed for which failures are shown.

    Returns:
        ``(feedback_text, failure_ids_shown, confusion_stats)``.
    """
    stats = _confusion_stats(oof_merged)
    wrong = oof_merged[
        (oof_merged["category"] != oof_merged["pred_category"])
        | (oof_merged["operational_domain"] != oof_merged["pred_operational_domain"])
    ]
    sample = wrong.sample(n=min(max_examples, len(wrong)), random_state=seed)
    lines = ["Confusion (true->predicted: count), out-of-fold on the optimize set:"]
    for axis in AXES:
        pairs = ", ".join(
            f"{p}: {c}" for p, c in sorted(stats[axis].items(), key=lambda kv: -kv[1])
        )
        lines.append(f"  {axis}: {pairs or '(none)'}")
    lines.append("")
    lines.append(f"Misclassified examples ({len(sample)} of {len(wrong)}):")
    for _, row in sample.iterrows():
        snippet = row["text"][:FEEDBACK_SNIPPET_CHARS]
        lines.append(
            f"- [{row['id']}] true=({row['category']}, {row['operational_domain']}) "
            f"pred=({row['pred_category']}, {row['pred_operational_domain']}): {snippet}"
        )
    return "\n".join(lines), sample["id"].tolist(), stats


# ---------------------------------------------------------------------------
# The proposer -- the only part that spends tokens.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExperimentProposal:
    """What a backend's ``propose()`` returns."""

    experiment: dict
    rationale: str
    edit_summary: str
    tokens: int


class MLLoopBackend(Protocol):
    """The seam between the loop and anything that costs money."""

    def propose(self, current_experiment: dict, feedback: str) -> ExperimentProposal:
        """Return the next experiment to try, given A-only feedback."""
        ...


PROPOSER_SYSTEM_PROMPT = """You are the data scientist in an autonomous ML loop \
for a defense-news classifier. A TF-IDF + logistic-regression baseline is trained \
on judge-labeled snippets; your job each iteration is to read the errors and \
propose the SINGLE next experiment most likely to improve held-out macro-F1 on \
BOTH axes (category: procurement/operations/policy/technology/industry; \
operational_domain: air/land/sea/cyber/space/multi).

You control exactly three things, expressed as one JSON experiment object:
1. "vectorizer": analyzer ("word" or "char_wb"), ngram_min/ngram_max (word: 1-3, \
char_wb: 1-6), min_df (1-10), max_features (null or 1000-200000), sublinear_tf \
(bool), stop_words ("english" or "none").
2. "model": C (0.01-100), class_weight ("balanced" or "none").
3. "keyword_features": up to 20 groups of {"name": identifier, "patterns": \
["substring", ...]} -- each group becomes one binary feature: 1 if any pattern \
appears (case-insensitive) in the snippet. THIS is your error-driven feature \
engineering: read the misclassified examples, find the signal the n-grams are \
missing (unit names, platform types, doctrinal phrases), and encode it.

Ground rules:
- Propose ONE coherent change per iteration and say why the errors motivate it. \
A shotgun of unrelated changes makes the run log unreadable and the result \
unattributable.
- You only ever see the optimize-set errors. The validation and test sets are \
hidden from you by design; do not ask for them.
- The training labels have almost no "industry" rows -- you cannot fix that \
class with features; do not burn iterations on it.
- Keep every value inside the stated bounds; out-of-bounds experiments are \
rejected before scoring and cost you a retry."""

PROPOSE_TOOL: ToolParam = {
    "name": "propose_experiment",
    "description": "Propose the next ML experiment for the loop to fit and score.",
    "input_schema": {
        "type": "object",
        "properties": {
            "experiment": {
                "type": "object",
                "description": "The complete next experiment configuration.",
            },
            "rationale": {
                "type": "string",
                "description": "Why the observed errors motivate this experiment.",
            },
            "edit_summary": {
                "type": "string",
                "description": "One line: what changed vs the current experiment.",
            },
        },
        "required": ["experiment", "rationale", "edit_summary"],
    },
}


class AnthropicMLBackend:
    """Live proposer. Every call spends real tokens; never constructed by tests."""

    def __init__(self, client: anthropic.Anthropic, model: str = MODEL) -> None:
        """Build the live backend.

        Args:
            client: Authenticated Anthropic client.
            model: Proposer model id (SYS-002 default: the Sonnet workhorse).
        """
        self.client = client
        self.model = model

    def propose(
        self, current_experiment: dict, feedback: str, max_retries: int = 3
    ) -> ExperimentProposal:
        """Ask the proposer for the next experiment; validate before returning.

        Mirrors rung 1's propose(): a forced tool call, retried on incomplete
        payloads AND on experiments that fail ``validate_experiment`` (the
        violations are echoed back into the retry message so the model can
        correct itself). Exhausting retries raises ``ProposalError`` -- the
        run stops rather than scoring a malformed experiment.

        Args:
            current_experiment: The experiment being revised.
            feedback: A-only feedback from ``build_feedback``.
            max_retries: Attempts before raising.

        Returns:
            A validated ``ExperimentProposal`` with exact token usage summed
            across every attempt (failed retries spend real tokens too).

        Raises:
            ProposalError: If every attempt fails validation or parsing.
        """
        tokens = 0
        complaint = ""
        last_error = "no attempt made"
        for _ in range(max_retries):
            message = (
                f"Current experiment:\n{json.dumps(current_experiment, indent=2)}\n\n"
                f"{feedback}\n{complaint}\nPropose the next experiment."
            )
            # The outer loop retries VALIDATION failures; transport failures
            # (429/529/connection drops) back off here per ADR-021 instead of
            # aborting an unattended multi-iteration run.
            response = api_retry.call_with_retry(
                lambda: self.client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    system=PROPOSER_SYSTEM_PROMPT,
                    tools=[PROPOSE_TOOL],
                    tool_choice={"type": "tool", "name": "propose_experiment"},
                    messages=[{"role": "user", "content": message}],
                )
            )
            tokens += int(response.usage.input_tokens) + int(
                response.usage.output_tokens
            )
            try:
                tool_block = next(
                    b for b in response.content if isinstance(b, ToolUseBlock)
                )
                payload = cast(dict, tool_block.input)
                experiment = payload["experiment"]
                violations = validate_experiment(experiment)
                if violations:
                    last_error = "; ".join(violations)
                    complaint = (
                        f"\nYour previous proposal was rejected: {last_error}. "
                        "Fix these and stay inside the bounds.\n"
                    )
                    continue
                return ExperimentProposal(
                    experiment=experiment,
                    rationale=payload["rationale"],
                    edit_summary=payload["edit_summary"],
                    tokens=tokens,
                )
            except (StopIteration, KeyError) as exc:
                last_error = repr(exc)
        raise ProposalError(
            f"no valid experiment after {max_retries} attempts; last: {last_error}",
            tokens=tokens,
        )


class DryRunBackend:
    """Deterministic offline proposer: a canned tour of the experiment space.

    Exists for the same reasons as rung 1's: free end-to-end runs in tests and
    demos, exercising the full loop (validation, fitting, logging, done-signal)
    with zero API calls. The canned sequence deliberately includes sensible
    moves so a dry run's log tells a plausible story for the replay viewer.
    """

    _MOVES: list[tuple[str, dict]] = [
        (
            "widen n-grams and soften tf scaling",
            {"vectorizer": {"ngram_max": 3, "sublinear_tf": True}},
        ),
        (
            "add error-driven platform keyword features",
            {
                "keyword_features": [
                    {
                        "name": "naval_platforms",
                        "patterns": ["carrier", "destroyer", "frigate", "fleet"],
                    },
                    {
                        "name": "air_platforms",
                        "patterns": ["squadron", "aircraft", "fighter", "bomber"],
                    },
                    {
                        "name": "ground_units",
                        "patterns": ["brigade", "battalion", "infantry", "soldiers"],
                    },
                ]
            },
        ),
        ("relax regularization", {"model": {"C": 4.0}}),
        ("drop stop-word filtering", {"vectorizer": {"stop_words": "none"}}),
    ]

    def __init__(self) -> None:
        """Start the canned sequence."""
        self._step = 0

    def propose(self, current_experiment: dict, feedback: str) -> ExperimentProposal:
        """Apply the next canned move on top of the current experiment.

        Args:
            current_experiment: The experiment to modify.
            feedback: Ignored (canned moves don't read errors); accepted so
                the dry-run path exercises the real feedback-building code.

        Returns:
            A validated proposal with ``tokens=0``.
        """
        summary, patch = self._MOVES[self._step % len(self._MOVES)]
        self._step += 1
        experiment = json.loads(json.dumps(current_experiment))
        for section, values in patch.items():
            if section == "keyword_features":
                experiment["keyword_features"] = values
            else:
                experiment[section].update(values)
        assert not validate_experiment(experiment), "canned move must be valid"
        return ExperimentProposal(
            experiment=experiment,
            rationale=f"[dry-run] {summary}",
            edit_summary=f"[dry-run] {summary}",
            tokens=0,
        )


# ---------------------------------------------------------------------------
# The run.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopConfig:
    """Tunable knobs for one loop run -- all CLI-configurable."""

    model: str = MODEL
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    token_budget: int = DEFAULT_TOKEN_BUDGET
    target_f1: float = DEFAULT_TARGET_F1
    plateau_n: int = DEFAULT_PLATEAU_N
    max_feedback_examples: int = MAX_FEEDBACK_EXAMPLES
    seed: int = DEFAULT_SEED


def score_experiment(
    experiment: dict, split: Split, seed: int
) -> tuple[dict, pd.DataFrame]:
    """Fit and score one experiment across all three splits.

    A's score comes from out-of-fold predictions (the generalization view the
    agent's feedback is built from); B and C are scored by a model fitted on
    ALL of A. C's number lands in the log as a report, and nothing reads it.

    Args:
        experiment: Validated experiment.
        split: The A/B/C split.
        seed: Reproducibility seed.

    Returns:
        ``(scores, oof_merged)`` -- the per-split scores dict and A's
        out-of-fold frame for feedback building.
    """
    oof = oof_predictions(experiment, split.a, seed=seed)
    fitted = fit_experiment(experiment, split.a, seed=seed)
    scores = {"A": score_frame(oof)}
    for name, frame in (("B", split.b), ("C", split.c)):
        merged = frame.copy()
        preds = fitted.predict(frame["text"])
        for axis in AXES:
            merged[f"pred_{axis}"] = preds[f"pred_{axis}"].values
        scores[name] = score_frame(merged)
    return scores, oof


def run_loop(
    backend: MLLoopBackend,
    config: LoopConfig,
    log_path: str | None = None,
) -> str:
    """Run the rung-2 loop to its done-signal; returns the run-log path.

    Args:
        backend: Proposer backend (live or dry-run).
        config: Run configuration.
        log_path: Run-log path override (tests); default is a fresh
            timestamped file under ``evals/ml_loop/``.

    Returns:
        Path of the JSONL run log written.
    """
    split = make_split(seed=config.seed)
    path = log_path or new_run_log_path(RUN_LOG_DIR)
    append_run_log(
        path,
        {
            "record": "run_metadata",
            "rung": 2,
            "model": config.model,
            "budget": config.token_budget,
            "iteration_cap": config.max_iterations,
            "target_f1": config.target_f1,
            "plateau_n": config.plateau_n,
            "split_hashes": split.hashes,
            "start_experiment": DEFAULT_EXPERIMENT,
            "seed": config.seed,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dry_run": isinstance(backend, DryRunBackend),
        },
    )

    experiment = DEFAULT_EXPERIMENT
    tokens_spent = 0
    b_history: list[float] = []
    records: list[dict] = []
    iteration = 0
    rationale, edit_summary, diff = "(baseline)", "(baseline)", "(baseline)"
    failures_shown: list = []

    while True:
        scores, oof = score_experiment(experiment, split, config.seed)
        feedback, failure_ids, confusion = build_feedback(
            oof, config.max_feedback_examples, seed=config.seed + iteration
        )
        b_history.append(scores["B"]["macro_f1"])
        record = {
            "record": "iteration",
            "iteration": iteration,
            "experiment": experiment,
            "experiment_diff": diff,
            "scores": scores,
            "failures_read": failures_shown,
            "confusion_stats": confusion,
            "agent_rationale": rationale,
            "edit_summary": edit_summary,
            "tokens_spent": tokens_spent,
            "done_signal": None,
        }
        records.append(record)
        print(
            f"iter {iteration}: A {scores['A']['macro_f1']:.3f}  "
            f"B {scores['B']['macro_f1']:.3f}  C {scores['C']['macro_f1']:.3f}  "
            f"({diff})",
            flush=True,
        )

        done = check_done_signal(
            b_history,
            config.target_f1,
            iteration,
            config.max_iterations,
            tokens_spent,
            config.token_budget,
            config.plateau_n,
        )
        record["done_signal"] = done
        append_run_log(path, record)
        if done:
            break

        try:
            proposal = backend.propose(experiment, feedback)
        except ProposalError as exc:
            tokens_spent += exc.tokens
            append_run_log(
                path,
                {
                    "record": "run_error",
                    "iteration": iteration,
                    "error": str(exc),
                    "tokens_spent": tokens_spent,
                },
            )
            done = "proposal_error"
            break
        tokens_spent += proposal.tokens
        diff = experiment_diff(experiment, proposal.experiment)
        experiment = proposal.experiment
        rationale, edit_summary = proposal.rationale, proposal.edit_summary
        failures_shown = failure_ids
        iteration += 1

    best = select_best_iteration(records)
    baseline, best_record = records[0], records[best]
    append_run_log(
        path,
        {
            "record": "run_summary",
            "done_signal": done,
            "iterations": len(records),
            "tokens_spent": tokens_spent,
            "best_iteration": best,
            "baseline_scores": baseline["scores"],
            "best_scores": best_record["scores"],
            "best_experiment": best_record["experiment"],
        },
    )
    print(
        f"done ({done}) after {len(records)} iterations; best = iter {best}: "
        f"B {best_record['scores']['B']['macro_f1']:.3f} "
        f"(baseline {baseline['scores']['B']['macro_f1']:.3f}), "
        f"C {best_record['scores']['C']['macro_f1']:.3f} "
        f"(baseline {baseline['scores']['C']['macro_f1']:.3f})",
        flush=True,
    )
    return path


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="offline canned proposer"
    )
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    parser.add_argument("--target-f1", type=float, default=DEFAULT_TARGET_F1)
    parser.add_argument("--plateau-n", type=int, default=DEFAULT_PLATEAU_N)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    config = LoopConfig(
        max_iterations=args.max_iterations,
        token_budget=args.token_budget,
        target_f1=args.target_f1,
        plateau_n=args.plateau_n,
        seed=args.seed,
    )
    backend: MLLoopBackend
    if args.dry_run:
        backend = DryRunBackend()
    else:
        from classify import make_client

        backend = AnthropicMLBackend(make_client())
    path = run_loop(backend, config)
    print(f"run log: {path}")


if __name__ == "__main__":
    main()
