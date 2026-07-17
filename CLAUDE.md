# CLAUDE.md — Defense News Classifier

## Project
A clean-room NLP project that classifies **public defense-related news articles and reports**. Given a piece of defense news (free text), the system assigns a **category** (what the article is about) and an **operational domain** (the warfighting domain it relates to). Built and evaluated on **synthetic and/or public text only** — no proprietary or non-public data is used anywhere in this project.

This is a personal portfolio project with two aims: (a) demonstrate practical, hands-on AI engineering, and (b) measure classification quality rigorously. **The measured eval results are the centerpiece, not just a working demo.** The subject is the open-source analysis side of defense — categorizing public news and reports — nothing operational.

## Scope — stay lean

The project is deliberately small and finishable: a synthetic **and** real-text
dataset, a single-call classifier with **structured (JSON) output** mapping
article text → `{category, operational_domain}`, and a rigorous eval harness
(overall accuracy, per-label precision/recall, confusion matrices, a
misclassification log) fronted by a README that **leads with the numbers**.
`v2.0.0` added BM25 RAG grounding over real public text, which was later **measured and
retired** ([ADR-012](decisions/012-retire-bm25-grounding.md)) once it stopped beating the
ungrounded classifier — the shipped classifier is ungrounded. The `region` field is the
planned `v3.0.0` breaking change. Version specifics — what ships when and why — live in
**Versioning roadmap** below, not here.

Still out of scope unless a version deliberately picks it up: a web UI, scraping
pipelines, databases, auth / multi-user, and model fine-tuning. If something
starts to feel like scope creep, flag it and ask before adding it — the
roadmap's parking lot is where unplanned ideas wait their turn.

## Domain definitions
**category** (what the article is primarily about):
- `procurement` — contracts, acquisitions, budgets, program awards
- `operations` — active conflict, deployments, military operations
- `policy` — legislation, treaties, strategy, doctrine
- `technology` — R&D, new systems, autonomous / drone / AI developments
- `industry` — defense-company business, earnings, mergers

**operational_domain** (the warfighting domain involved):
- `air`, `land`, `sea`, `cyber`, `space`, `multi` (joint / spans more than one)

These labels are a starting point. If a cleaner set emerges once you see the data, propose the change and confirm before switching.

