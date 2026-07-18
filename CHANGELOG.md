# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versions are tagged by milestone; individual commits are noted where relevant.

---

## [2.2.0] - 2026-07-18

Milestone: **tiered model routing — measured and declined.** The roadmap's v2.2.0 ships as a
measured negative result ([ADR-013](decisions/013-decline-tiered-routing.md)), the project's
second after the BM25 grounding retirement: the routing harness was built, the cost/quality
trade was measured, and the verdict is that routing buys nothing at ~2x the cost. The shipped
classifier stays single-model, single-call.

### Added
- **Tiered-routing experiment: runner-up trigger + offline-replayable measurement harness** (`src/route.py`, `src/route_eval.py`) — the build for the roadmap's **v2.2.0 "tiered model routing"**, aimed at the `technology`-vs-`operations` boundary per [ADR-011](decisions/011-reaim-tiered-routing-technology-operations.md). The shipped classifier forces tool use and so emits no confidence signal; `route.py` manufactures one — a routing-only variant of the classify tool adds a required `runner_up_category` field, and `route()` escalates to the Opus tier exactly when the workhorse reports {technology, operations} as its top-two. `classify_routed()` keeps the `{category, operational_domain}` contract byte-for-byte. `route_eval.py` measures the cost/quality trade with three honesty guards baked in: quality is graded **only on the n=54 human gold set** (the scale set's answer key is the Opus judge — the escalation target itself — so it reports rate/cost, never "accuracy"); escalations are **replayed from the stored judge predictions** (same model, same call shape), so the live spend is one workhorse pass and zero new Opus calls; and the runner-up schema's perturbation of the workhorse's own labels is measured, not assumed away. Shipped with the stated hypothesis that the #79 prompt fix already cleared the target cluster (technology recall 1.000 vs human) and routing likely no longer pays.
- **The measured verdict** (`evals/route_eval.txt`, [ADR-013](decisions/013-decline-tiered-routing.md)) — the hypothesis held, decisively. On the human-graded gold set, routing moved **+0 rows on both axes** (94.4% / 92.6%, identical to the workhorse); the escalated rows read **fixed 0, broke 1, unchanged 8**, where the one change was Opus overriding a correct workhorse answer with the judge's own known tech→ops error (g007). Even all-Opus scores the same 94.4% category as the workhorse — no category router has headroom to capture on this set. On 299 real DVIDS snippets the trigger fires on **19.4%** of articles (changing only 2 labels), pricing the routed pipeline at **~1.97x** the workhorse per article at the 5:1 list-price ratio. Routing is therefore **declined**: the harness, artifacts, and tests stay dormant as the reproducible record, and the shipped path is unchanged. The schema perturbation was small (2/54 category, 0/54 domain) but included one finding worth the record: the runner-up field flipped s151 — a chem-bio *defense* program story the baseline had classified cleanly — into a safety-layer refusal.

### Fixed
- **Runner-up passes survive safety-layer refusals** (`src/route_eval.py`) — the first live scale batch crashed retrieving results when s151 came back `stop_reason='refusal'` (the loop caught transport errors and invalid labels, but a refusal escaped and aborted the retrieval). Both passes now record a `refused` sentinel row and continue: the id counts as done on resume (no re-buying a permanently-refused row every rerun), `_load_runner` excludes sentinel rows from every metric, and the report names the excluded ids so the shrunken n is stated, not silent. The conftest batch fake learned to simulate a refusal (a *succeeded* item with `stop_reason='refusal'` and no tool_use block) so the guard is under test.

## [2.1.0] - 2026-07-17

Milestone: **scale the eval**. This tag also releases everything that had accumulated under
`[Unreleased]` since v2.0.1 (the v2.0.2 hardening, the evals-CI gate, the prompt-optimization
loop, OTel tracing), plus the tech-vs-ops prompt improvement and the BM25 grounding retirement.

