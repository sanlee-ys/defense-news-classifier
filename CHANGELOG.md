# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versions are tagged by milestone; individual commits are noted where relevant.

---

## [Unreleased]

### Added
- **`Jenkinsfile`** — the CI pipeline expressed as a declarative Jenkins pipeline (checkout → `uv sync` → parallel ruff/black/mypy → unit tests with the coverage gate), mirroring `.github/workflows/tests.yml`. GitHub Actions stays the live gate; this is pipeline-as-code for a Jenkins controller (none runs it here, so it has no status check).

The `{category, operational_domain}` output contract is unchanged throughout. The
classifier's live surface remains the `/classify` HTTP provider.

## [2.0.1] - 2026-07-05

Dead-code hardening release: removes the Kafka consumer path outright instead of
continuing to carry it as inactive weight. No change to the `{category,
operational_domain}` output contract.

### Removed
- **Kafka consumer (`src/consumer.py`) and its test suite.** The consumer was added as
  an event-driven alternative to the `/classify` HTTP path — reading `NoteCreated`
  events off a `note-events` topic, classifying them in-process, and writing labels back
  onto the note as namespaced tags. It was later reclassified from active integration to
  inactive reference implementation once notes-api's Python/FastAPI port dropped Kafka
  in favor of a `BackgroundTasks` writeback loop: nothing has published `note-events`
  since, so the consumer had become a no-op against the live system. Keeping a dead
  consumer and its Testcontainers-backed integration test (`tests/test_consumer.py`,
  `tests/test_consumer_integration.py`) green in CI cost ongoing maintenance for zero
  live coverage, so both are deleted here; the reference implementation itself remains
  available in git history and the project's ADRs for anyone who wants to see the
  event-driven design. The now-unused `kafka-python` and `testcontainers[kafka]`
  dependencies are dropped from `pyproject.toml` and `requirements.txt` accordingly.
  `README.md`'s project-structure listing, `.env.example`'s now-orphaned
  `KAFKA_BOOTSTRAP_SERVERS`/`NOTE_EVENTS_TOPIC`/`KAFKA_GROUP_ID`/`NOTES_API_BASE_URL`
  block, and `docs/integration-testing.md` (which existed solely to document the
  now-deleted integration test) are updated/removed to match. The CI `integration-test`
  job (the Testcontainers Kafka lane in `.github/workflows/tests.yml`) is dropped along
  with it, since it had no integration test left to run. The classifier's live
  surface remains the unchanged `/classify` HTTP provider.

## [2.0.0] — 2026-06-21

Moved the eval off synthetic, self-graded data and onto **real public-domain text**, with retrieval grounding and a non-circular, human-labeled answer key. v1 measured in-distribution *consistency* (the model classifying snippets it wrote itself); v2 measures real-world *accuracy* against labels a human assigned. The arc between them is the headline.

