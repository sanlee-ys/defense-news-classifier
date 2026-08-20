# Defense News Classifier

[![tests](https://github.com/sanlee-ys/defense-news-classifier/actions/workflows/tests.yml/badge.svg)](https://github.com/sanlee-ys/defense-news-classifier/actions/workflows/tests.yml)
[![release](https://img.shields.io/github/v/release/sanlee-ys/defense-news-classifier)](https://github.com/sanlee-ys/defense-news-classifier/releases)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

This project classifies public defense news.
It assigns a **category**, an **operational domain**, and a **region**.
The current release is **v3.2.1**.
The workhorse is **Claude Sonnet 5**.
The gold numbers below are the primary result.

The shipped path is one API call with structured JSON output.
The text is synthetic or public-domain (DoD news wire + SEC filings).

## What it is

Given a defense-news snippet, the system assigns three labels:

- **`category`**: `procurement` · `operations` · `policy` · `technology` · `industry`
- **`operational_domain`**: `air` · `land` · `sea` · `cyber` · `space` · `multi`
- **`region`**: `indo-pacific` · `europe` · `middle-east` · `africa` · `americas` · `global`

`global` is the catch-all for no-anchor and multi-region stories
([ADR-014](decisions/014-region-field-design.md)).
The API enforces the label enum with `strict: true`
([ADR-008](decisions/008-strict-structured-outputs.md)).

The response fields are:

| Field | Meaning |
|---|---|
| `category` | What the article is about |
| `operational_domain` | The warfighting domain |
| `region` | The geographic theater of the subject activity |

## Results

Current gold is **v3.2.1**, n=54, human answer key
([`evals/gold_eval_v3.txt`](evals/gold_eval_v3.txt)).
v3.2.1 adopted a one-bullet `global`-boundary clause
([ADR-024](decisions/archive/024-global-boundary-clause-adopted.md)).

<!-- BEGIN GENERATED: gold-metrics (scripts/gen_readme_metrics.py) -->

| Axis | Accuracy | Macro-F1 | Judge vs human |
|---|---|---|---|
| Category | **94.4%** | 0.93 | 94.4% |
| Operational domain | **98.1%** | 0.982 | 92.6% |
| Region | **94.4%** | 0.975* | 96.3% |

<!-- END GENERATED: gold-metrics -->

\* Region macro-F1 is support-limited (`europe` n=1, `africa` n=2 on a US-wire gold set).
Read the per-label table in the report before you quote it.

Accuracy is workhorse vs human labels.
Macro-F1 averages per-label F1 with equal weight.
Judge vs human is Opus-judge agreement with those labels.

The table above is generated from [`evals/metrics.json`](evals/metrics.json).

```bash
uv run python scripts/gen_readme_metrics.py --check
```

### v1 and v2

v1 used synthetic text.
v2 used real public-domain text.

| | v1 | v2 |
|---|---|---|
| **Data** | 300 synthetic snippets the model wrote | 54 real public-domain snippets (DoD news wire + SEC filings) |
| **Answer key** | the same model that classifies (circular) | hand-labeled by a human, cross-checked by an Opus judge |
| **Retrieval** | none | BM25 over a 62-doc corpus, tried and cited — then measured and **retired** ([ADR-012](decisions/archive/012-retire-bm25-grounding.md)) |
| **Honest read** | in-distribution *consistency* | real-world *accuracy* |

### Classical baseline

TF-IDF + logistic regression is the local classical stack.
ADR-017 froze this bake-off on the n=54 human gold set.
The LLM column is the bake-off snapshot (92.6% / 92.6%).
It does not track the headline table (v3.2.1: 94.4% / 98.1%).
This table has no `metric:` markers.
A marker would pull today's artifact into a historical comparison
([ADR-017](decisions/archive/017-classical-baseline-bakeoff.md),
[`evals/baseline_eval.txt`](evals/baseline_eval.txt)).

| Axis | Classical baseline | LLM (bake-off snapshot) | McNemar (paired, exact) |
|---|---|---|---|
| Category | 72.2% [59.1, 82.4] | 92.6% | p=0.013 |
| Operational domain | 66.7% [53.4, 77.8] | 92.6% | p=0.0005 |

### Measured work

- **BM25 grounding** stopped beating the ungrounded classifier. It was retired ([ADR-012](decisions/archive/012-retire-bm25-grounding.md), [`evals/gold_rag_eval.txt`](evals/gold_rag_eval.txt)).
- **Tiered routing** moved +0 rows on both axes at ~1.97x cost. It was declined ([ADR-013](decisions/archive/013-decline-tiered-routing.md), [`evals/route_eval.txt`](evals/route_eval.txt)).
- **kNN exemplars** scored category 91.0% vs 90.0% on the n=300 scale eval (McNemar p=0.70). They were declined ([ADR-019](decisions/archive/019-knn-exemplar-fewshot.md), [`evals/exemplar_eval.txt`](evals/exemplar_eval.txt)).
- **L4 multi-agent review** fixed 6 of 7 region misses. It then harmed domain (91.3% → 86.7%, n=300, McNemar p=0.016) at ~4× calls. It was declined ([ADR-020](decisions/archive/020-l4-multi-agent-pipeline.md), [`evals/l4_eval.txt`](evals/l4_eval.txt)).
- **The `global`-boundary clause** shipped in v3.2.1 after a pre-registered re-run at n=595 (McNemar p=0.0002) ([ADR-024](decisions/archive/024-global-boundary-clause-adopted.md), [`evals/region_clause_rerun.txt`](evals/region_clause_rerun.txt)).

## Gold set

[`data/gold/gold.csv`](data/gold/gold.csv) holds 54 hand-labeled public-domain snippets.
The label guide is [`data/gold/README.md`](data/gold/README.md).
`src/gold_eval.py` scores the workhorse against those labels.
It also validates an Opus judge against the same labels.

Confusion matrices live in [`evals/gold_confusion_v3.md`](evals/gold_confusion_v3.md).

A scaled judge-graded region eval at n=300 is a frozen dated figure
([ADR-022](decisions/archive/022-scaled-region-eval-verdict.md),
[`evals/scale_eval_v3.txt`](evals/scale_eval_v3.txt)).

## Run

This project uses [uv](https://docs.astral.sh/uv/).
`uv sync` installs the versions pinned in `uv.lock`.
`uv run` runs a command in that environment.

The classifier reads `ANTHROPIC_API_KEY` from the environment.
It never reads a key from a tracked file.

```bash
cp .env.example .env
```

On PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and paste your key.
Get a key at [console.anthropic.com](https://console.anthropic.com).
`.env` is gitignored.
A fresh clone has no `.env`.
Recreate it from the template.
Never commit `.env`.

```bash
uv sync --group dev
```

### Classify one snippet

```bash
uv run --env-file .env python src/classify.py "The Pentagon awarded a \$4.2B contract for 24 F-35 fighters."
```

The command prints JSON on stdout.

### Gold eval

```bash
uv run --env-file .env python src/gold_eval.py
```

The report writes to [`evals/gold_eval_v3.txt`](evals/gold_eval_v3.txt).
The script checkpoints predictions and resumes if you interrupt it.
This run spends about 108 API calls (Sonnet + Opus per snippet).

### Synthetic eval

```bash
uv run --env-file .env python src/generate.py
```

`src/generate.py` writes 300 labeled snippets.
This run spends about 30 API calls.

```bash
uv run --env-file .env python src/eval.py
```

`src/eval.py` scores the classifier on that set.
This run spends about 300 API calls.
Rerun the same command to resume an interrupted eval.

If you do not have uv, install it from the
[uv docs](https://docs.astral.sh/uv/getting-started/installation/).
Or use `pip install -r requirements.txt` and run the scripts with `python`.

## Tests

The suite in [`tests/`](tests/) mocks the API.
It needs no key.

```bash
uv sync --group dev
```

```bash
uv run pytest
```

## CI gate

The offline gate grades committed prediction CSVs against
[`evals/thresholds.toml`](evals/thresholds.toml).
It never calls the API.
Design: [ADR-007](decisions/007-evals-as-ci-gate.md).

```bash
uv run python src/eval_gate.py
```

If the prompt or the model changed, and the gold eval did not re-run,
the gate exits 1 with `STALE SNAPSHOT`.
Re-run the gold eval so the numbers describe the shipped classifier.

## Service

The eval scripts call `classify()` directly.
This command serves classification over HTTP:

```bash
uv run --with fastapi --with "uvicorn[standard]" --env-file .env \
  uvicorn api:app --app-dir src --host 127.0.0.1 --port 8000
```

`GET /health` is the liveness check.
`POST /classify` with `{"text": "..."}` returns a prediction.

## Notebook

```bash
uv sync --group notebook
```

```bash
uv run jupyter notebook
```

Open `notebooks/eval_analysis.ipynb`.

## Stack

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) for dependencies
- [`anthropic`](https://github.com/anthropics/anthropic-sdk-python) for the LLM calls
- [`pandas`](https://pandas.pydata.org/) for eval tables and CSV I/O
- Models: `claude-sonnet-5` (workhorse), `claude-opus-4-8` (eval judge)
- Data: [DVIDS](https://www.dvidshub.net/) public-domain DoD news wire, [SEC EDGAR](https://www.sec.gov/edgar) filings
- `fastapi` + `uvicorn` for the live `src/api.py` service (`POST /classify`)

## Design

- [`docs/how-it-works.md`](docs/how-it-works.md): the pipeline
- [`docs/CASE_STUDY.md`](docs/CASE_STUDY.md): the narrative writeup
- [`decisions/`](decisions/): the ADRs
- [`data/gold/README.md`](data/gold/README.md): the label guide
- [`evals/`](evals/): reports and confusion matrices
- [`evals/metrics.json`](evals/metrics.json): the published gold artifact

## Limits

- The human gold set has 54 snippets. Per-label rates rest on single digits.
- Each axis gets one label. A snippet that spans two categories gets one forced label.
- Region classes are thin on a US-wire gold set (`europe` n=1, `africa` n=2).