## Tech stack
- Python 3.11+
- LLM via the **Anthropic API** (or OpenAI — confirm which key I'm using). Read the API key from an environment variable; **never hardcode keys**.
- Structured outputs / JSON schema for the classifier response.
- Minimal dependencies: the LLM client (`anthropic` or `openai`) plus `pandas` for the eval tables. Avoid heavy frameworks.
- Dependency management via **uv**: `pyproject.toml` declares deps, `uv.lock` pins them, `uv sync` builds the env, and `uv run` executes scripts. `requirements.txt` is kept as a pip fallback.

  Quick uv workflow:
  ```bash
  uv sync --group dev          # install project and test dependencies
  uv run pytest                # run unit tests
  uv run pytest --cov=src      # run tests with coverage
  uv run python src/generate.py  # generate the synthetic dataset
  uv run python src/classify.py "<article text>"  # classify one article
  uv run python src/eval.py    # run the full evaluation
  ```
- Eval is plain Python; a Jupyter notebook for the analysis is fine.
- Code style: **Black** (`uv run black src/ tests/`), **Ruff** for linting (`uv run ruff check src/ tests/`), **mypy** for type checking (`uv run mypy src/`). All at line length 88, targeting Python 3.11. **pre-commit** runs these automatically before each commit.

## Project structure
```
/data        synthetic articles + labels
/src         generator, classifier, eval
/evals       eval results, confusion matrices
README.md
CLAUDE.md
```

## How to work with me
- **Explain the key decisions** briefly as you make them (why this prompt design, why this eval metric) so the code is understood, not just run.
- Prefer **clear, readable code with short comments** over clever one-liners.
- Work in **small steps**. After each step, explain what was done and what's next, and wait for review before moving on.
- When there's a real design choice (how to structure the eval, how to handle an article that spans two categories), **surface it and ask** rather than silently picking.
- Write code so each piece can be run and inspected independently.

## Working across multiple sessions
Each web session runs in its own fresh container and can't see another session's uncommitted work — the **only** shared coordination point is `main`. Everything here follows from that. These rules exist because parallel sessions once built the same CI workflow three times (PRs #4/#5/#6) and forked off a stale `main`, causing conflicts.

- **One concern per session → one branch → one PR.** If the deliverable doesn't fit in a sentence, it's two sessions. Don't wander into adjacent cleanup.
- **Before starting, check open PRs and branches** for the same work. A 10-second look prevents duplicate efforts.
- **Branch from fresh `main`, merge fast, delete the branch on merge.** Short-lived branches are the whole game — the longer a branch lives, the more it drifts from `main`.
- **Serialize changes to shared files; parallelize only genuinely independent work.**
  - Must serialize (collision hotspots): `pyproject.toml`, `uv.lock`, `README.md`, `.github/workflows/*`, anything restructuring layout.
  - Safe to parallelize: separate `src/` modules, isolated docs, separate test files.
  - **Parallelize by independent *file*, not by *task*.** Cut a session per file that nothing else touches — never one session per task when the tasks collide on the same file. **Generated or aggregated files (build outputs, indexes, registries, generated HTML/SVG) especially can't be merged**, so when several pieces of work feed one of them, keep that *wiring* in one hand: author the independent content in parallel, then have a single integrator do the registration + rebuild once, after the content lands.
- **Name branches by intent, not a session slug** (`fix-industry-labels`, not `claude/recent-changes-xyz`) so duplicates are obvious at a glance.
- **If many sessions run at once, designate one "integrator"** that owns merging to `main` and keeping it green; others stay feature-scoped and rebase on its merges.

## Definition of done (v1)
- Run the generator and produce a labeled synthetic dataset of defense-news snippets.
- Run the classifier on any article and get a structured `{category, operational_domain}` back.
- Run the eval and see accuracy, per-label precision/recall, confusion matrices, and a list of the misclassified cases.
- The README leads with those numbers and explains the design and the limitations honestly.

## Versioning roadmap

v1 (synthetic, self-graded) and v2 (real text + human gold + BM25 retrieval, since retired —
[ADR-012](decisions/012-retire-bm25-grounding.md)) have shipped;
**`v2.0.1` is the current release.** Releases follow **semver** (`MAJOR.MINOR.PATCH`) and
[Keep a Changelog](https://keepachangelog.com/) — every milestone gets a git tag + a CHANGELOG
entry. The line to internalize:

- **PATCH** (`x.y.Z`) — a *fix*. No new capability, no change to the `{category,
  operational_domain}` output contract. Same behavior, just more correct.
- **MINOR** (`x.Y.0`) — a new, **backward-compatible** capability. The contract still holds;
  you added something, you didn't change what callers already rely on. **Bumping MINOR resets
  PATCH to 0.**
- **MAJOR** (`X.0.0`) — a **breaking** change: the output contract, label schema, or core
  methodology changes so prior results/integrations no longer apply. **Bumping MAJOR resets
  MINOR *and* PATCH to 0.**

A worked progression from `v2.0.0` (the concrete plan, not just the theory):

| Version | Bump | What it would ship | Why that bump |
|---|---|---|---|
| **v2.0.1** | patch | Remove the dead Kafka consumer path (`src/consumer.py` + its Testcontainers integration test) once notes-api dropped Kafka for a `BackgroundTasks` writeback | Pure dead-code hardening — no feature, contract untouched — **shipped 2026-07-05** |
| **v2.0.2** | patch | Backfill the v2 eval modules' remaining orchestration tests — the API-driving run-loops and `main()` entrypoints the pure-function tests skipped in `gold_eval_rag.py` (62%), `stability.py` (58%), `retrieval_error_analysis.py` (82%), `gold_eval_haiku.py` (86%) — and fix any edge cases they expose | Pure correctness/hardening — no feature, contract untouched |
| **v2.1.0** | minor | **Scale the eval with the validated judge** — grade 300+ real snippets with the Opus judge (validated against the human labels: 90.7% category / 92.6% domain agreement on the current Sonnet-5-era run, `evals/gold_eval.txt`) and report confidence intervals, so n=54's noise floor shrinks | New capability, same output contract → MINOR; PATCH resets to 0 |
| **v2.1.1** | patch | Fix whatever the scaled run exposes — e.g. a resume/batching bug in the judge harness or a larger-data CI timeout | A fix *on top of* v2.1.0 → third digit increments |
| **v2.2.0** | minor | **Tiered model routing** — escalate only low-confidence `technology`-vs-`operations` cases to Opus, measure the cost/quality trade ([ADR-011](decisions/011-reaim-tiered-routing-technology-operations.md) re-aimed this from `industry`-vs-`procurement`: on the real gold set that pair is a non-issue, while `technology`→`operations` is the clustered miss) | Additive, callers unaffected → MINOR again; PATCH back to 0 |
| **v3.0.0** | major | **Add a `region` field** — output becomes `{category, operational_domain, region}` (`indo-pacific`, `europe`, …), needs a fresh gold-labeling pass | Breaks the output contract → MAJOR; MINOR + PATCH reset to 0 |

Read straight down the third digit: it climbs *within* a line (`2.0.1` -> `2.0.2`, then `2.1.1`)
and **resets to 0 every time a digit to its left moves** (`2.1.0`, `2.2.0`, `3.0.0`). That reset
rule is the whole game — a version number is a promise about what changed, not a counter.

**Landed on `main`, not in the progression above (both still `[Unreleased]` in the CHANGELOG):**
- **Evals-as-CI capability gate** ([ADR-007](decisions/007-evals-as-ci-gate.md)) — CI tooling
  (wires the gold-set evals into CI as an offline PR gate plus a paid live gate). It does not
  change the `{category, operational_domain}` output contract, so on its own it doesn't earn a
  bump — it rides along with whichever version is next tagged.
- **Rung-1 prompt-optimization loop, autonomy ladder L3** ([ADR-005](decisions/005-agentic-prompt-optimization-loop.md),
  [spec](docs/specs/prompt-optimization-loop.md)) — a new, backward-compatible capability, so by
  the rule above it *would* be MINOR. The loop spec's §11 deliberately defers that bump
  **until after `v2.1.0`** ("scale the eval" — v2.1.0 is what shrinks the noise floor this
  loop's own honest numbers depend on), which has not shipped yet. So this capability is built,
  tested, and merged, but intentionally carries no version number yet — that's the spec's
  sequencing call, not an oversight.

**Guiding principle (carried over from v1):** model tier and feature scope are per-task
cost/quality knobs **decided by the eval, not by default** — measure first, escalate only where
it pays. That's why "scale the eval" (v2.1.0) comes *before* "route to a premium model"
(v2.2.0): you earn the right to spend by measuring first.

**Parking lot (unversioned until picked):**
- A thin **Streamlit demo UI** — turns the eval harness into a usable product; arguably its own
  major surface (changes what the project *is*), so it'd likely force a major bump if added.
- **Semantic / embedding retrieval** — v2's "BM25 grounding doesn't justify embeddings"
  verdict has only hardened: [ADR-012](decisions/012-retire-bm25-grounding.md) retired
  grounding entirely after it stopped paying under the improved prompt. This stays parked
  unless a future eval shows semantic retrieval beating the 94%+ ungrounded baseline — a high
  bar. Borderline minor-vs-major if ever picked up.
- RAG over real public text — shipped in `v2.0.0`, then **retired** (ADR-012); the grounding
  code is kept dormant as the record.

<!-- shared:links-verify v1 -->
## Links — verify before sending (hard rule)

Links given in chat must resolve: **full `github.com/<owner>/<repo>/blob/<ref>/<path>` URLs only**, **verify the path exists on the ref before sending** (unverified → say so), and **branch links are perishable** (prefer `main` once merged). Full rule + rationale: [claude-ops `conventions/links-verify.md`](https://github.com/sanlee-ys/claude-ops/blob/main/conventions/links-verify.md).
<!-- /shared:links-verify -->

## Known issue: `uv sync` file-lock races on Windows (Defender)

Observed 2026-07-04: `uv run pytest` / `uv sync` failing repeatedly with
`error: failed to remove directory ...dist-info\... Access is denied. (os error 5)`,
hitting a *different* package each retry (`fastapi`, then `ruff`, then `uv` itself). No
python/pytest/uvicorn process was holding the venv — this is a genuine race condition, not a
stuck process. `uv` deletes and recreates a package's `dist-info` folder when upgrading it;
Windows Defender's real-time scanner grabs a transient lock on the newly-written files mid-swap,
so the delete loses the race. Retrying blind makes it worse: a partial delete leaves the
`dist-info` folder missing its `RECORD` file, so later runs skip cleanup on that package too
("may result in an incomplete environment"), and the errors compound onto new packages each
retry.

**Fix:** stop retrying piecemeal — `uv venv --clear && uv sync` rebuilds the venv clean in one
shot. **Prevention:** add a Windows Defender exclusion for the repo path
(`Add-MpPreference -ExclusionPath "C:\path\to\repo"`, needs an elevated shell) so `uv` isn't
racing the scanner on every sync. This is per-sync flakiness, not systemic venv corruption —
sibling repos' venvs (checked the same day) were unaffected.
