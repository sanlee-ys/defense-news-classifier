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
- Code style: **Black** (`uv run black src/ tests/`). Line length default (88). Run before committing.

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
- **Name branches by intent, not a session slug** (`fix-industry-labels`, not `claude/recent-changes-xyz`) so duplicates are obvious at a glance.
- **If many sessions run at once, designate one "integrator"** that owns merging to `main` and keeping it green; others stay feature-scoped and rebase on its merges.

## Definition of done (v1)
- Run the generator and produce a labeled synthetic dataset of defense-news snippets.
- Run the classifier on any article and get a structured `{category, operational_domain}` back.
- Run the eval and see accuracy, per-label precision/recall, confusion matrices, and a list of the misclassified cases.
- The README leads with those numbers and explains the design and the limitations honestly.

## Note for later (v2 ideas, not now)
- Add a `region` field (e.g., indo-pacific, europe, middle-east, americas, africa, global).
- Add RAG over a small corpus of real public reports.
- Add a thin Streamlit UI to demo it.
