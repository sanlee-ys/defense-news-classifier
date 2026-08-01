"""Export the ADR-017 bake-off baseline as portable JSON for browser inference.

The classical baseline (`src/baseline_ml.py`) is a TF-IDF vectorizer plus one
logistic regression per axis — a *linear* model over a sparse bag of n-grams.
That is small enough and simple enough to run anywhere, including in a browser
tab with no server and no runtime dependencies: the whole model is a vocabulary,
an idf vector, and one coefficient matrix per axis.

This script fits **exactly the ADR-017 configuration on exactly the ADR-017
training data** (it calls `baseline_ml.load_train` and `baseline_ml.fit_baseline`
rather than re-declaring the config, so the two can't drift) and writes those
numbers to `web/baseline_export.json`. `web/baseline_infer.js` consumes the file;
`scripts/parity_check.mjs` proves the JS reproduces sklearn's own scores.

Nothing here re-measures anything. The published 72.2% / 66.7% figures stay the
frozen record in `evals/baseline_eval.txt`; this is a portability artifact, not a
new eval.

The stop-word list is exported **from the installed sklearn**, not hardcoded:
`stop_words="english"` removes tokens *before* n-grams are formed, so a JS
reimplementation that guesses the list would build different bigrams and quietly
disagree. Same reasoning for echoing every vectorizer knob into the file — the JS
side reads the config it was fitted with instead of assuming defaults.

Run (offline, no API key):
    uv run python scripts/export_baseline.py
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd  # noqa: E402
import sklearn  # noqa: E402
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS  # noqa: E402

import baseline_ml  # noqa: E402

EXPORT_PATH = REPO_ROOT / "web" / "baseline_export.json"

# The browser demo downloads this file, so the number that matters is the
# *transferred* size: JSON full of decimal numbers is highly compressible and any
# static host serves it gzipped. The budget is therefore checked against the
# gzipped size. `--max-features` exists for the case where even that blows the
# budget -- it is a real accuracy trade (see the PR that added this script), so it
# is opt-in and always recorded in metadata.
SIZE_BUDGET_BYTES = 250_000


def training_frame() -> pd.DataFrame:
    """Load the ADR-017 training split via the harness itself.

    Returns:
        The 300-row judge-labelled train frame (`id`, `text`, one column per axis).
    """
    return baseline_ml.load_train(
        text_path=str(REPO_ROOT / baseline_ml.TRAIN_TEXT_PATH),
        label_path=str(REPO_ROOT / baseline_ml.TRAIN_LABEL_PATH),
    )


def content_hash(train: pd.DataFrame) -> str:
    """Fingerprint the exact training rows behind an export.

    Hashes text plus both labels in `id` order, so the artifact can be tied to
    the data it was fitted on without shipping that data.

    Args:
        train: The training frame.

    Returns:
        Hex sha256 digest.
    """
    ordered = train.sort_values("id")
    digest = hashlib.sha256()
    for row in ordered.itertuples(index=False):
        payload = "\x1f".join(
            [str(row.id), str(row.text)]
            + [str(getattr(row, ax)) for ax in baseline_ml.AXES]
        )
        digest.update(payload.encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()


def _round(value: float) -> float:
    """Trim a float to 10 significant digits to shrink the JSON.

    Full `repr` precision costs ~19 characters per number across ~37k numbers.
    Ten significant digits leaves a relative error near 1e-10 — five orders of
    magnitude below the 1e-6 parity tolerance, so `parity_check.mjs` still holds.

    Args:
        value: The number to trim.

    Returns:
        The trimmed float.
    """
    return float(f"{value:.10g}")


def fit_for_export(
    train: pd.DataFrame, max_features: int | None
) -> baseline_ml.Baseline:
    """Fit the ADR-017 baseline, optionally with a vocabulary cap.

    `scripts/generate_parity_fixture.py` calls this too, so the fixture and the
    export can never come from differently-fitted models.

    Args:
        train: The training frame from `training_frame`.
        max_features: Vocabulary cap, or None for the unrestricted ADR-017 fit.

    Returns:
        The fitted baseline.
    """
    baseline = baseline_ml.fit_baseline(train, class_weight="balanced")
    vec = baseline.vectorizer
    if max_features is not None:
        # Re-fit with the cap. Everything else is read back off the ADR-017
        # vectorizer instance so the capped fit can only differ in this one knob.
        vec = type(vec)(
            ngram_range=vec.ngram_range,
            stop_words=vec.stop_words,
            min_df=vec.min_df,
            lowercase=vec.lowercase,
            max_features=max_features,
        )
        features = vec.fit_transform(train["text"])
        models = {}
        for axis in baseline_ml.AXES:
            model = type(baseline.models[axis])(
                class_weight="balanced",
                max_iter=1000,
                random_state=baseline_ml.RANDOM_STATE,
            )
            model.fit(features, train[axis])
            models[axis] = model
        baseline = baseline_ml.Baseline(vectorizer=vec, models=models)
    return baseline


def build_export(train: pd.DataFrame, max_features: int | None) -> dict[str, Any]:
    """Fit the baseline and flatten it into a JSON-serialisable dict.

    Args:
        train: The training frame from `training_frame`.
        max_features: Vocabulary cap, or None for the unrestricted ADR-017 fit.

    Returns:
        The export payload.
    """
    baseline = fit_for_export(train, max_features)
    vec = baseline.vectorizer
    vocabulary = {term: int(index) for term, index in vec.vocabulary_.items()}
    axes = {
        axis: {
            "classes": [str(c) for c in baseline.models[axis].classes_],
            "coef": [[_round(v) for v in row] for row in baseline.models[axis].coef_],
            "intercept": [_round(v) for v in baseline.models[axis].intercept_],
        }
        for axis in baseline_ml.AXES
    }
    return {
        "schema_version": 1,
        "metadata": {
            "source": "ADR-017 classical ML baseline (src/baseline_ml.py)",
            "generated_by": "uv run python scripts/export_baseline.py",
            "sklearn_version": sklearn.__version__,
            "train_rows": int(len(train)),
            "train_content_sha256": content_hash(train),
            "max_features_cap": max_features,
            "note": (
                "Portability artifact only. The published accuracy figures "
                "(category 72.2%, operational_domain 66.7% vs the 54-row human "
                "gold set) live in evals/baseline_eval.txt and are not restated "
                "or recomputed here."
            ),
        },
        # Echoed rather than assumed: baseline_infer.js reads these instead of
        # hardcoding sklearn's defaults, so a config change surfaces as a parity
        # failure instead of a silent behaviour difference.
        "vectorizer": {
            "analyzer": vec.analyzer,
            "lowercase": vec.lowercase,
            "strip_accents": vec.strip_accents,
            "token_pattern": vec.token_pattern,
            "ngram_range": list(vec.ngram_range),
            "min_df": vec.min_df,
            "max_df": vec.max_df,
            "max_features": vec.max_features,
            "binary": vec.binary,
            "use_idf": vec.use_idf,
            "smooth_idf": vec.smooth_idf,
            "sublinear_tf": vec.sublinear_tf,
            "norm": vec.norm,
            "stop_words": sorted(ENGLISH_STOP_WORDS),
        },
        "vocabulary": vocabulary,
        "idf": [_round(v) for v in vec.idf_],
        "axes": axes,
    }


def main() -> None:
    """Fit, export, and report the artifact's size against the budget."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-features",
        type=int,
        default=None,
        help="Cap the exported vocabulary (recorded in metadata). Default: no cap.",
    )
    args = parser.parse_args()

    train = training_frame()
    payload = build_export(train, args.max_features)
    text = json.dumps(payload, separators=(",", ":"), sort_keys=False) + "\n"

    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(text, encoding="utf-8")

    raw = text.encode("utf-8")
    transferred = len(gzip.compress(raw, 9))
    print(f"wrote {EXPORT_PATH.relative_to(REPO_ROOT)}")
    print(f"  vocabulary : {len(payload['vocabulary'])} terms")
    print(f"  size       : {len(raw):,} bytes raw / {transferred:,} bytes gzipped")
    print(f"  budget     : {SIZE_BUDGET_BYTES:,} bytes transferred")
    for axis, block in payload["axes"].items():
        print(f"  {axis:20s}: {len(block['classes'])} classes")
    if transferred > SIZE_BUDGET_BYTES:
        print(
            "  NOTE: over budget -- re-run with --max-features N to cap the vocabulary."
        )


if __name__ == "__main__":
    main()
