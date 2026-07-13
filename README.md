# Defense News Classifier

[![tests](https://github.com/sanlee-ys/defense-news-classifier/actions/workflows/tests.yml/badge.svg)](https://github.com/sanlee-ys/defense-news-classifier/actions/workflows/tests.yml)
[![release](https://img.shields.io/github/v/release/sanlee-ys/defense-news-classifier)](https://github.com/sanlee-ys/defense-news-classifier/releases)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

An NLP pipeline that classifies public defense-related news snippets into a **category**
(what the article is about) and an **operational domain** (the warfighting domain involved).
**v1** is built and graded entirely on synthetic, publicly safe data; **v2** moves to *real*
public-domain text (DoD news wire + SEC filings), grounds each call with retrieval, and grades
against a human-labeled answer key. The workhorse now runs on **Claude Sonnet 5** (migrated
July 2026, [ADR-010](decisions/010-rag-path-model-pin.md)). The measured eval numbers are the
centerpiece.

---

## Results

The project ran in two iterations, and the arc between them *is* the story. v1 proved the
pipeline on synthetic data the model graded itself. v2 swapped in real text and a human answer
key to find out what that self-grading was hiding. A third chapter kept the v2 methodology and
swapped the model: in July 2026 the workhorse moved from Sonnet 4.6 to Sonnet 5 and was
re-measured on the same gold set. Those are the current numbers, directly below.

| | v1 | v2 |
|---|---|---|
| **Data** | 300 synthetic snippets the model wrote | 54 real public-domain snippets (DoD news wire + SEC filings) |
| **Answer key** | the same model that classifies (circular) | hand-labeled by a human, cross-checked by an Opus judge |
| **Retrieval** | none | BM25 over a 62-doc corpus; each call grounded + cited |
| **Honest read** | in-distribution *consistency* | real-world *accuracy* |

### Current state — Sonnet 5 on the v2 gold set

The migration went through the same gate as every other change here: run the v2 gold eval
before and after, on the same 54 human-labeled snippets
([ADR-010](decisions/010-rag-path-model-pin.md), `evals/gold_eval.txt`).

| Field | Sonnet 4.6 (v2 as shipped) | Sonnet 5 (current) |
|---|---|---|
| Category accuracy | 88.9% | **90.7%** |
| Category macro-F1 | 0.906 | **0.902** |
| Domain accuracy | 88.9% | **90.7%** |
| Domain macro-F1 | 0.894 | **0.919** |

The current snapshot follows the extended-rubric prompt change (PR #73, which also made the
prompt cache real): category edged up to 90.7% and domain sits at 90.7%. The post-migration
refresh before the rubric had domain at 94.4% — at n=54 a two-flip swing, inside the eval's
own run-to-run noise (see the stability note below), so read the pair as "low 90s," not as a
regression or a lift. The category ceiling remains label ambiguity in borderline snippets,
which neither a stronger model nor a sharper rubric can un-blur.

#### Category: per-label precision / recall / F1 (Sonnet 5, current)

| Label | Precision | Recall | F1 | n |
|---|---|---|---|---|
| industry | 0.833 | 1.000 | 0.909 | 5 |
| operations | 0.913 | 0.955 | 0.933 | 22 |
| policy | 0.857 | 1.000 | 0.923 | 6 |
| procurement | 0.875 | 0.875 | 0.875 | 8 |
| technology | 1.000 | 0.769 | 0.870 | 13 |

The v1 `industry` fix holds: recall stays at 1.000 on the real SEC snippets (v1 caught 1 in 5).
On the refreshed run the Opus judge agrees with the human labels on 90.7% of category calls and
92.6% of domain calls.

**The migration's negative result matters as much as the lift.** Re-running the grounding eval
against the stronger Sonnet 5 baseline showed BM25 grounding *regressing* domain accuracy by
9.3 points (94.4% ungrounded → 85.2% grounded, reproduced 3×): the retrieved neighbors now pull
a confident, correct call sideways more often than they help. The grounded RAG path is
therefore **pinned to `claude-sonnet-4-6`** while the feature's future against the new baseline
is decided — a deliberate, transitional split, not a quiet fork, recorded with full reasoning in
[ADR-010](decisions/010-rag-path-model-pin.md). The grounding comparison further down runs both
arms on Sonnet 4.6 per that pin, so its deltas still measure grounding alone.

---

### v2 — real text, human-graded (the v2 ship, on Sonnet 4.6)

This is the number v1's circular eval could not produce: the classifier run on real defense
news and graded against labels a **human** assigned, not labels the model invented. The numbers
in this section are the v2.0 ship on `claude-sonnet-4-6`, kept as the record of that iteration;
the current Sonnet 5 numbers are above.

| Field | Accuracy | Macro-F1 |
|---|---|---|
| Category | **88.9%** | **0.906** |
| Operational domain | **88.9%** | **0.894** |

**The headline is the fix, not the topline.** v1's worst class was `industry` — recall **0.217**,
the model caught 1 real industry story in 5. On v2's real SEC earnings/M&A snippets that same
class lands at **F1 1.000**. Real text with the actual financial vocabulary (revenue, backlog,
acquisition) gives the model the signal the synthetic snippets never did. The honest caveat:
that's `n=5` clear-cut filings, so read it as "the failure mode is gone on unambiguous cases,"
not "solved at scale."

#### Category: per-label precision / recall / F1 (v2 gold set, Sonnet 4.6)

| Label | Precision | Recall | F1 | n |
|---|---|---|---|---|
| industry | 1.000 | 1.000 | 1.000 | 5 |
| operations | 0.905 | 0.864 | 0.884 | 22 |
| policy | 0.857 | 1.000 | 0.923 | 6 |
| procurement | 0.800 | 1.000 | 0.889 | 8 |
| technology | 0.909 | 0.769 | 0.833 | 13 |

#### Can the judge stand in for the human?

Hand-labeling doesn't scale, so v2 tests whether an **Opus judge** can serve as a cheaper
answer key. It's validated the only honest way — against the human labels (v2 run; the
refreshed post-migration agreement numbers are in the current-state section above):

| | Judge vs human |
|---|---|
| Category agreement | 88.9% |
| Operational domain agreement | 94.4% |

High agreement means the judge tracks human judgment closely enough to grade where
hand-labeling can't reach — the basis for scaling the eval past 54 snippets later.

#### Did retrieval grounding actually help?

v2 grounds each classification in the top-3 BM25-retrieved corpus neighbors (label-tagged) and
returns citations. Whether that *helps* is a measured question, not an assumption — and the
answer is **marginal**. Both arms of this comparison run on `claude-sonnet-4-6` (the RAG pin,
[ADR-010](decisions/010-rag-path-model-pin.md)), so the deltas measure grounding alone:

| | Baseline | Grounded | Δ |
|---|---|---|---|
| Category accuracy | 88.9% | 94.4% | +5.6% |
| Category macro-F1 | 0.906 | 0.950 | +0.044 |
| Domain accuracy | 88.9% | 96.3% | +7.4% |
| Domain macro-F1 | 0.894 | 0.964 | +0.070 |

The flip analysis keeps that honest: on category, grounding changed 5 calls (4 wrong→right, 1
right→wrong); on domain it changed 4 and fixed all 4 (4→0). That is a real shift from the v2
ship, where grounding was marginal (+1.9% category, domain flat, breaking as many domain calls
as it fixed) — the extended-rubric prompt (PR #73) and grounding now reinforce each other
instead of fighting. **The conclusion stands, stronger: lexical BM25 grounding does not earn
the cost of upgrading to embeddings here** — not because grounding barely helps, as at the v2
ship, but because BM25 grounding now clearly works. Same "measure first" principle, new
evidence. One caveat the numbers reopen rather than settle: the Sonnet 5 regression that
motivated the pin (−9.3 domain points, reproduced 3×) was measured with the pre-rubric prompt
and has not been re-run since — whether the pin is still needed under the new prompt is an
open, measurable question (see ADR-010).

Full v2 reports: [`evals/gold_eval.txt`](evals/gold_eval.txt) (baseline + judge) and
[`evals/gold_rag_eval.txt`](evals/gold_rag_eval.txt) (grounding lift).

---

### v1 — synthetic, self-graded (the foundation, and its blind spot)

v1's numbers come from the model classifying 300 snippets *it generated itself*. They measure
in-distribution consistency, not real-world accuracy — but they're what surfaced the `industry`
hole that v2 went on to close, and the reverted-experiment lesson below is the reason v2 trusts
the eval over intuition.

| Field | Accuracy | Macro-F1 |
|---|---|---|
| Category | **79.0%** | **0.765** |
| Operational domain | **97.3%** | **0.973** |

Accuracy is the headline. **Macro-F1** is the more honest single number for an imbalanced
problem: F1 fuses a label's precision and recall into one score, and *macro* averages those
per-label F1s with every label weighted equally, no matter how common the label is. For
category the two diverge: macro-F1 falls *below* accuracy because the collapsed `industry`
class (F1 0.356) is hidden by raw accuracy but counts fully in the macro average. For
operational domain the classes are balanced, so the two agree. (Plain-language definition of
precision, recall, and F1 in [`docs/how-it-works.md`](docs/how-it-works.md).)

#### Category: per-label precision / recall / F1

| Label | Precision | Recall | F1 |
|---|---|---|---|
| procurement | 0.561 | 1.000 | 0.719 |
| operations | 1.000 | 0.933 | 0.966 |
| policy | 1.000 | 0.967 | 0.983 |
| technology | 0.769 | 0.833 | 0.800 |
| industry | 1.000 | 0.217 | 0.356 |

#### Operational domain: per-label precision / recall / F1

| Label | Precision | Recall | F1 |
|---|---|---|---|
| air | 0.980 | 0.980 | 0.980 |
| land | 0.980 | 0.980 | 0.980 |
| sea | 0.980 | 1.000 | 0.990 |
| cyber | 0.978 | 0.880 | 0.926 |
| space | 0.980 | 1.000 | 0.990 |
| multi | 0.943 | 1.000 | 0.971 |

Confusion matrices and a full misclassification log are in [`evals/`](evals/).

On synthetic data, operational domain was essentially solved at 97.3%. Category was harder at
79.0%, and the failure was concentrated in one place: **`industry` recall 0.22** — the model
caught only 1 in 5 industry articles, predicting the other 4 as `procurement`. Both labels
involve defense companies and money; the distinction is subtle (procurement is a purchase, the
buyer's view; industry is a company's own business news — earnings, mergers), and short
synthetic snippets rarely carried enough signal to separate them. That exact hole is what v2's
real SEC text closed. A full per-case audit is in [`evals/error_audit.md`](evals/error_audit.md);
the notebook (`notebooks/eval_analysis.ipynb`) is the best place to study the misses visually.

#### What I tried that didn't work

The obvious fix for the `industry`/`procurement` confusion is to spell the distinction out in the
prompt. I tried exactly that, adding *"a firm winning a specific contract is procurement; a firm
reporting earnings or merging is industry,"* and re-ran the full eval. It **regressed**: category
accuracy fell 79.0% → 76.7% and `industry` recall dropped 0.217 → 0.100. The sharper wording gave
the model an even cleaner rule for dumping borderline company stories into `procurement`. I reverted
to the baseline prompt and kept the 79.0% numbers reported above. The lesson is the point of having
an eval at all: a prompt change that reads better to a human moved the decision boundary the wrong
way, and only the measurement caught it. And the drop is real, not noise: a 5-run stability check
([`evals/stability.txt`](evals/stability.txt)) puts category accuracy's run-to-run std at 0.24
points, so a 2.3-point regression clears the noise floor by roughly 10x. (See `CHANGELOG.md` for
the full before/after.)

---

## Design

> For a plain-language walkthrough of the three-stage pipeline and why the
> classifier/evaluator separation matters, see [`docs/how-it-works.md`](docs/how-it-works.md).
> For the narrative writeup (decisions, the reverted experiment, and what I'd do
> differently), see [`docs/CASE_STUDY.md`](docs/CASE_STUDY.md).

### Problem

Given a plain-text defense-news snippet, assign two labels:

- **`category`**: `procurement` · `operations` · `policy` · `technology` · `industry`
- **`operational_domain`**: `air` · `land` · `sea` · `cyber` · `space` · `multi`

### Approach (v1 core)

A single LLM call per article using the **Anthropic API** (`claude-sonnet-5` since the
July 2026 migration; v1 and v2 shipped on `claude-sonnet-4-6`) with
[tool use](https://docs.anthropic.com/en/docs/tool-use) to force structured JSON output.
No fine-tuning, no retrieval, no embeddings: just a well-specified prompt and a JSON schema
that biases the output toward the valid label set. v2 keeps this call exactly and only changes
what's *in front of it* (see [v2 architecture](#v2-architecture) below), so the two are
measured apart by precisely the retrieved context.

Tool use (rather than asking the model to return raw JSON in the message body) is the key
reliability mechanism for the response *shape*: you always get the two fields back as
structured data, never free text to parse. The `enum` in the schema strongly biases the model
toward valid labels, but it is **not** a hard server-side constraint: a tool-use schema is a
guided prior, not constrained decoding. So `classify()` validates the returned labels against
the allowed sets and re-samples once on the rare out-of-enum response before raising. This
isn't hypothetical: in one 300-article run exactly one prediction came back out-of-enum
(`category="cyber"`, which isn't a category), which is what prompted adding the guard (see
[`evals/error_audit.md`](evals/error_audit.md)).

### Dataset

300 synthetic defense-news snippets generated by `claude-sonnet-4-6` — the workhorse at the
time, i.e. the same model that classified them in v1 —
uniformly distributed across all 30 category × domain combinations (10 articles each).
The generator uses the same tool-use approach to force correctly labeled output.

All data is synthetic: no proprietary text, no scraping, no real news sources.

### Eval

The classifier is run on all 300 labeled articles. Per-label precision, recall, and F1 are
computed from TP/FP/FN counts (no ML framework needed). The confusion matrices reveal which
label pairs are hardest to distinguish.

One important caveat: **the test data was generated by the same model that classifies it.**
A real-world eval would require human-labeled articles from actual news sources. The numbers
here measure consistency more than true generalization, and should be read in that light.
Closing that caveat is exactly what v2 does.

### v2 architecture

v2 keeps the v1 classifier call untouched and adds three pieces around it, each measured:

1. **A real, public-domain corpus.** 62 documents collected from sources that are legitimately
   free to use: 56 from the **DVIDS** API (the DoD public-affairs news wire — public-domain U.S.
   government text) covering procurement / operations / technology / policy across all six
   domains, plus 6 hand-pulled **SEC** filings for the `industry` class that the military wire
   doesn't carry. `scripts/fetch_corpus.py` pulls and writes the DVIDS manifest;
   `data/corpus/` holds one `.txt` per doc. (The service sites — defense.gov, navy/af.mil —
   hard-block bots, so the DVIDS API and hand-collected SEC text are the clean-room way in.)

2. **Retrieval grounding.** `src/retrieve.py` is a BM25 index (`rank-bm25`, whole-doc, no
   embeddings) over the corpus — the deliberately cheap "measure first" baseline.
   `src/classify_rag.py` retrieves the top-3 label-tagged neighbors for a target article,
   prepends them as reference context, and returns the labels **plus citations**. Because the
   gold set is disjoint from the corpus, grounding a gold snippet never retrieves itself.
   Since the Sonnet 5 migration this grounded path is pinned to `claude-sonnet-4-6`
   ([ADR-010](decisions/010-rag-path-model-pin.md)); the ungrounded workhorse call is not.

3. **An honest eval.** The v1 self-grading is gone. `data/gold/gold.csv` is 54 snippets a human
   labeled by hand against a written [labeling guide](data/gold/README.md). `src/gold_eval.py`
   scores the workhorse against those human labels *and* validates an Opus judge against them;
   `src/gold_eval_rag.py` measures the grounding lift with the flip analysis above. Macro-F1 and
   the flip counts are what keep a lucky topline from masquerading as a real gain.

---

## Project structure

```
data/
  synthetic_articles.csv    # v1: 300 labeled snippets (generated by generate.py)
  corpus/                   # v2: 62 real public-domain docs (one .txt each) + manifests
  gold/
    gold.csv                # v2: 54 hand-labeled real snippets (the answer key)
    README.md               # v2: the human labeling guide
src/
  generate.py               # v1: synthetic dataset generator (30 API calls)
  classify.py               # Classifier: one article -> {category, domain}
  eval.py                   # v1: eval harness on the synthetic dataset
  retrieve.py               # v2: BM25 retriever over the real corpus
  classify_rag.py           # v2: retrieval-grounded classify + citations
  gold_eval.py              # v2: workhorse vs human labels + Opus-judge validation
  gold_eval_rag.py          # v2: grounded vs baseline lift, with flip analysis
  api.py                    # FastAPI service wrapping classify() at POST /classify;
                             #   the live HTTP surface notes-api and kb-agent call
scripts/
  fetch_corpus.py           # v2: pull the DVIDS corpus + write its manifest
  build_gold.py             # v2: pull fresh gold candidates (disjoint from corpus)
  add_policy_gold.py        # v2: targeted backfill for the policy class
evals/
  predictions.csv           # v1: raw predictions (also a resume checkpoint)
  metrics.txt               # v1: accuracy + per-label precision/recall/F1
  confusion_*.csv           # v1: category / domain confusion matrices
  misclassifications.csv    # v1: every article where a prediction was wrong
  error_audit.md            # v1: per-case audit (classifier error vs label ambiguity)
  stability.txt             # v1: multi-run noise floor (std/min/max per metric)
  gold_eval.txt             # v2: real-text baseline + judge agreement
  gold_rag_eval.txt         # v2: grounding lift vs baseline
notebooks/
  eval_analysis.ipynb       # Interactive analysis: heatmaps, F1 charts, miss browser
pyproject.toml              # Project metadata + dependencies (uv)
uv.lock                     # Pinned, reproducible dependency versions
requirements.txt            # pip fallback (kept in sync with pyproject.toml)
README.md
CLAUDE.md
```

---

## Running it

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.
`uv sync` installs the exact versions pinned in `uv.lock` into a local `.venv`,
and `uv run` executes a command inside it, with no manual virtualenv activation needed.

### API key & secrets

The classifier reads `ANTHROPIC_API_KEY` from the environment; it is **never** hardcoded
or read from a tracked file. The convention here is the standard `.env` pattern:

- **`.env.example`** is committed: a secret-free template documenting what the project
  needs.
- **`.env`** is gitignored: you create it locally and paste your real key in. It is never
  committed or synced.
- **`uv run --env-file .env ...`** injects the key for that one run. (Set `UV_ENV_FILE=.env`
  once in your shell profile to drop the flag.) A one-off `export ANTHROPIC_API_KEY=...`
  works too, but it vanishes when the shell closes.

```bash
cp .env.example .env       # then edit .env and paste your key (get one at console.anthropic.com)
```

> **Caveat: `.env` is machine-local by design.** Because it is gitignored, it lives only
> on the machine where you created it. A fresh clone or a new laptop has no `.env`, so you
> recreate it (copy the template, paste the key). That is the deliberate trade-off of
> keeping secrets out of git, not a bug. Never commit `.env`; if it ever shows up in
> `git status` as staged, stop and unstage it.

```bash
uv sync --group dev                    # install project deps + dev/test tools

# Prefix the run commands below with: uv run --env-file .env ...

# 1. Generate the dataset (~30 API calls, ~1 min)
uv run python src/generate.py

# 2. Sanity-check the classifier on one article
uv run python src/classify.py "The Pentagon awarded a \$4.2B contract for 24 F-35 fighters."

# 3. Run the full eval (~300 API calls, ~5 min)
uv run python src/eval.py

# 4. (Optional) Measure run-to-run stability by running the eval N times
uv run python src/stability.py --runs 5     # ~300 calls per run

# 5. Explore results interactively
uv sync --group notebook
uv run jupyter notebook     # open notebooks/eval_analysis.ipynb
```

### v2: real-text eval

The corpus and the human-labeled gold set are already committed, so the v2 eval reproduces with
just `ANTHROPIC_API_KEY` — no corpus re-pull needed. (Re-pulling the corpus with
`scripts/fetch_corpus.py` is the only step that also needs `DVIDS_API_KEY`, the free **public**
DVIDS key; see `.env.example`.)

```bash
# Prefix with: uv run --env-file .env ...

# 1. Baseline on real text + Opus-judge validation (~108 calls: Sonnet + Opus per snippet)
uv run python src/gold_eval.py              # -> evals/gold_eval.txt

# 2. Retrieval-grounded run and the lift vs baseline (~54 calls)
uv run python src/gold_eval_rag.py          # -> evals/gold_rag_eval.txt

# 3. (Optional) Re-pull the DVIDS corpus — needs DVIDS_API_KEY
uv run python scripts/fetch_corpus.py
```

Both v2 eval scripts checkpoint their predictions and resume if interrupted, same as v1.

> No uv? Install it from the [uv docs](https://docs.astral.sh/uv/getting-started/installation/),
> or fall back to plain pip: `pip install -r requirements.txt` then run the scripts with `python` directly.

The eval script saves predictions as it goes and supports resuming: if interrupted, rerun
`uv run python src/eval.py` and it will pick up from where it left off.

### Rung-1: the prompt-optimization loop

An agent iterates the classifier's system prompt against the eval until an explicit
done-signal fires — Level 3 of the [autonomy ladder](docs/specs/autonomy-ladder.md), spec'd in
[docs/specs/prompt-optimization-loop.md](docs/specs/prompt-optimization-loop.md) and decided in
[ADR-005](decisions/005-agentic-prompt-optimization-loop.md). Each iteration: read misclassified
examples + confusion stats from set **A** only, propose a revised prompt, re-score **A/B/C**, and
check the done-signal. **Feedback signal** = set-A failures (never B or C — that is the Goodhart
guard: B drives the stop condition and C is the honest held-out number, so neither can leak into
the thing being optimized). **Done-condition** = the first of threshold (category macro-F1 on B
reaches target), plateau (no B-improvement for 3 iterations), or budget (iteration/token cap —
the fail-safe backstop). **Overfitting guard** = the A-vs-B and B-vs-C gaps reported every
iteration, plus the A-vs-C delta across the whole run as the headline number.

```bash
# Dry run: zero API calls, deterministic mock backend — safe to run anytime, no key needed.
uv run python src/optimize.py --dry-run

# A real optimization run (spends real tokens against your Anthropic key). Each iteration
# re-scores all of A+B+C (~354 classify calls with the default split) plus one proposer call,
# so 8 iterations is on the order of 2,800+ calls and ~1.7M estimated tokens (~$5-8 at current
# Sonnet pricing). The default token budget (2M) is sized so the ITERATION cap is what stops a
# full default run and the token budget stays the runaway backstop — if you lower it, know that
# one scoring pass estimates at ~185k tokens, so e.g. --token-budget 200000 stops after a
# single edit.
uv run --env-file .env python src/optimize.py --max-iterations 8
```

Either command writes an append-only JSONL run log to `evals/optimize/run_<UTC-timestamp>.jsonl` —
schema documented in [`evals/optimize/README.md`](evals/optimize/README.md), which also explains
why the committed `sample_dryrun_run.jsonl` there is a mock, not a result.

---

## Tests

Unit tests live in [`tests/`](tests/) and cover the logic that doesn't need the network:
the eval metrics (precision/recall/F1, confusion matrices, report text) and the wiring
around the LLM calls (request shape, structured-output parsing, the enum-validation guard,
retry/backoff). The API itself is mocked, so the suite runs offline and needs no API key.

```bash
uv sync           # installs the dev group (pytest, pytest-cov) by default
uv run pytest
```

---

## Evals as a CI quality gate

The v2 numbers above (`evals/gold_eval.txt`, `evals/gold_rag_eval.txt`) are measured once
and committed — nothing stopped them from silently regressing on a later prompt or model
change until now. [`.github/workflows/evals.yml`](.github/workflows/evals.yml) wires the
gold-set evals into CI as two gates, split by API cost (full design rationale in
[ADR-007](decisions/007-evals-as-ci-gate.md)):

- **Offline gate** (every push/PR, free, no key) — grades the prediction CSVs already
  committed in `evals/` against the floors in
  [`evals/thresholds.toml`](evals/thresholds.toml), via `src/eval_gate.py`. It proves the
  shipped numbers still clear the bar and that the scoring code itself still computes them
  correctly. It never calls the API.
- **Live capability gate** (`workflow_dispatch` + a weekly schedule only — **never** on
  `pull_request`) — deletes the cached predictions, re-runs `gold_eval.py` and
  `gold_eval_rag.py` against the real models, then runs the same gate against the fresh
  numbers. This is the actual "did the model/prompt/retrieval get worse" check, and the
  only job that touches `ANTHROPIC_API_KEY`. Restricting it to dispatch/schedule (never
  PRs, and never `pull_request_target`) means a fork PR on this public repo has no path to
  invoke it.

### Go live

The live gate needs a repository secret that does not exist yet — confirm with
`gh secret list -R sanlee-ys/defense-news-classifier` (empty until you add it). Add it,
then trigger a run:

```bash
gh secret set ANTHROPIC_API_KEY -R sanlee-ys/defense-news-classifier
gh workflow run evals.yml -R sanlee-ys/defense-news-classifier
```

Until that secret is set, `live-capability-eval` fails fast with a clear message instead
of silently skipping or half-running. Note `gh workflow run` only finds workflow files
that exist on the ref you dispatch against (the default branch, unless you pass `--ref`),
so this only works once `evals.yml` has been merged to `main`.

### Enforce the gate (required status check)

A failing check is not the same as a blocked merge. As shipped, `offline-gate` reports a
red X on a breaching PR, but GitHub still shows a green "Merge" button next to it — nothing
stops the merge until `offline-gate` is marked a **required status check** in this repo's
branch protection. That's a one-time repo setting, not something `evals.yml` can declare on
its own behalf. Turn it on for `main`:

```bash
gh api repos/sanlee-ys/defense-news-classifier/branches/main/protection \
  --method PUT --input - <<'JSON'
{
  "required_status_checks": {"strict": false, "contexts": ["offline-gate"]},
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
```

(Equivalently: Settings -> Branches -> add/edit the `main` rule -> "Require status checks
to pass before merging" -> select `offline-gate`.) `offline-gate` is the right check to
require — it runs on every PR. `live-capability-eval` deliberately does not (see above), so
it would never report on the PR being merged and there is nothing to require.

### Run the gate locally

No key needed — it grades whatever is already committed:

```bash
uv run python src/eval_gate.py                    # both baseline and rag
uv run python src/eval_gate.py --check baseline    # baseline only
uv run python src/eval_gate.py --check rag         # rag only
```

To exercise the same sequence the live job runs (needs `ANTHROPIC_API_KEY`, costs real
money, ~162 calls total — San only, not something to run casually):

```bash
# Prefix the two eval commands below with: uv run --env-file .env ...
rm -f evals/gold_predictions.csv evals/gold_rag_predictions.csv    # force a fresh run
uv run python src/gold_eval.py
uv run python src/gold_eval_rag.py
uv run python src/eval_gate.py                                     # no key needed
```

---

## Limitations

**v1 (synthetic):**

- **Circular eval:** the same model generates and classifies the data. Numbers measure
  in-distribution consistency, not generalization to real-world news. *(This is the limitation
  v2 set out to close, on a small real-text set.)*
- **No ambiguity handling:** articles that span two categories (e.g., a procurement story
  about a drone contract, both `procurement` and `technology`) get a single forced label.
  The error audit is the best place to study these cases.
- **Synthetic text:** generated snippets are more uniform in style and vocabulary than real
  news. A classifier trained on this data would likely overfit to that style.
- **`multi` domain is underspecified:** it acts as a catch-all for joint operations, which
  makes it both the easiest to recall and the hardest to be precise about.

**v2 (real text):**

- **Small gold set:** 54 hand-labeled snippets buys an *honest* number but a noisy one;
  per-label rates rest on single digits (`industry` is `n=5`, `space` is `n=3`). The validated
  Opus judge is the path to scaling the answer key past what hand-labeling reaches.
- **Lexical-only retrieval:** BM25 matches words, not meaning, so a paraphrased neighbor is
  invisible to it. The eval showed grounding's lift didn't justify embeddings *here* — that
  verdict is specific to this corpus and set size, not a general claim.
- **Corpus skew:** the DVIDS wire is public-affairs copy, so operations/ceremony framing is
  over-represented and `industry` had to be sourced separately from SEC. The corpus is a
  retrieval pool, not a balanced sample of defense news.

---

## Stack

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) for dependency management and reproducible environments
- [`anthropic`](https://github.com/anthropics/anthropic-sdk-python) for the LLM calls
- [`pandas`](https://pandas.pydata.org/) for eval tables and CSV I/O
- [`rank-bm25`](https://github.com/dorianbrown/rank_bm25) for v2 lexical retrieval
- Models: `claude-sonnet-5` (workhorse classifier, since July 2026; v1/v2 shipped on
  `claude-sonnet-4-6`), `claude-sonnet-4-6` (RAG-grounded path, pinned per
  [ADR-010](decisions/010-rag-path-model-pin.md)), `claude-opus-4-8` (v2 eval judge)
- Data sources: [DVIDS](https://www.dvidshub.net/) public-domain DoD news wire,
  [SEC EDGAR](https://www.sec.gov/edgar) filings (v2 corpus)
- `fastapi` + `uvicorn` for the live `src/api.py` service (`POST /classify`), `httpx`
  for its tests — this is the serving surface notes-api and kb-agent call over HTTP;
  not used by the eval scripts above

## Running the service

The eval scripts above call `classify()` directly. To serve classification over HTTP
(the path notes-api's enrichment task and kb-agent's `classify_snippet` tool use):

```bash
uv run --with fastapi --with "uvicorn[standard]" --env-file .env \
  uvicorn api:app --app-dir src --host 127.0.0.1 --port 8000
```

`GET /health` for a liveness check, `POST /classify` with `{"text": "..."}` for a
prediction. See `decisions/SYS-004` (in the `architecture` repo) for the contract.
