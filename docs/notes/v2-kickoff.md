# v2 Kickoff: the RAG iteration

*A warm-start breadcrumb for whoever (human or a fresh Claude session) begins v2, so the
work doesn't re-derive what v1 already settled. Read this together with `CLAUDE.md`, the
`README.md`, and `docs/CASE_STUDY.md`.*

---

## Where v1 left off

- **v1.1.0 is tagged and released.** `main` is the source of truth; the two releases
  (v1.0.0, v1.1.0) are frozen snapshots.
- **What exists:** a synthetic data generator, a classifier (single Anthropic call with
  tool-use, an enum schema, and an in-code validation guard), and an eval harness
  (accuracy, per-label precision/recall/F1, macro-F1, confusion matrices, a
  misclassification log, `evals/error_audit.md`, and a multi-run stability harness).
- **Headline numbers:** category 79.0% accuracy (macro-F1 0.765), operational domain 97.3%
  (macro-F1 0.973), on a 300-article synthetic test set.
- **The key finding to carry forward:** ~90% of category misses are *label-scheme overlap*
  (the `industry` / `procurement` / `technology` boundary), not model error. The ceiling is
  label ambiguity, not model horsepower. See `evals/error_audit.md`.
- **The limitation v2 should attack:** the eval is *circular* — the same model generates and
  grades the data, so "ground truth" is model-asserted, not human-verified.

## What v2 is (and isn't)

v2 is the **RAG iteration**, plus a few related upgrades parked in the `CLAUDE.md`
"Note for later" section (a `region` field, tiered model routing, multi-label output, an
LLM judge for grading real data).

The thesis: move from synthetic, self-graded data toward **real public text, grounded
retrieval, and an eval that doesn't depend on a model-made answer key.**

Keep the scope discipline from `CLAUDE.md`: **one concern per session/branch.** RAG alone is
plenty for one iteration. Do not try to land RAG + region + tiered routing all at once.

## The three open scoping questions (decide these first, before code)

1. **Corpus** — what real public reports/news to retrieve over, and where they come from.
   Public / clean-room only, same constraint as v1. How is it stored and indexed (embeddings?
   a vector store? something simpler)?
2. **How retrieval changes the pipeline** — does retrieved source text feed the classifier as
   extra context, ground a cited source, or both? Where does the retrieval step sit relative
   to the single classify call?
3. **The eval rethink** — with real text there is no model-made answer key, so v1's
   auto-grading breaks. Options: hand-label a small gold set, and/or use a top-tier model as
   an **LLM judge** (flagged in `CLAUDE.md`). Decide *how v2 measures quality* before building
   it — same "measure first" discipline that made v1 honest.

## Constraints carried from CLAUDE.md (don't re-litigate these)

- Synthetic and/or **public** text only. Nothing proprietary or non-public, anywhere.
- Secrets from the environment (`ANTHROPIC_API_KEY`); never commit `.env`.
- Minimal dependencies; `uv` for the env; Black / Ruff / mypy / pre-commit; keep CI green.
- Branch from fresh `main`, one concern, short-lived branch → PR → merge → delete.
- Model tier is a per-task cost/quality knob decided **by the eval**, not a default. Sonnet is
  the workhorse; escalate to a higher tier only where the eval shows it pays.

## How to start the v2 session

1. Open a **new session** (fresh context budget).
2. `git checkout main`, pull, then branch (e.g. `v2-rag`).
3. Read this file, `CLAUDE.md`, `README.md`, and `docs/CASE_STUDY.md` to load context cold.
4. Answer the three scoping questions *with San* before writing code — surface the design
   choices and confirm, don't silently pick.
5. Build in small steps. Measure first.