### Added
- **Real public-domain corpus** (`data/corpus/`, 62 docs) — 56 pulled from the [DVIDS](https://www.dvidshub.net/) DoD news wire (public-domain U.S. government text) spanning procurement / operations / technology / policy across all six domains, plus 6 hand-collected SEC filings for the `industry` class the military wire doesn't carry. Collected by `scripts/fetch_corpus.py` (DVIDS API; the service sites hard-block bots, so the API + hand-collection are the clean-room way in). New dependency: `rank-bm25`.
- **BM25 retriever** (`src/retrieve.py`) — whole-doc lexical retrieval over the corpus, reading both the auto-generated and hand-curated manifests. Chosen as the deliberate "measure first" baseline; embeddings are escalated only if the eval shows retrieval is the bottleneck.
- **Human-labeled gold set** (`data/gold/gold.csv`, 54 snippets) — hand-labeled against a written guide (`data/gold/README.md`) that sharpened the `policy` definition, disjoint from the corpus so grounding a snippet never retrieves itself. Builder scripts `scripts/build_gold.py` and `scripts/add_policy_gold.py`.
- **Honest eval harness** (`src/gold_eval.py`) — the workhorse classifier graded against the human labels: category **88.9%** (macro-F1 **0.906**), operational domain **88.9%** (macro-F1 **0.894**) — the non-circular numbers v1's self-grading could not produce. Headline fix: **`industry` F1 1.000** on real SEC earnings/M&A, v1's worst class (recall 0.217 → caught 1 in 5); honest caveat is `n=5` clear-cut filings. An **Opus judge** is validated against the human labels at **88.9%** category / **94.4%** domain agreement, so it can serve as a scalable answer key where hand-labeling doesn't reach. Report in `evals/gold_eval.txt`.
- **Retrieval-grounded classification + citations** (`src/classify_rag.py`) — prepends the top-k label-tagged BM25 neighbors as reference context and returns the citations that grounded the call. Lift measured by `src/gold_eval_rag.py` with a flip analysis: **+1.9%** category accuracy (2 wrong→right, 1 right→wrong), domain **flat** (3 fixed / 3 broke). Conclusion: lexical BM25 grounding does **not** justify upgrading to embeddings here — the negative result is the finding (`evals/gold_rag_eval.txt`).
- `model=` parameter on `classify()` so the Opus judge runs the identical prompt, tool schema, and label validation as the workhorse — baseline vs judge differ only by model tier.
- `DVIDS_API_KEY` documented in `.env.example` (the read-only **public** key only; the secret key is unused).
- Unit tests for the retriever, the gold-eval metrics, and grounded classification — all offline/mocked, no API key needed.

### Changed
- **README rewritten to lead with the v2 numbers**, structured as a v1→v2 arc: v2's honest, human-graded results up top; v1's synthetic self-graded eval kept as the foundation and the `industry` blind spot it surfaced (which v2's real SEC text then closed).
- `pyproject.toml` version bumped `1.1.0` → `2.0.0`.

---

## [1.1.0] — 2026-06-21

Tightened the measurement around the v1.0.0 classifier: macro-F1, a multi-run stability harness, a full error audit, and an enum-validation guard (which caught and corrected an inaccurate docs claim along the way).

### Added
- `LICENSE` — MIT license
- README status badges (CI, release, license, Python version)
- `docs/how-it-works.md` — plain-language one-pager on the three-stage pipeline and why the classifier/evaluator separation is the point, with a "Threats to validity" section
- `docs/CASE_STUDY.md` — narrative writeup (problem, key decisions, the reverted experiment, honest limitations, what's next); linked from the README
- **Macro-averaged precision/recall/F1** in the eval report (`macro_average` in `src/eval.py`) — every label weighted equally, so a collapsed minority class is no longer hidden by raw accuracy. Category macro-F1 is **0.765** (below its 79.0% accuracy); domain is **0.973**. Two new unit tests cover it.
- **Multi-run stability harness** (`src/stability.py`) — runs the full eval N times and reports mean / std / min / max per headline metric, so a config difference can be checked against the run-to-run noise floor (clears ~2x std?) instead of trusting a single run. Optional `--temperature` flag; per-run predictions saved to `evals/runs/`, summary to `evals/stability.txt`. `classify()` and `classify_with_retry()` gained an optional `temperature` parameter. Six new unit tests cover the pure aggregation/reporting functions. First run (5 passes) puts category accuracy's run-to-run std at 0.24 points and domain accuracy's at 0.50 points; the reverted prompt experiment's 2.3-point drop clears that noise floor by ~10x, confirming it was a real regression rather than sampling noise.
- `.env.example` — committed template documenting the `ANTHROPIC_API_KEY` the project needs; copy to `.env` (gitignored) and load with `uv run --env-file .env`. README gained an "API key & secrets" subsection covering the pattern, the rationale, and the machine-local caveat (`.env` is recreated on a fresh clone — the deliberate trade-off of keeping secrets out of git).
- `evals/error_audit.md` — manual audit of all 67 misclassifications, separating genuine classifier errors from label-scheme ambiguity. 90% of category misses fall in the `industry`/`procurement`/`technology` triangle, where a company winning a contract matches two label definitions at once — so the gap is label overlap, not model capability.
- **Enum validation guard** in `classify()` (`InvalidLabelError` + `_validate`) — the result is checked against the allowed `CATEGORIES`/`DOMAINS` and the call is re-sampled once on an out-of-enum response before raising. A tool-use `enum` is a guided prior, not a hard server-side constraint: one prediction in a 300-article run came back as an invalid category (`category="cyber"`), and this guards against it. New unit tests (plus a sequence-returning test client) cover validation, the re-sample, and the raise.

### Fixed
- Corrected an inaccurate claim across `README.md`, `docs/CASE_STUDY.md`, `docs/how-it-works.md`, and PRD requirement F9 that out-of-enum output is "rejected/enforced at the API layer." Tool use enforces the response *shape* and strongly biases toward valid labels, but enum membership is validated in our code, not guaranteed by the API. (Surfaced by the error audit; see above.)

### Changed
- `pyproject.toml` version bumped `0.1.0` → `1.0.0` to match the released tag
- README results table now reports macro-F1 alongside accuracy
- `evals/metrics.txt` regenerated to include the macro-average rows (recomputed from existing predictions, no re-classification)
- Added a plain-language definition of precision, recall, and F1/macro-F1 to `docs/how-it-works.md` (with a short gloss in the README results section), so the headline metric isn't unexplained jargon
- Readability pass over `README.md`, `docs/CASE_STUDY.md`, and `docs/how-it-works.md`: trimmed heavy em-dash use in favor of colons, commas, and periods

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

[Unreleased]: https://github.com/sanlee-ys/defense-news-classifier/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/sanlee-ys/defense-news-classifier/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/sanlee-ys/defense-news-classifier/releases/tag/v0.1.0
</content>
</invoke>
