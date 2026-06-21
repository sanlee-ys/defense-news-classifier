# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versions are tagged by milestone; individual commits are noted where relevant.

---

## [Unreleased]

### Added
- `LICENSE` — MIT license
- README status badges (CI, release, license, Python version)
- `docs/how-it-works.md` — plain-language one-pager on the three-stage pipeline and why the classifier/evaluator separation is the point, with a "Threats to validity" section
- **Macro-averaged precision/recall/F1** in the eval report (`macro_average` in `src/eval.py`) — every label weighted equally, so a collapsed minority class is no longer hidden by raw accuracy. Category macro-F1 is **0.765** (below its 79.0% accuracy); domain is **0.973**. Two new unit tests cover it.
- **Multi-run stability harness** (`src/stability.py`) — runs the full eval N times and reports mean / std / min / max per headline metric, so a config difference can be checked against the run-to-run noise floor (clears ~2x std?) instead of trusting a single run. Optional `--temperature` flag; per-run predictions saved to `evals/runs/`, summary to `evals/stability.txt`. `classify()` and `classify_with_retry()` gained an optional `temperature` parameter. Six new unit tests cover the pure aggregation/reporting functions.
- `.env.example` — committed template documenting the `ANTHROPIC_API_KEY` the project needs; copy to `.env` (gitignored) and load with `uv run --env-file .env`. README gained an "API key & secrets" subsection covering the pattern, the rationale, and the machine-local caveat (`.env` is recreated on a fresh clone — the deliberate trade-off of keeping secrets out of git).

### Changed
- `pyproject.toml` version bumped `0.1.0` → `1.0.0` to match the released tag
- README results table now reports macro-F1 alongside accuracy
- `evals/metrics.txt` regenerated to include the macro-average rows (recomputed from existing predictions — no re-classification)

---

## [1.0.0] — 2026-06-20

First complete version of the defense news classifier. All v1 success criteria met.

### Added
- Synthetic dataset generator (`src/generate.py`) — 300 labeled articles across all 30 category × domain combinations, produced via Anthropic API with structured (tool-use) output
- LLM classifier (`src/classify.py`) — single API call per article returning validated `{category, operational_domain}` JSON
- Eval harness (`src/eval.py`) — accuracy, per-label precision/recall/F1, confusion matrices, misclassification log, and resume-on-interrupt support
- Eval artifacts (`evals/`) — predictions, metrics, confusion matrices, misclassification log
- Unit test suite (`tests/`) covering classifier, generator, and eval metrics with mocked API calls (`dd2d727`)
- `pytest-cov` dev dependency for coverage reporting (`478b6a1`)
- `uv` for dependency management — `pyproject.toml`, `uv.lock`, `.venv` (`8e1db6d`)
- `requirements.txt` kept as a pip fallback
- README leading with eval results (79.0% category accuracy, 97.3% domain accuracy)
- `docs/PRD.md` — product requirements document
- `CLAUDE.md` — project guidance for Claude Code

### Tooling
- Black for code formatting (`uv run black src/ tests/`); configured in `pyproject.toml`
- Ruff for linting (`uv run ruff check src/ tests/`); configured in `pyproject.toml`
- mypy for static type checking (`uv run mypy src/`); configured in `pyproject.toml`
- pre-commit for running the above checks before each commit
- GitHub Actions CI running the test suite on push and pull request
- `.gitattributes` marking notebooks as documentation so the GitHub language bar reflects the Python source rather than embedded notebook output

### Fixed
- `metrics.txt` written with explicit UTF-8 encoding to avoid platform-default encoding errors on Windows (`2cf797c`)

### Investigated
- **Prompt experiment — sharpening the procurement/industry definitions (reverted).**
  Hypothesis: adding an explicit "a firm *winning a specific contract* is procurement; a firm
  *reporting earnings or merging* is industry" distinction to the system prompt would lift
  `industry` recall, the weakest label (0.217). Re-ran the full 300-article eval — the change
  **regressed** the target: category accuracy 79.0% → 76.7%, `industry` recall 0.217 → 0.100.
  The sharper wording made the model even more willing to route borderline company stories into
  `procurement`. Reverted the prompt and kept the 79.0% baseline. Recorded as a negative result —
  the eval, not intuition, decided.

---

## [0.1.0] — 2026-06-19

### Added
- Initial project scaffold: `src/`, `data/`, `evals/` directory structure (`c64c074`)
- Core scripts: `generate.py`, `classify.py`, `eval.py`
- Synthetic dataset (`data/synthetic_articles.csv`)

---

[Unreleased]: https://github.com/sanlee-ys/defense-news-classifier/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/sanlee-ys/defense-news-classifier/releases/tag/v0.1.0
</content>
</invoke>
