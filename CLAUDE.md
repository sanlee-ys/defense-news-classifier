# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# CLAUDE.md — Defense News Classifier

## Project
A clean-room NLP project that classifies **public defense-related news articles and reports**. Given a piece of defense news (free text), the system assigns a **category** (what the article is about) and an **operational domain** (the warfighting domain it relates to). Built and evaluated on **synthetic and/or public text only** — no proprietary or non-public data is used anywhere in this project.

This is a personal portfolio project with two aims: (a) demonstrate practical, hands-on AI engineering, and (b) measure classification quality rigorously. **The measured eval results are the centerpiece, not just a working demo.** The subject is the open-source analysis side of defense — categorizing public news and reports — nothing operational.

## Scope (v1 — lean)

**In scope:**
- A synthetic dataset generator: use an LLM to produce a few hundred realistic, labeled defense-news snippets spanning the categories and domains below.
- A classifier: a single LLM call with **structured (JSON) output** mapping article text → `{category, operational_domain}`.
- An eval harness: a held-out labeled test set, overall accuracy, per-label precision/recall for both fields, confusion matrices, and a log of misclassifications for failure analysis.
- A README that leads with the eval numbers and a short writeup.

**Explicitly out of scope for v1 — do NOT build these:**
- A web UI
- RAG / retrieval over a document corpus
- Any scraping pipeline, database, auth, or multi-user features
- Model fine-tuning
- A third "region" field (see note below — keep v1 to two fields for a clean eval)

Keep the project small and finishable. If something starts to feel like scope creep, flag it and ask before adding it.

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

v1 (synthetic, self-graded) and v2 (real text + human gold + BM25 retrieval) have shipped;
**`v2.0.0` is the current release.** Releases follow **semver** (`MAJOR.MINOR.PATCH`) and
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

A worked progression from today's `v2.0.0` (the concrete plan, not just the theory):

| Version | Bump | What it would ship | Why that bump |
|---|---|---|---|
| **v2.0.1** | patch | Backfill the v2 eval modules' missing tests (`gold_eval_rag.py` is at 0% coverage, `gold_eval.py` 55%, `retrieve.py` 76%) and fix any edge cases they expose | Pure correctness/hardening — no feature, contract untouched |
| **v2.1.0** | minor | **Scale the eval with the validated judge** — grade 300+ real snippets with the Opus judge (validated at 88.9% / 94.4%) and report confidence intervals, so n=54's noise floor shrinks | New capability, same output contract → MINOR; PATCH resets to 0 |
| **v2.1.1** | patch | Fix whatever the scaled run exposes — e.g. a resume/batching bug in the judge harness or a larger-data CI timeout | A fix *on top of* v2.1.0 → third digit increments |
| **v2.2.0** | minor | **Tiered model routing** — escalate only low-confidence `industry`-vs-`procurement` cases to Opus, measure the cost/quality trade | Additive, callers unaffected → MINOR again; PATCH back to 0 |
| **v3.0.0** | major | **Add a `region` field** — output becomes `{category, operational_domain, region}` (`indo-pacific`, `europe`, …), needs a fresh gold-labeling pass | Breaks the output contract → MAJOR; MINOR + PATCH reset to 0 |

Read straight down the third digit: it climbs *within* a line (`2.0.1`, `2.1.1`) and **resets to
0 every time a digit to its left moves** (`2.1.0`, `2.2.0`, `3.0.0`). That reset rule is the
whole game — a version number is a promise about what changed, not a counter.

**Guiding principle (carried over from v1):** model tier and feature scope are per-task
cost/quality knobs **decided by the eval, not by default** — measure first, escalate only where
it pays. That's why "scale the eval" (v2.1.0) comes *before* "route to a premium model"
(v2.2.0): you earn the right to spend by measuring first.

**Parking lot (unversioned until picked):**
- A thin **Streamlit demo UI** — turns the eval harness into a usable product; arguably its own
  major surface (changes what the project *is*), so it'd likely force a major bump if added.
- **Semantic / embedding retrieval** — only if a larger eval overturns v2's measured verdict
  that "BM25 grounding doesn't justify embeddings." Borderline minor-vs-major depending on
  whether it reshapes the grounding story.
- RAG over real public text — **done in `v2.0.0`.**

## Links — verify before sending (hard rule)

Added 2026-07-04 after repeated 404s from links given in chat. Any clickable
reference given to the user must actually resolve:

1. **Full URLs only.** Point at files with the complete
   `https://github.com/<owner>/<repo>/blob/<ref>/<path>` URL — never a
   local-clone path like `<repo-folder>/materials/foo.md`, whose leading
   repo-folder segment doubles when pasted after a GitHub branch URL and 404s.
2. **Verify before sending.** Confirm the exact path exists on the exact ref
   before linking (e.g. GitHub MCP `get_file_contents`, or `git ls-tree
   origin/<branch> -- <path>` after a confirmed push). Unverified links do not
   get sent — say "unverified" instead.
3. **Branch links are perishable.** A `blob/<feature-branch>` URL dies when the
   branch merges and is deleted. Flag branch-scoped links as such; prefer
   `main` URLs once the work has merged.

If a link 404s, the failure mode was here — fix the process, not just the link.
