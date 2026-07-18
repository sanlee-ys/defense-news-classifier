# How It Works: Defense News Classifier (one-pager)

A plain-language tour of what the system does, how the pieces fit, and *why* it's
built this way. If you only remember one thing: **the classifier sorts the news,
the evaluator grades the classifier, and keeping those two jobs separate is the
entire point of the project.**

---

## The one-sentence version

Given a short defense-news snippet, the system assigns two labels: a **category**
(what the article is about) and an **operational domain** (the warfighting domain it
relates to). It does this with a single LLM call, then *measures how often it gets
those labels right* against a known answer key.

---

## The three stages

The project is deliberately split into three scripts, each with one job. This is the
spine of the whole thing.

```
   generate.py            classify.py              eval.py
 ┌─────────────┐        ┌─────────────┐         ┌──────────────┐
 │  make the   │        │  sort ONE   │         │  grade the   │
 │  answer key │ ─────▶ │  article    │ ──────▶ │  classifier  │
 │ (synthetic  │  data  │ (no answers │ preds   │ vs answer key│
 │   + labels) │        │   in view)  │         │  → metrics   │
 └─────────────┘        └─────────────┘         └──────────────┘
   ground truth          the model under          the measurement
                              test
```

### 1. `generate.py`: build the labeled data (the answer key)
Calls Claude to produce 300 synthetic defense-news snippets, evenly spread across all
30 combinations of category × domain (5 categories × 6 domains, 10 articles each).
Crucially, each snippet comes out **with its correct labels already attached**. This
is the ground truth, the answer key everything else is measured against.

*Why synthetic?* No proprietary or scraped text anywhere; the project is clean-room
by design. The trade-off is acknowledged openly (see the "circular eval" caveat below).

### 2. `classify.py`: sort one article (the thing being tested)
The actual classifier. It takes one article's **text only** (never its label), makes a
single Claude call, and returns `{category, operational_domain, region}` (the region
axis arrived in v3.0.0). This is the model under test, and the only stage that does
the "AI" job of deciding.

*Why one call with forced tool-use?* It guarantees the response *shape*: you always get
the three fields back as structured data, never free text to parse. The enum in the schema
strongly biases the model toward valid labels, but it does not hard-enforce them (a tool
schema is a guided prior, not constrained decoding), so `classify.py` validates the
labels in code and re-samples once on the rare out-of-enum case.

### 3. `eval.py`: grade the classifier (the measurement)
Runs the classifier across all 300 articles, lines each prediction up against the
ground-truth label, and computes the report card: overall accuracy, per-label
precision / recall / F1, confusion matrices, and a log of every miss.

> **What are precision, recall, and F1?** For one label, *precision* asks "when the model
> picks this label, how often is it right?" and *recall* asks "of all the articles that
> truly have this label, how many did it catch?" **F1** is their harmonic mean, so it only
> goes high when *both* are high. **Macro-F1** then averages the per-label F1 scores with
> every label weighted equally, regardless of how common each label is. That equal weighting
> is what makes it honest on an imbalanced problem: a class the model quietly gave up on
> (here, `industry` at F1 0.36) drags the macro average down, where plain accuracy lets the
> common, easy classes paper over it.

*Why hand-compute the metrics instead of importing scikit-learn?* The math (TP/FP/FN →
precision/recall) is short and standard; doing it by hand keeps the dependency list
tiny and proves the numbers are understood, not borrowed from a black box.

---

## Why the separation IS the point

It would have been easy to mash these together: one script that generates, classifies,
and prints an accuracy number. Resisting that is what makes the result trustworthy:

- **The classifier never sees the answers.** Because `classify.py` is handed text and
  nothing else, it can't "cheat." The score reflects genuine decisions, not leakage.
- **You can put a *number* on quality.** Separating the answer key (stage 1) from the
  thing being measured (stage 2) is exactly what lets stage 3 say "79.0% category
  accuracy" and mean it. No separation, no honest measurement.
- **Each stage runs and is inspected on its own.** You can regenerate data without
  touching the classifier, or re-grade existing predictions without spending API calls.
- **It mirrors how real ML evaluation works:** train/build the system, hold out a
  labeled test set, measure against it. Same discipline, small scale.

This is the difference between *"I made an AI thing"* and *"I built a system and then
measured how good it actually is, and can tell you exactly where it fails."*

---

## A third job: the gate enforces the bar

