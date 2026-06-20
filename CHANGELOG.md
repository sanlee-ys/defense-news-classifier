# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versions are tagged by milestone; individual commits are noted where relevant.

---

## [Unreleased]

### Added
- Black for code formatting (`uv run black src/ tests/`); configured in `pyproject.toml`
- Ruff for linting (`uv run ruff check src/ tests/`); configured in `pyproject.toml`
- mypy for static type checking (`uv run mypy src/`); configured in `pyproject.toml`
- pre-commit for running checks before each commit

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

### Fixed
- `metrics.txt` written with explicit UTF-8 encoding to avoid platform-default encoding errors on Windows (`2cf797c`)

---

## [0.1.0] — 2026-06-19

### Added
- Initial project scaffold: `src/`, `data/`, `evals/` directory structure (`c64c074`)
- Core scripts: `generate.py`, `classify.py`, `eval.py`
- Synthetic dataset (`data/synthetic_articles.csv`)

---

[Unreleased]: https://github.com/sanlee/defense-news-classifier/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/sanlee/defense-news-classifier/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/sanlee/defense-news-classifier/releases/tag/v0.1.0
