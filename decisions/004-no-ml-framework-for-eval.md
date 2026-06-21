# ADR-004: Implement eval metrics in plain Python — no ML framework

**Status:** Accepted  
**Date:** 2026-06-19  
**Deciders:** San Lee

---

## Context

Computing precision, recall, F1, and confusion matrices is standard functionality available in `scikit-learn`. The alternative is to implement these directly using pandas and arithmetic.

## Decision

Implement all eval metrics in plain Python with pandas. No `scikit-learn`, no `torchmetrics`, no other ML framework.

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