The one-sentence version at the top names two jobs: the classifier sorts, the evaluator
grades. There's a third: **the gate enforces the bar.** `src/gold_eval.py` and
`src/gold_eval_rag.py` measure the classifier against the human-labeled gold set and print
a report — but a report nobody re-checks isn't actually a quality bar, it's a snapshot that
can go stale the moment a prompt or model changes. `.github/workflows/evals.yml` closes
that gap: `src/eval_gate.py` grades the same numbers against floors in
`evals/thresholds.toml` and fails the build if one is breached, split into a free offline
gate (every push/PR, grades what's already committed) and a paid live gate
(`workflow_dispatch` + a weekly schedule only, re-runs the models first). Full rationale —
including why the live gate is deliberately never triggered by a pull request — in
[ADR-007](../decisions/007-evals-as-ci-gate.md).

---

## What the measurement found

- **Operational domain: 97.3%.** Essentially solved. Air/land/sea/cyber/space/multi
  are easy to tell apart from short text.
- **Category: 79.0%.** Harder, and the failure is concentrated in *one* place:
  `industry` recall is 0.22. Four out of five industry articles get mislabeled as
  `procurement`, because both involve defense companies and money. Short snippets often
  don't carry enough signal to separate "a company's own business news" from "a company
  winning a purchase."

Knowing *where* and *why* it fails, not just the headline number, is the payoff of
having a real eval. (A full per-case audit of every miss lives in `evals/error_audit.md`.)

---

## A decision the eval reversed (the honest bit)

The obvious fix for the industry/procurement confusion was to spell the distinction out
in the prompt. I tried exactly that, re-ran the full eval, and it **regressed**:
category accuracy fell 79.0% → 76.7% and industry recall dropped 0.217 → 0.100. The
sharper wording just gave the model a cleaner rule for dumping borderline stories into
`procurement`. I reverted to the baseline prompt and kept the 79.0% numbers.

That's the whole case for building an eval: a change that *read* better to a human moved
the decision boundary the wrong way, and only the measurement caught it. (Full
before/after in `CHANGELOG.md`; the reasoning behind each design choice is in
`decisions/` as ADRs.)

---

## Honest limitations

- **Circular eval:** the same model generates and classifies the data, so the numbers
  measure in-distribution *consistency* more than real-world generalization. A true eval
  would need human-labeled articles from actual news sources.
- **Single forced label:** articles spanning two categories still get exactly one.
- **Synthetic style:** generated snippets are more uniform than real news.

These aren't hidden; they're in the README, the ADRs, and stated up front. Knowing the
limits of your own measurement is part of the measurement.

---

## Threats to validity

The limitations above are about the *system*; these are about whether the **numbers
themselves can be trusted**. Naming them is the point: each is a known seam with a
named fix, not a surprise lurking in the results.

1. **The "negative result" rests on a small sample (originally n=1).** The prompt
   experiment that regressed category accuracy 79.0% → 76.7% was one run of each config,
   and the calls are non-deterministic, so a single 2.3-point move could in principle sit
   inside run-to-run noise. *Addressed in v1.1:* `src/stability.py` runs the full eval N
   times and reports mean / std / min / max per metric. The first 5-run pass put category
   accuracy's run-to-run std at 0.24 points, so the 2.3-point regression clears the noise
   floor by roughly 10x. It was a real regression, not sampling noise. (`uv run python
   src/stability.py --runs 5`)

2. **Circular eval can flatter or deflate.** Because the same model generates and grades
   the data, the score measures self-consistency, not generalization. That cuts both ways:
   one could argue agreement *should* be near-ceiling, which reframes 79% as a ceiling to
   beat rather than a floor. Real-world news would almost certainly score lower.

3. **"Ground truth" is model-asserted, not human-verified.** The generator attached the
   labels and no human checked them, so some misclassifications may be cases where the
   classifier was right and the label was wrong. *Addressed in v1.1:* `evals/error_audit.md`
   audits every miss and finds ~90% of category errors sit on genuinely overlapping label
   definitions (the `industry` / `procurement` / `technology` boundary) rather than being
   clean classifier mistakes.

4. **Accuracy hides class imbalance.** Raw accuracy is propped up by the easy classes;
   `industry` recall of 0.22 barely dents it. Macro-F1 (every class weighted equally) is the
   more honest single number for an imbalanced problem (see the metrics note above).
   *Addressed in v1.1:* the eval now reports macro-F1 alongside accuracy. Category is
   **0.765** (below its 79.0% accuracy, because the collapsed `industry` class counts
   fully); domain is **0.973** (balanced, so the two agree).

5. **Reliability ≠ correctness.** Forced tool-use guarantees the response *shape*, and the
   validation guard keeps labels in-enum, but neither makes a label *correct*. Forcing
   exactly one label on a genuinely multi-category article (a drone *contract* is both
   `procurement` and `technology`) can also manufacture errors. Multi-label output with a
   threshold is the more correct model and a v2 candidate.

None of these break the project; they're the *next* questions. A measurement you can
attack on five specific, ranked grounds, each with a fix, is a measurement you understand.
