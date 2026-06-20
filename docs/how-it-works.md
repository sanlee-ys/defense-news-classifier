# How It Works — Defense News Classifier (one-pager)

A plain-language tour of what the system does, how the pieces fit, and *why* it's
built this way. If you only remember one thing: **the classifier sorts the news;
the evaluator grades the classifier — and keeping those two jobs separate is the
entire point of the project.**

---

## The one-sentence version

Given a short defense-news snippet, the system assigns two labels — a **category**
(what the article is about) and an **operational domain** (the warfighting domain it
relates to) — using a single LLM call, and then *measures how often it gets those
labels right* against a known answer key.

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

### 1. `generate.py` — build the labeled data (the answer key)
Calls Claude to produce 300 synthetic defense-news snippets, evenly spread across all
30 combinations of category × domain (5 categories × 6 domains, 10 articles each).
Crucially, each snippet comes out **with its correct labels already attached** — this
is the ground truth, the answer key everything else is measured against.

*Why synthetic?* No proprietary or scraped text anywhere — the project is clean-room
by design. Trade-off acknowledged openly (see the "circular eval" caveat below).

### 2. `classify.py` — sort one article (the thing being tested)
The actual classifier. Takes one article's **text only** — never its label — makes a
single Claude call, and returns `{category, operational_domain}`. This is the model
under test. It is the only stage that does the "AI" job of deciding.

*Why one call with forced tool-use?* The API validates the answer against a fixed list
of allowed labels (an enum schema) *before* returning it, so the model physically
cannot emit a label outside the valid set. Reliability is enforced at the API layer,
not patched up afterward in Python.

### 3. `eval.py` — grade the classifier (the measurement)
Runs the classifier across all 300 articles, lines each prediction up against the
ground-truth label, and computes the report card: overall accuracy, per-label
precision / recall / F1, confusion matrices, and a log of every miss.

*Why hand-compute the metrics instead of importing scikit-learn?* The math (TP/FP/FN →
precision/recall) is short and standard; doing it by hand keeps the dependency list
tiny and proves the numbers are understood, not borrowed from a black box.

---

## Why the separation IS the point

It would have been easy to mash these together — one script that generates, classifies,
and prints an accuracy number. Resisting that is what makes the result trustworthy:

- **The classifier never sees the answers.** Because `classify.py` is handed text and
  nothing else, it can't "cheat." The score reflects genuine decisions, not leakage.
- **You can put a *number* on quality.** Separating the answer key (stage 1) from the
  thing being measured (stage 2) is exactly what lets stage 3 say "79.0% category
  accuracy" and mean it. No separation → no honest measurement.
- **Each stage runs and is inspected on its own.** You can regenerate data without
  touching the classifier, or re-grade existing predictions without spending API calls.
- **It mirrors how real ML evaluation works** — train/build the system, hold out a
  labeled test set, measure against it. Same discipline, small scale.

This is the difference between *"I made an AI thing"* and *"I built a system and then
measured how good it actually is, and can tell you exactly where it fails."*

---

## What the measurement found

- **Operational domain: 97.3%** — essentially solved. Air/land/sea/cyber/space/multi
  are easy to tell apart from short text.
- **Category: 79.0%** — harder, and the failure is concentrated in *one* place:
  `industry` recall is 0.22. Four out of five industry articles get mislabeled as
  `procurement`, because both involve defense companies and money. Short snippets often
  don't carry enough signal to separate "a company's own business news" from "a company
  winning a purchase."

Knowing *where* and *why* it fails — not just the headline number — is the payoff of
having a real eval.

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

These aren't hidden — they're in the README, the ADRs, and stated up front. Knowing the
limits of your own measurement is part of the measurement.
