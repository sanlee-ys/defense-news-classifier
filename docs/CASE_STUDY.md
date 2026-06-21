# Case Study — Defense News Classifier

*A short, honest writeup of what I built, the decisions behind it, and what the
measurement taught me. The reference docs are the [README](../README.md) and
[`how-it-works.md`](how-it-works.md); this is the narrative version.*

---

## The one-line summary

I built an LLM system that classifies public defense-news snippets into a **category**
and an **operational domain**, and — more importantly — a rigorous **evaluation** that
measures exactly how well it works and where it fails. The eval is the point, not the demo.

**Headline result:** 79.0% category accuracy (macro-F1 0.765) and 97.3% operational-domain
accuracy (macro-F1 0.973) on a 300-article labeled test set. Shipped as a tagged v1.0.0.

---

## Why I built it

I wanted a portfolio piece that proves hands-on AI engineering judgment, not just a working
demo. The brief I set myself was deliberately narrow and finishable: a real classifier, a
real eval, and an honest writeup — built entirely on synthetic, publicly safe data so there
was nothing proprietary anywhere near it. "Small and finished" was a design goal, not a
limitation; a tagged release beats an impressive-looking repo that was abandoned half-built.

## What it does

Given a plain-text defense-news snippet, the system assigns two labels:

- **category** — `procurement` · `operations` · `policy` · `technology` · `industry`
- **operational_domain** — `air` · `land` · `sea` · `cyber` · `space` · `multi`

It does this with a single LLM call per article (Anthropic `claude-sonnet-4-6`), using
tool-use to force structured JSON output constrained to the valid label set.

## The key decisions (and why)

I treated each design choice as something I should be able to defend, and recorded the
significant ones as ADRs (`decisions/`). The ones that mattered most:

- **Separate the data, the classifier, and the eval into three stages.** The classifier
  only ever sees article text, never the label, so it cannot "cheat." That separation is
  what lets the eval put an honest *number* on quality instead of just asserting it works.
- **Force structured output with tool-use, not free-text JSON.** The API validates the
  response against an enum schema before returning it, so an out-of-range label is rejected
  at the API layer — reliability of *form* is enforced, not patched up afterward in Python.
- **Hand-compute the metrics (no scikit-learn).** Precision/recall from TP/FP/FN is short
  and standard; doing it by hand kept the dependency list tiny and meant I understood every
  number, rather than borrowing them from a black box. The metric code is unit-tested.
- **Pick a mid-tier model on purpose.** Sonnet 4.6 is capable enough for a fixed-label
  classification task and cheap enough for the ~330 calls an eval run costs. Model tier is a
  cost/quality knob I decided with the eval, not a default — the bigger model buys almost no
  headroom on a task that's already at 97% on domain.

## What the measurement found

Operational domain is essentially solved at 97.3% — the model reliably separates air, land,
sea, cyber, space, and multi from short text. Category is harder at 79.0%, and the failure
is concentrated in **one** place: `industry` recall is 0.22. Four of five industry articles
get predicted as `procurement`, because both involve defense companies and money, and a
short snippet often doesn't carry enough signal to tell "a company's own business news"
from "a company winning a purchase." Knowing precisely *where* and *why* it fails — not just
the headline number — is the payoff of building a real eval.

## The decision I'm most proud of: the one the data reversed

The obvious fix for the industry/procurement confusion was to spell the distinction out in
the prompt. I did exactly that — added an explicit "a firm winning a specific contract is
procurement; a firm reporting earnings or merging is industry" rule — and re-ran the full
eval expecting a lift.

It **regressed.** Category accuracy fell 79.0% → 76.7% and `industry` recall dropped 0.217 →
0.100. The sharper wording just gave the model a cleaner rule for dumping borderline company
stories into `procurement`. So I reverted the prompt, kept the baseline numbers, and recorded
the experiment as a negative result in the changelog.

That's the whole case for building an eval at all: a change that *read* better to a human
moved the decision boundary the wrong way, and only the measurement caught it. I'd rather
ship 79% I can trust than 77% I talked myself into.

## Being honest about the limits

The numbers come with real caveats, and I document them rather than hide them
(see "Threats to validity" in `how-it-works.md`):

- **Circular eval:** the same model generates and classifies the data, so the score measures
  in-distribution consistency more than real-world generalization.
- **Model-asserted ground truth:** the labels were attached by the generator, not verified
  by a human, so some "misclassifications" may be bad labels.
- **Accuracy hides imbalance:** I report macro-F1 alongside accuracy precisely because raw
  accuracy lets a collapsed minority class hide.
- **Single forced label:** genuinely two-category articles still get exactly one.

To stop the negative-result claim from resting on a single run, I also built a stability
harness that runs the full eval N times and reports the run-to-run standard deviation — so a
"this is better than that" claim can be checked against the noise floor before I believe it.
Over five passes, category accuracy's run-to-run std is **0.24 points** (`evals/stability.txt`),
so the ~2x-std threshold for a meaningful difference is about half a point. The reverted
experiment's 2.3-point drop is roughly **10x** that noise floor — confirming it was a real
regression, not sampling noise. (The same check showed the single-run 79.0% I report is the
*low* end of the five runs, not a cherry-picked high.)

## Engineering practices

The project is built like real software, not a notebook dump: dependency management and a
lockfile (`uv`), a unit-test suite that mocks the API and runs offline, CI on every push,
formatting/linting/type-checking via pre-commit (Black, Ruff, mypy), ADRs for the decisions,
a Keep-a-Changelog history, and a tagged v1.0.0 release. Secrets are read from the
environment via a documented `.env` pattern and never committed.

## What I'd do next (v2)

- **RAG over real public reports** — retrieve real source text at query time so the model
  classifies grounded in actual documents. This directly attacks the circular-eval limitation
  and lets outputs cite a source.
- **Tiered model routing** — keep Sonnet as the workhorse, escalate only the low-confidence
  `industry`/`procurement` boundary cases to a higher tier, so the premium model runs on the
  ~15% of articles that actually need it.
- **A `region` field** and **multi-label output** for genuinely two-category articles.

## What I took away

The headline isn't the accuracy number — it's the discipline. Build the thing, measure it
honestly, let the measurement overrule your intuition, and document where it can't be
trusted. That's the difference between "I made an AI thing" and "I built a system, measured
how good it actually is, and can tell you exactly where it breaks."
