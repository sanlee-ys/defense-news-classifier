# Defense News Classifier — Personal Notes

## Environment setup

```bash
# One-time: install everything (project deps + dev tools)
uv sync --group dev

# Optional: Jupyter for analysis notebook
uv sync --group notebook
uv run jupyter notebook   # opens browser tab with file browser

# Set your API key before running anything that calls the API
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # PowerShell
# export ANTHROPIC_API_KEY="sk-ant-..." # bash
```

---

## Key commands

```bash
# Run the dataset generator (makes 30 API calls, ~300 articles → data/synthetic_articles.csv)
uv run python src/generate.py

# Classify one article inline
uv run python src/classify.py "The Pentagon awarded Lockheed Martin a $1.2B contract for F-35 maintenance."

# Classify from stdin (pipe-friendly)
echo "..." | uv run python src/classify.py

# Run the full eval (classifies every article in data/, saves results to evals/)
uv run python src/eval.py

# Tests
uv run pytest                    # all tests
uv run pytest --cov=src          # with coverage
uv run pytest tests/test_generate.py  # one file

# Linting / formatting / type checks
uv run black src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
```

---

## How the project works (v1)

The whole system is three scripts in `src/`. Each can be run and inspected independently.

### 1. `src/generate.py` — dataset generator

**What it does:** Produces `data/synthetic_articles.csv`, a labeled dataset of ~300 synthetic
defense-news snippets.

**How it works:**
- There are 5 categories × 6 domains = **30 combinations** (e.g. `procurement × air`,
  `technology × cyber`).
- For each combo, it makes **one API call** asking Claude to write 10 distinct snippets labeled
  with that combo's values. That's 30 API calls total.
- Structured output is forced via **tool use** (`tool_choice: {"type": "tool", "name":
  "generate_articles"}`). The tool schema includes `enum` constraints on `category` and
  `operational_domain`, so Claude can't drift to synonyms like `"aerial"` instead of `"air"`.
- Results accumulate into `rows[]` and are written to CSV at the end.
- A 0.5s sleep between calls keeps it inside rate limits.

**Key function:** `generate_combo(client, category, domain) -> list[dict]`

**Output columns:** `id`, `text`, `category`, `operational_domain`

---

### 2. `src/classify.py` — the classifier

**What it does:** Takes a raw article text, returns `{"category": "...", "operational_domain": "..."}`.

**How it works:**
- Single LLM call with a system prompt that defines all six labels (both fields) and the
  key distinctions (e.g. procurement vs industry: "A firm *winning a specific contract* is
  procurement; a firm *reporting earnings or merging* is industry").
- Again uses **forced tool use** (`classify_article` tool) so the response is always structured
  JSON, never free text.
- `classify(client, text)` is the core function — importable from other scripts.
- `make_client()` builds the Anthropic client from `ANTHROPIC_API_KEY`.
- CLI entry point accepts text as args or from stdin.

**Key function:** `classify(client, text) -> dict`

**Label audit, 2026-08-20 — the synthetic set disagreed with this convention 42 times.**
A full read of all 300 rows in `data/synthetic_articles.csv` found three defect classes,
all of them the convention above applied backwards:

| Move | Rows | Shape |
|---|---|---|
| `industry` → `procurement` | 25 | A government buyer awards a valued contract and the award is the story. |
| `technology` → `procurement` | 8 | The same shape, found in `technology`. |
| `industry` → `technology` | 9 | A company unveils a system or reports a test milestone. |

`procurement`, `operations` and `policy` were clean; those 180 rows needed no change.

The clearest evidence is two duplicate stories that carried opposite labels. Rows 2 and
290 were both "Lockheed Martin has been awarded a $N contract by the U.S. [Air Force /
Department of Defense] to [produce / develop]", labeled `procurement` and `industry`. Rows
41 and 221 are both the DGA awarding Thales Alenia Space the Syracuse 5 satellite
contract, labeled `procurement` and `technology`. No surface rule separates either pair,
because there is no difference to separate.

**Why this matters beyond the data.** The first live run of the ADR-026 outer loop learned
the defect and wrote it into the prompt as a rule: label `industry` when a named company
is the lead sentence's grammatical subject. That reverses the convention above. The run
gained +0.132 macro-F1 on split A and +0.131 on B while the real gold set C did not move
at all (0.936 both ends), because gold carries the correct convention and has none of
these rows. Branch `loop/prompt-optimize` was not merged. See
[ADR-026](../../decisions/archive/026-ralph-loop-honest-ruler.md) and
[ADR-003](../../decisions/003-synthetic-data-only.md).

**Every A/B figure computed before 2026-08-20 rests on the uncorrected labels.** Gold-set
and scale-eval figures use different data and are unaffected.

---

### 3. `src/eval.py` — evaluation harness

**What it does:** Runs the classifier on every article, then produces accuracy, per-label
precision/recall/F1, confusion matrices, and a misclassification log.

**How it works:**
- Loads `data/synthetic_articles.csv`.
- **Resume support:** if `evals/predictions.csv` already exists from a previous run, articles
  with existing predictions are skipped. Each prediction is written immediately after the API
  call, so a crash never loses more than one call's work.
- `classify_with_retry()` wraps the classifier with exponential backoff (2s → 4s) for
  transient 500/429 errors.
- Metrics are computed in plain Python + pandas — no sklearn. The logic is in `compute_metrics()`:
  for each label it computes TP/FP/FN manually, then precision = TP/(TP+FP), recall = TP/(TP+FN).
- Confusion matrices use `pd.crosstab`.

**Output files in `evals/`:**
| File | What it contains |
|------|-----------------|
| `predictions.csv` | Raw predictions (id, pred_category, pred_operational_domain) |
| `metrics.txt` | Human-readable report: accuracy + per-label P/R/F1 for both fields |
| `confusion_category.csv` | Confusion matrix for category |
| `confusion_domain.csv` | Confusion matrix for operational_domain |
| `misclassifications.csv` | Every row where at least one field was wrong |

---

## Labels reference

**category** (what the article is about):
- `procurement` — contracts, acquisitions, budgets, program awards (buyer's perspective)
- `operations` — active conflict, deployments, military operations
- `policy` — legislation, treaties, strategy, doctrine
- `technology` — R&D, new systems, autonomous/drone/AI developments
- `industry` — company-side news: earnings, mergers, layoffs (company's perspective)

**operational_domain** (warfighting domain):
- `air` — aircraft, missiles, UAVs
- `land` — ground forces, armored vehicles, infantry
- `sea` — naval vessels, submarines, maritime
- `cyber` — information warfare, network attacks, EW
- `space` — satellites, launch systems
- `multi` — joint/spans more than one domain

---

## Project layout

```
/data         synthetic_articles.csv (generated, not hand-labeled)
/src          generate.py, classify.py, eval.py, api.py
/tests        unit tests for all four modules
/evals        predictions + metrics output (git-ignored or committed after a run)
/decisions    ADRs — why Anthropic API, why tool use, why synthetic data, why no sklearn
/docs/notes   this file
```

---

## Design choices worth knowing

- **Why synthetic data?** No proprietary or non-public data anywhere. Makes the project
  shareable. See `decisions/003-synthetic-data-only.md`.
- **Why tool use for structured output?** More reliable than asking the model to return raw JSON
  in the message body. The enum constraints in the tool schema prevent label drift. See
  `decisions/002-structured-output-via-tool-use.md`.
- **Why no sklearn for eval?** Keeps dependencies minimal and makes the metric math transparent.
  See `decisions/004-no-ml-framework-for-eval.md`.
- **Why Anthropic API?** See `decisions/001-llm-provider.md`.
