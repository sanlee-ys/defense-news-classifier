"""Classical ML baseline bake-off: TF-IDF + logistic regression vs the LLM.

The repo's thesis is measure-before-you-spend, and every prior measurement (BM25
grounding, tiered routing) priced a spend *on top of* an LLM. This module baselines
the LLM itself: what does the standard zero-dollar classical stack score on the same
human gold set? Publishable in either direction -- see
``docs/specs/ml-baseline-bakeoff.md``.

Design constraints (from the spec, non-negotiable):

- Train on the judge-graded scaled set (``data/scale/scale_set.csv`` joined with
  ``evals/scale_predictions.csv``), labels from ``judge_*`` ONLY -- training on
  ``pred_*`` would distill the very model the baseline is an alternative to.
- The 54 human gold rows are touched exactly once, at the end, for scoring. All
  fitting and any cross-validation happen strictly inside the 300-row train split;
  ``fit_baseline`` never sees a gold path.
- Deliberately boring configuration: word 1-2 grams, English stop words, min_df=2,
  one LogisticRegression per axis. A hand-tuned baseline invites "you rigged it"
  in both directions.
- Metrics are the repo's hand-rolled ``eval.py`` functions, not sklearn's report
  (ADR-004: sklearn may model, it may not measure).

Covers category and operational_domain only: the scaled set has no region labels
(the scaled region eval is unscheduled). Train labels are judge-generated,
so the baseline inherits the judge's ~5-6% disagreement-with-human ceiling and is
then tested against human labels -- the direction that handicaps the baseline, not
flatters it.

Run (offline, no API key):
    uv run python src/baseline_ml.py

Reads ``data/scale/scale_set.csv``, ``evals/scale_predictions.csv``,
``data/gold/gold.csv``, and the LLM's stored ``evals/gold_predictions_v3.csv``
(for the paired McNemar test). Writes ``evals/baseline_predictions.csv``,
``evals/baseline_eval.txt``, and the fitted artifacts to
``evals/baseline_model.joblib`` (gitignored -- reproducible from committed data).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold

from eval import compute_metrics, confusion_matrix, macro_average, wilson_interval

TRAIN_TEXT_PATH = "data/scale/scale_set.csv"
TRAIN_LABEL_PATH = "evals/scale_predictions.csv"
GOLD_PATH = "data/gold/gold.csv"
LLM_PREDS_PATH = "evals/gold_predictions_v3.csv"

PREDICTIONS_PATH = "evals/baseline_predictions.csv"
REPORT_PATH = "evals/baseline_eval.txt"
MODEL_PATH = "evals/baseline_model.joblib"

AXES = ["category", "operational_domain"]

RANDOM_STATE = 42
CV_FOLDS = 5


def load_train(
    text_path: str = TRAIN_TEXT_PATH, label_path: str = TRAIN_LABEL_PATH
) -> pd.DataFrame:
    """Join scaled-set text with the judge's labels; drop the workhorse's.

    The label file carries both ``pred_*`` (the workhorse LLM's own output) and
    ``judge_*`` (the validated Opus judge). Training on ``pred_*`` would make the
    baseline a distillation of the model it is meant to be an alternative to, so
    the ``pred_*`` columns are dropped at load time -- nothing downstream can
    reach them.

    Args:
        text_path: CSV with ``id`` and ``text`` columns (no labels by design).
        label_path: CSV with ``id`` and ``judge_*``/``pred_*`` label columns.

    Returns:
        DataFrame with ``id``, ``text``, ``category``, ``operational_domain``,
        where the label columns are the judge's, renamed to the axis names.
    """
    text = pd.read_csv(text_path)[["id", "text"]]
    labels = pd.read_csv(label_path)[
        ["id", "judge_category", "judge_operational_domain"]
    ].rename(
        columns={
            "judge_category": "category",
            "judge_operational_domain": "operational_domain",
        }
    )
    return text.merge(labels, on="id", validate="one_to_one")


@dataclass
class Baseline:
    """A fitted TF-IDF vectorizer plus one logistic regression per axis."""

    vectorizer: TfidfVectorizer
    models: dict[str, LogisticRegression]

    def predict(self, texts: pd.Series) -> pd.DataFrame:
        """Predict both axes for a series of texts.

        Args:
            texts: Article snippets to classify.

        Returns:
            DataFrame with ``pred_category`` and ``pred_operational_domain``
            columns (named to match the rest of the eval harness).
        """
        features = self.vectorizer.transform(texts)
        return pd.DataFrame(
            {f"pred_{axis}": self.models[axis].predict(features) for axis in AXES},
            index=texts.index,
        )


def fit_baseline(
    train: pd.DataFrame, class_weight: str | None = "balanced"
) -> Baseline:
    """Fit the vectorizer and both per-axis classifiers on the train split only.

    Takes the already-loaded train DataFrame rather than a path, so the fitting
    code has no way to read the gold file -- the no-leakage guarantee is
    structural, and the test suite pins it.

    Args:
        train: Output of ``load_train`` (or any frame with ``text`` + axis columns).
        class_weight: Passed to LogisticRegression; ``"balanced"`` attacks the
            operations skew (66% of train) at the risk of distorting the majority
            class -- the report measures both settings via CV.

    Returns:
        The fitted ``Baseline``.
    """
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2), stop_words="english", min_df=2, lowercase=True
    )
    features = vectorizer.fit_transform(train["text"])
    models = {}
    for axis in AXES:
        model = LogisticRegression(
            class_weight=class_weight, max_iter=1000, random_state=RANDOM_STATE
        )
        model.fit(features, train[axis])
        models[axis] = model
    return Baseline(vectorizer=vectorizer, models=models)


def cross_validate(train: pd.DataFrame, class_weight: str | None) -> dict[str, float]:
    """5-fold CV accuracy per axis, entirely within the 300-row train split.

    This measures agreement with the *judge* labels (n=300, tighter interval),
    which is a different question from agreement with the human gold set -- the
    report labels the two clearly. Plain (unstratified) KFold because
    ``industry`` has a single training row and cannot be stratified.

    Args:
        train: Output of ``load_train``.
        class_weight: LogisticRegression class_weight to evaluate.

    Returns:
        Mean CV accuracy per axis, keyed by axis name.
    """
    folds = KFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    correct = {axis: 0 for axis in AXES}
    for train_idx, val_idx in folds.split(train):
        fold_fit = fit_baseline(train.iloc[train_idx], class_weight=class_weight)
        preds = fold_fit.predict(train.iloc[val_idx]["text"])
        for axis in AXES:
            correct[axis] += int(
                (preds[f"pred_{axis}"].values == train.iloc[val_idx][axis].values).sum()
            )
    return {axis: correct[axis] / len(train) for axis in AXES}


def mcnemar_exact(both_wrong_a_only: int, both_wrong_b_only: int) -> float:
    """Two-sided exact McNemar p-value on the discordant pair counts.

    Hand-rolled binomial test (ADR-004: no framework for metric computation).
    Under H0 the discordant rows split 50/50 between the two systems.

    Args:
        both_wrong_a_only: Rows system A got wrong and system B got right.
        both_wrong_b_only: Rows system B got wrong and system A got right.

    Returns:
        Two-sided p-value; 1.0 when there are no discordant rows.
    """
    n = both_wrong_a_only + both_wrong_b_only
    if n == 0:
        return 1.0
    k = min(both_wrong_a_only, both_wrong_b_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def main() -> None:
    """Train, score once against gold, and write the full bake-off report."""
    train = load_train()

    # -- Open question 2 (spec §9): class_weight, measured within train only.
    cv_balanced = cross_validate(train, "balanced")
    cv_none = cross_validate(train, None)

    baseline = fit_baseline(train, class_weight="balanced")
    joblib.dump(baseline, MODEL_PATH)

    # -- The single touch of the gold set: predict, time it, score.
    gold = pd.read_csv(GOLD_PATH).rename(columns={"domain": "operational_domain"})
    start = time.perf_counter()
    preds = baseline.predict(gold["text"])
    elapsed_ms = (time.perf_counter() - start) * 1000
    merged = pd.concat([gold, preds], axis=1)
    merged[["id", "pred_category", "pred_operational_domain"]].to_csv(
        PREDICTIONS_PATH, index=False
    )

    llm = pd.read_csv(LLM_PREDS_PATH)[
        ["id", "pred_category", "pred_operational_domain"]
    ].rename(columns={f"pred_{axis}": f"llm_{axis}" for axis in AXES})
    paired = merged.merge(llm, on="id", validate="one_to_one")

    lines: list[str] = []
    out = lines.append
    out("=" * 62)
    out("CLASSICAL ML BASELINE BAKE-OFF -- TF-IDF + logistic regression")
    out("=" * 62)
    out("")
    out("Train : 300 DVIDS snippets, Opus-JUDGE labels (not human; the")
    out("        baseline inherits the judge's ~5-6% human-disagreement ceiling).")
    out("Test  : the 54-row human gold set, touched once. Region is NOT covered")
    out("        (the training data has no region labels until the scaled")
    out("        region eval ships).")
    out("Config: word 1-2 grams, english stop words, min_df=2,")
    out("        LogisticRegression(class_weight='balanced') per axis.")
    out("Caveat: 'industry' has n=1 training row -- structurally unlearnable.")
    out("")

    for axis in AXES:
        correct = int((paired[axis] == paired[f"pred_{axis}"]).sum())
        n = len(paired)
        lo, hi = wilson_interval(correct, n)
        # The LLM row comes from the same stored v3 predictions the McNemar
        # pairs against, so both sides of the comparison share one run.
        llm_correct = int((paired[axis] == paired[f"llm_{axis}"]).sum())
        llm_lo, llm_hi = wilson_interval(llm_correct, n)
        out(f"-- {axis}: accuracy vs human gold (n={n}), 95% Wilson CI --------")
        out(f"  baseline : {correct / n:6.1%}  [{lo:.1%}, {hi:.1%}]  ({correct}/{n})")
        out(
            f"  LLM      : {llm_correct / n:6.1%}  [{llm_lo:.1%}, {llm_hi:.1%}]"
            f"  ({llm_correct}/{n})"
        )
        base_only = int(
            (
                (paired[axis] != paired[f"pred_{axis}"])
                & (paired[axis] == paired[f"llm_{axis}"])
            ).sum()
        )
        llm_only = int(
            (
                (paired[axis] == paired[f"pred_{axis}"])
                & (paired[axis] != paired[f"llm_{axis}"])
            ).sum()
        )
        p = mcnemar_exact(base_only, llm_only)
        out(
            f"  McNemar (paired, exact): baseline-only-wrong={base_only},"
            f" LLM-only-wrong={llm_only}, p={p:.4f}"
        )
        out("")
        metrics = compute_metrics(paired, axis)
        macro = macro_average(metrics)
        out(f"  Per-label (baseline vs human), macro-F1 {macro['f1']:.3f}:")
        out("  " + metrics.to_string().replace("\n", "\n  "))
        out("")
        out("  Confusion (true rows x predicted cols):")
        out("  " + confusion_matrix(paired, axis).to_string().replace("\n", "\n  "))
        out("")

    out("-- Second number (spec §9): 5-fold CV within the 300 train rows -----")
    out("   Measures agreement with the JUDGE labels, not with humans; larger n,")
    out("   different question. Also the class_weight experiment (spec §9):")
    for axis in AXES:
        out(
            f"  {axis:20s} balanced: {cv_balanced[axis]:6.1%}"
            f"   unweighted: {cv_none[axis]:6.1%}"
        )
    out("")
    out("-- Cost / latency (half the comparison) ----------------------------")
    out(
        f"  baseline : $0.00 per article, {elapsed_ms:.1f} ms wall-clock for all"
        f" 54 rows ({elapsed_ms / len(paired):.2f} ms/article, local CPU)"
    )
    out("  LLM      : 1.00x workhorse-call units (the route_eval cost unit);")
    out("             per-call API latency is network-bound (order of seconds)")
    out("             and has not been separately measured in this repo.")
    out("=" * 62)

    report = "\n".join(lines) + "\n"
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report)


if __name__ == "__main__":
    main()
