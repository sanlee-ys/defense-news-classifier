"""Freeze sklearn's own answers so the JS port can be held to them.

`web/baseline_infer.js` reimplements scikit-learn's TF-IDF transform by hand.
Hand-ported preprocessing is where browser ports of Python models go wrong, and
they go wrong *quietly*: the demo still returns a plausible label, just not the
one the measured model would have returned. A page that shows a wrong-but-
plausible baseline next to recorded LLM verdicts is worse than no page.

So the port is not trusted, it is gated. This script writes what Python actually
computes -- a set of texts plus, per axis, the predicted label and the full
`decision_function` vector -- and `scripts/parity_check.mjs` re-derives all of it
in Node and fails the build on any disagreement beyond 1e-6.

The fit comes from `export_baseline.fit_for_export`, the same function that
produced the committed JSON, so the fixture and the export cannot describe
different models.

Two text sources, for two different reasons:

- the 54 gold snippets are the realistic demo input, and
- the 300 training snippets are there for **coverage**. A fixture built only from
  gold exercises only the vocabulary those 54 rows happen to contain, and the
  first draft of this gate proved that hole is real: perturbing a coefficient for
  a term absent from all 54 rows left the check green. The training texts are
  what the vocabulary was derived from, so every column of every coefficient
  matrix is reachable.

Both are used as *text*, not as an answer key: no accuracy is computed here and
no label column is read from either file. ADR-017's "touch gold once" discipline
is about scoring, and nothing here scores.

Run (offline, no API key):
    uv run python scripts/generate_parity_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import export_baseline  # noqa: E402
import pandas as pd  # noqa: E402

import baseline_ml  # noqa: E402

GOLD_PATH = REPO_ROOT / "data" / "gold" / "gold.csv"
EXPORT_PATH = export_baseline.EXPORT_PATH
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "baseline_parity.json"


def main() -> None:
    """Fit, predict on the gold + train texts, and write the parity fixture."""
    export = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    # The cap is read back out of the committed artifact rather than passed in:
    # the fixture must describe whatever model the JSON actually holds.
    max_features = export["metadata"]["max_features_cap"]

    train = export_baseline.training_frame()
    baseline = export_baseline.fit_for_export(train, max_features)

    gold = pd.read_csv(GOLD_PATH)
    cases = [("gold", str(i), str(t)) for i, t in zip(gold["id"], gold["text"])]
    cases += [("train", str(i), str(t)) for i, t in zip(train["id"], train["text"])]

    texts = [text for _, _, text in cases]
    features = baseline.vectorizer.transform(pd.Series(texts))

    rows = []
    per_axis_scores = {
        axis: baseline.models[axis].decision_function(features)
        for axis in baseline_ml.AXES
    }
    per_axis_labels = {
        axis: baseline.models[axis].predict(features) for axis in baseline_ml.AXES
    }
    for i, (split, row_id, text) in enumerate(cases):
        rows.append(
            {
                "id": f"{split}:{row_id}",
                "split": split,
                "text": text,
                "expected": {
                    axis: {
                        "label": str(per_axis_labels[axis][i]),
                        "scores": [float(v) for v in per_axis_scores[axis][i]],
                    }
                    for axis in baseline_ml.AXES
                },
            }
        )

    payload = {
        "schema_version": 1,
        "generated_by": "uv run python scripts/generate_parity_fixture.py",
        "export_train_content_sha256": export["metadata"]["train_content_sha256"],
        "sklearn_version": export["metadata"]["sklearn_version"],
        "tolerance": 1e-6,
        "axes": {
            axis: [str(c) for c in baseline.models[axis].classes_]
            for axis in baseline_ml.AXES
        },
        "rows": rows,
    }

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(
        json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {FIXTURE_PATH.relative_to(REPO_ROOT)} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