### Added
- **Scaled eval with the validated Opus judge** (`src/scale_eval.py`, `scripts/build_scale_set.py`, and `wilson_interval` in `src/eval.py`) — the tooling for the roadmap's **v2.1.0 "scale the eval"**. Grades a ~300-snippet real DVIDS set with the Opus judge as the answer key (validated at 94.4% / 94.4% agreement vs the human gold labels), reporting workhorse accuracy with **95% Wilson confidence intervals** so the n=54 gold set's ~13-point-wide CI shrinks to ~5 points at n=300 — the report shows that narrowing against the committed gold snapshot side by side. Reuses `gold_eval.run_predictions`/`run_predictions_batch` (now `preds_path`-parameterized) and `eval.py`'s metric helpers, so every number is computed identically to the rest of the harness; resume-safe, with an optional `--batch` path. `scripts/build_scale_set.py` sources the snippets from DVIDS disjoint from **both** the corpus and the gold set (no leakage into the judge's own validation data), unlabeled — the workhorse and judge produce the labels at eval time. **Measured on 300 DVIDS snippets:** category **93.3%** (95% CI [89.9%, 95.6%]), domain **90.3%** (95% CI [86.5%, 93.2%]) — half the n=54 CI width, corroborating the gold-set accuracy rather than replacing it. Honest caveats baked into the report (`evals/scale_eval.txt`): it measures workhorse-vs-judge agreement (inherits the judge's ~5–6% human-disagreement ceiling), and the operations-heavy DVIDS skew (`operations` 66%, `industry` n=1) makes the category macro-F1 uninformative — read overall accuracy + the well-populated per-label rows. `{category, operational_domain}` output contract untouched.
- **OpenTelemetry tracing over the `classify()` LLM call** (`src/telemetry.py`) — the classifier's single LLM call is instrumented against the OTel API always; the recording SDK is configured only when `CLASSIFIER_TRACING` is set, so the eval hot path (hundreds of `classify()` calls per optimize iteration) and the offline suite stay a zero-overhead no-op. When on, each call emits a `chat <model>` span with GenAI-semconv attributes (`gen_ai.usage.*` tokens, `gen_ai.response.finish_reasons`) plus the resulting `classifier.category` / `classifier.operational_domain`. Console exporter to stderr by default; OTLP is the optional `otlp` extra. Mirrors the `kb-agent` tracing so the two services share one observability language, and closes the classifier half of the SYS-007 "OTel across notes-api + `/classify`" item. Output contract (`{category, operational_domain}`) is untouched, so this rides `[Unreleased]` without earning a bump.
- **`Jenkinsfile`** — the CI pipeline expressed as a declarative Jenkins pipeline (checkout → `uv sync` → parallel ruff/black/mypy → unit tests with the coverage gate), mirroring `.github/workflows/tests.yml`. GitHub Actions stays the live gate; this is pipeline-as-code for a Jenkins controller (none runs it here, so it has no status check).
- **Evals-as-CI capability gate** (`.github/workflows/evals.yml`, `src/eval_gate.py`, `evals/thresholds.toml`) — wires the v2 gold-set evals (`gold_eval.py`, `gold_eval_rag.py`) into CI as two gates split by API cost: a free offline gate on every push/PR that grades the prediction CSVs already committed against threshold floors, and a paid live gate on `workflow_dispatch` + a weekly schedule only (never `pull_request`, and never `pull_request_target`) that re-runs the real models first and never commits the refreshed numbers back. `build_report()` in both eval scripts now reads from an extracted `metrics()` function — same printed output, now also machine-readable. `Jenkinsfile` gets a matching parity-only offline stage. See [ADR-007](decisions/007-evals-as-ci-gate.md).
- **Rung-1 prompt-optimization loop** (`src/optimize.py`, autonomy ladder L3) — an agent-driven loop that reads the classifier's eval failures on a held-out A split, proposes a revised system prompt, re-scores A/B/C, and repeats until an explicit done-signal fires (threshold, then plateau, then budget). The orchestrator (`run_optimization`) talks to an injected `OptimizerBackend` (`score`, `propose`) rather than the Anthropic client directly, which makes the Goodhart guard structural — B/C never reach the code path that builds the proposer's feedback — and gives a zero-API `--dry-run` mode for free via `DryRunBackend`. Run log is append-only JSONL for resume-safety. See [ADR-005](decisions/005-agentic-prompt-optimization-loop.md) and [the loop spec](docs/specs/prompt-optimization-loop.md). **Per the spec's §11 sequencing, this was held for `v2.1.0`** — which shrinks the n≈54 noise floor its honest held-out number depends on — and, that milestone having shipped in this release, it is released here.
- **Backfilled the v2 eval modules' orchestration tests** — offline tests for the API-driving run-loops and `main()` entrypoints in `src/stability.py`, `src/gold_eval_rag.py`, `src/gold_eval_haiku.py`, and `src/retrieval_error_analysis.py` that the existing pure-function tests deliberately skipped (the run loops, the transient-error retry/backoff, batch polling, and the CLI dispatch/resume-skip branches). They reuse the conftest fake-client / fake-batch stand-ins plus `monkeypatch`ed path constants, so they stay offline — no API key, no network. Lifts those four modules from 58–86% to 99% line coverage — only the `if __name__` guard lines remain, matching `gold_eval.py` — and overall `src/` coverage from 90% to 97% (+18 tests); the `{category, operational_domain}` output contract and all runtime behavior are unchanged. This is the "v2.0.2" hardening from the CLAUDE.md versioning roadmap — recorded here rather than tagged, so it rides the next release like the evals-CI gate above.

### Changed
- **Prompt refinement: technology-vs-operations + the `land` domain default** (`SYSTEM_PROMPT`) — the per-cell gold confusion breakdown showed the clustered misses were `technology`→`operations` (a new system tested/demoed in an operational setting, read as `operations`) and over-assignment to `land`. Two targeted rubric clauses fixed both, **measured on the gold set**: category **90.7% → 94.4%**, domain **90.7% → 92.6%** (`technology` recall to 1.000), nothing regressed. The #78 confusion tool (`src/eval_confusion.py`) is what surfaced the clusters; ADR-011 re-aimed the v2.2.0 tiered-routing target at this pair as a result. Output contract untouched.

### Removed
- **BM25 retrieval grounding, retired** ([ADR-012](decisions/012-retire-bm25-grounding.md)) — once the prompt improved, a **fair same-prompt re-measure** (the earlier grounding "lift" had been scored against a stale, pre-prompt baseline) showed BM25 grounding no longer pays: neutral on category, a domain regression — **0 domain calls fixed and 4 broken across a 3-pass confirm**. It was removed from the shipped path and the CI gate (which now scores only the ungrounded classifier), and `[rag]` was dropped from `thresholds.toml`. The grounding code, corpus, and measurement scripts stay in the repo dormant and reproducible. Supersedes [ADR-010](decisions/010-rag-path-model-pin.md)'s 4.6 pin. `src/api.py` never grounded, so the live service and kb-agent are unaffected.

### Changed (earlier in this release, since superseded)
- **Eval snapshot refreshed post-rubric** — `evals/gold_predictions.csv`, `gold_rag_predictions.csv`,
  and both report files re-run fresh under the extended-rubric prompt, with README numbers swept to
  match (one self-consistent run, mirroring the live CI gate's procedure). Baseline (Sonnet 5):
  category 90.7% (macro-F1 0.902), domain 90.7% (0.919); judge agreement 90.7% / 92.6%. Grounded
  (Sonnet 4.6 pin): category 94.4% (0.950), domain 96.3% (0.964) — grounding's flip ratio improved
  from break-even at the v2 ship to 8 fixed / 1 broken, strengthening the no-embeddings verdict.
  Every gated metric clears its `thresholds.toml` floor. Noted honestly in the README: the
  pre-rubric refresh had Sonnet 5 domain at 94.4% vs 90.7% now (a two-flip swing inside n=54
  noise). ADR-010's Sonnet-5 grounding regression was then re-measured under the new rubric
  (`scripts/adr010_remeasure.py`, 3 passes): it persists at −3.7/−3.7/−5.6 domain, each pass
  breaching the −3.0 floor — smaller than the original −9.3 but not cured, so the RAG pin
  stands (recorded in ADR-010's re-measurement section).
- **`SYSTEM_PROMPT` gains an extended rubric, making prompt caching real** — the prompt now
  encodes the gold set's own labeling conventions (contract award = the buyer's story →
  `procurement`; policy = the rule, not the doing; cyber-vs-host-platform; uncrewed systems
  by operating medium) plus 16 worked examples and an explicit tie-break order, targeting the
  `industry`/`procurement`/`technology` triangle where 90% of the v1 category misses lived
  (`evals/error_audit.md`). Sizing is deliberate: the cacheable prefix (tool schema + system
  prompt) grows from ~876 to ~2425 tokens, clearing claude-sonnet-5's 2048-token minimum
  cacheable-prefix floor — verified live via `scripts/cache_diagnostics.py --live` (call 1:
  `cache_creation=2350`, call 2: `cache_read=2350`), where before the change both calls
  showed the `cache_control` marker as a silent no-op. Bulk paths (eval runs, batches, the
  optimize loop) now re-read the prefix at the 90%-discounted cache rate. The script's
  misleading "not surfaced by this SDK version" message for a null diagnostics field is also
  fixed (null is the API's "no divergence found" answer, per the cache-diagnostics docs).

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
