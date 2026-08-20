# ADR-011: Re-aim v2.2.0 tiered routing at technology-vs-operations, not industry-vs-procurement

**Status:** Accepted
**Date:** 2026-07-16
**Deciders:** San Lee

---

## Context

The versioning roadmap (CLAUDE.md) plans **v2.2.0 — tiered model routing** as:

> escalate only low-confidence `industry`-vs-`procurement` cases to Opus, measure the
> cost/quality trade

That `industry`-vs-`procurement` target was chosen from the **synthetic** confusion
matrix (`evals/confusion_category.csv`), where `industry` → `procurement` is by far the
dominant category confusion (35 of 60 `industry` snippets are graded `procurement`). On the
synthetic data, that is unambiguously the hard pair.

The per-cell breakdown of the **real, human-labeled** gold set (n=54) — introduced in the
gold-set confusion tool (PR #78, `evals/gold_confusion.md`) — tells a different story. The
category disagreements do not spread randomly; they cluster, and **not** on the pair the
roadmap assumes:

| Judge-vs-human category miss | Count | Snippets |
|---|---|---|
| `technology` → `operations` | 3 | g007, g036, g040 |
| `procurement` → `industry` | 1 | g020 |
| `operations` → `policy` | 1 | g053 |

On real text, `industry`/`procurement` is a **non-issue**: exactly one borderline case
(g020, Crane Army restarting a C4 production line), which is genuinely ambiguous rather than
a systematic confusion. The five `industry` earnings snippets (g054–g058) are all correct.
The real clustered category confusion is **`technology` → `operations`** (3 of 5 misses) —
a system being built, tested, or demonstrated by an operational unit or during an exercise,
read as `operations`. The domain axis shows an analogous concentration: over-assignment to
`land` (`land` precision 0.786, the lowest on the axis).

So the feature as roadmapped would spend premium-model budget escalating the pair the real
eval says is already fine, and ignore the pair it actually gets wrong. The synthetic
generator makes a *different* pair hard than reality does — which is itself worth recording,
because it is the kind of "the synthetic proxy disagreed with the real measurement" finding
the project exists to surface.

Two caveats bound this. First, the tech→ops cluster is **3 cases out of 54** — it rests on
the same small sample whose noise floor v2.1.0 ("scale the eval") exists to shrink. Second,
the roadmap already sequences v2.2.0 *after* v2.1.0 on the principle "you earn the right to
spend by measuring first." Both caveats point the same way: re-aim the target now while the
evidence is fresh, but do not build the feature until the eval is larger.

## Decision

**When v2.2.0 tiered routing is built, aim its confidence-triggered escalation at the
`technology`-vs-`operations` boundary, not `industry`-vs-`procurement`** — and keep the
roadmap's existing sequencing (build it after v2.1.0, not before).

Concretely:

1. **Target pair.** The low-confidence cases escalated to Opus are the ones on the
   `technology`/`operations` line (e.g. a new system tested or demonstrated in an
   operational setting), which the gold set shows is where the workhorse and the judge
   actually disagree with human labels. `industry`/`procurement` is dropped as the target on
   the strength of the real-text evidence.
2. **Consider a domain escalation too, separately.** The `land` over-assignment is the
   domain-axis analogue. Whether it warrants its own confidence gate is left open — it is a
   smaller, fuzzier cluster (2–3 cases, and the human labels themselves split on
   close-air-support), and a prompt fix (see PR #79) may resolve it more cheaply than
   routing. Decide this against the scaled eval.
3. **Sequencing is unchanged.** v2.2.0 still follows v2.1.0. The confidence threshold and
   the target pair both rest on n=54 today; v2.1.0 is what earns the right to set them. This
   ADR re-aims a future decision; it does not authorize building the feature now.
4. **A prompt fix is tried first.** PR #79 proposes prompt clauses for exactly these two
   clusters. If, once measured on the scaled eval, the prompt change clears the tech→ops
   cluster on its own, tiered routing for that pair may be unnecessary — routing is the
   fallback for the residual the prompt cannot fix, not the first tool.

This ADR changes **no code and ships no feature.** It records the target correction and its
evidence so the roadmap's v2.2.0 row is not built to the wrong specification.

## Consequences

- **The roadmap's v2.2.0 row is updated** to name the `technology`/`operations` target and
  point at this ADR (CLAUDE.md, same PR). The illustrative row otherwise stands.
- **The `industry`/`procurement` framing is retired for routing purposes** but not deleted
  from the record — it remains the correct read of the *synthetic* data, and the
  synthetic-vs-real divergence is the point worth keeping.
- **The target is provisional on n=54.** If v2.1.0's scaled run reshapes the category
  confusion (e.g. `industry`/`procurement` re-emerges at scale, or a new pair appears), this
  ADR is superseded by whatever that larger measurement shows. It is a course correction on
  current evidence, not a permanent verdict.
- **No version bump.** A documentation/decision change with no output-contract effect.
- **Order of operations for v2.2.0 is now explicit:** scale the eval (v2.1.0) → see whether
  the PR #79 prompt fix already clears tech→ops → build routing only for the residual, aimed
  at tech/ops. Each step is gated on the previous one's measurement.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Keep `industry`/`procurement` as the v2.2.0 target per the original roadmap | Contradicted by the real gold set: `industry`/`procurement` is one borderline case on real text, not a systematic confusion. Building the feature to that spec would spend premium budget on a pair the eval says is already fine. |
| Build v2.2.0 now, aimed at tech/ops, on the n=54 finding | Premature spend. The cluster is 3 cases; the confidence threshold would be tuned on the exact noise floor v2.1.0 exists to shrink. The roadmap's "measure first, then escalate" principle sequences routing after the scaled eval for this reason. |
| Skip the ADR; just edit the roadmap row | The correction is not a typo — it is a decision backed by a synthetic-vs-real divergence that should be recorded with its evidence, so a future reader knows *why* the target moved and can reopen it if the scaled eval disagrees. |
| Fold this into PR #79 (the prompt fix) | Different concern and different artifact: #79 is a measurable code change to the shipped prompt; this is a forward-looking target correction for an unbuilt feature. Keeping them separate honors one-concern-per-PR and lets the prompt fix be measured on its own. |
