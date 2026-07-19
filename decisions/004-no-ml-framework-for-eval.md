# ADR-004: Implement eval metrics in plain Python — no ML framework

**Status:** Accepted; **amended 2026-07-19** (see [Amendment](#amendment-2026-07-19))  
**Date:** 2026-06-19  
**Deciders:** San Lee

---

## Context

Computing precision, recall, F1, and confusion matrices is standard functionality available in `scikit-learn`. The alternative is to implement these directly using pandas and arithmetic.

## Decision

Implement all eval **metric computation** in plain Python with pandas. No `scikit-learn`, no `torchmetrics`, no other ML framework *for computing metrics*.

Introducing an ML library as a **subject of measurement** — a baseline model the eval scores — in a dev/eval dependency group is outside this ADR's scope and is governed by its own record. See the [Amendment](#amendment-2026-07-19).

```python
tp = int(((df[true_col] == label) & (df[pred_col] == label)).sum())
fp = int(((df[true_col] != label) & (df[pred_col] == label)).sum())
fn = int(((df[true_col] == label) & (df[pred_col] != label)).sum())
precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
```

## Consequences

- **Minimal dependency surface.** The project's runtime dependencies are `anthropic` and `pandas` — nothing else. Simpler `pyproject.toml`, faster `uv sync`, easier to audit.
- **The metrics logic is readable and directly testable.** `test_eval.py` tests the TP/FP/FN counting and F1 formula directly. With `sklearn`, the implementation would be opaque.
- **Good fit for the scale.** 300 articles, two fields, six labels each. `scikit-learn` is appropriate for datasets and label sets where the combinatorics become unwieldy.
- **Slight redundancy.** The confusion matrix and per-label metrics are ~40 lines of code that `sklearn.metrics.classification_report` and `confusion_matrix` would replace. Accepted tradeoff for portfolio clarity and minimal deps.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| `scikit-learn` | Heavier dependency for a simple two-field eval; hides the metric logic from the reader |
| `torchmetrics` | Designed for training loops; entirely unnecessary here |

---

## Amendment (2026-07-19)

Written in the repo's third week, when there was no model in the project to fit. The Decision line banned ML frameworks outright while **every stated reason underneath it was about computing metrics**. That gap went live when the [ML baseline bake-off spec](../docs/specs/ml-baseline-bakeoff.md) needed `scikit-learn` for a TF-IDF + logistic-regression baseline — a model the eval *measures*, not a metric library.

The Decision above is now scoped to what its rationale actually supports. Of the two load-bearing reasons, one expires and one does not:

- **"Minimal dependency surface — runtime deps are `anthropic` and `pandas`, nothing else" is superseded.** That census is dead: runtime deps are now `anthropic`, `pandas`, `rank-bm25`, `httpx`, `opentelemetry-api`, `opentelemetry-sdk`. The lean-deps instinct survives as *avoid heavy frameworks*, not as a two-dep line that no longer exists. (`rank-bm25` is a deliberate cost, not drift — the grounding path is kept dormant as the record of [ADR-012](012-retire-bm25-grounding.md)'s negative result.)
- **"The metrics logic is readable and directly testable" stands on its own, and is why this ADR survives.** This repo is a relearning vehicle; hand-rolled TP/FP/FN counting and confusion matrices are portfolio signal, not overhead, and `test_eval.py` tests the formulas directly. The "~40 lines, no sprawl" prediction held — `src/eval.py` became a small internal metrics API rather than duplicated arithmetic, and eight modules import it.

**So: a model may use a framework; metrics stay plain Python.**

Explicitly, so a future session does not read the amendment as a general relaxation: **do not replace the hand-written metrics with `sklearn.metrics.classification_report` or `confusion_matrix`.** Trading them for a ~40-line saving deletes the thing this ADR was protecting.

**Downstream surfaces.** [ADR-005](005-agentic-prompt-optimization-loop.md)'s Alternatives table rejected DSPy partly on "the repo's minimal-deps rule (ADR-004)". That ground is narrowed by this amendment, so ADR-005's entry is re-grounded on its own stronger argument in the same change. `CLAUDE.md`'s "avoid heavy frameworks" line is unchanged and still governs.
