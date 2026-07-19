# Feature Spec — Prompt-Optimization Loop

**Version:** 0.1 (Draft)
**Status:** Proposed
**Author:** San Lee
**Last updated:** 2026-06-27
**Roadmap fit:** new **MINOR** (backward-compatible; the `{category, operational_domain}` output contract is untouched). Proposed to sequence **after v2.1.0** — see §11.
**Related:** ADR 005 (decision record, to be written) · [master PRD](../PRD.md) · [autonomy-ladder roadmap](autonomy-ladder.md) (this loop is **Level 3** of that spine)
**Portfolio framing:** this is the repo-side implementation of the "loop engineering demo," which is **Level 3** of the [autonomy ladder](autonomy-ladder.md). The repo calls it a *prompt-optimization loop* (what it does); the portfolio calls it *loop engineering* (the skill it demonstrates). The outward showcase is the **classifier's project page** (`/projects/defense-news-classifier.html`), not `/lab` — `/lab` stays a pure front-end sandbox (decided 2026-07-04).

---

## 1. Problem Statement

The classifier is tuned by a human editing the prompt by hand, reading the misclassifications, and trying again. That manual loop is exactly the kind of iterate-against-a-signal work an agent can run on its own. This feature replaces the human in that loop with an **autonomous agent** that reads the eval's failures, revises the classifier prompt, re-scores, and repeats until an explicit stop condition fires.

Two aims, in priority order:

1. **Demonstrate loop engineering** — a legible, autonomous loop with a real feedback signal, an explicit done-signal, and an honest guard against gaming the metric. This is the deliverable; the artifact is the point.
2. **Possibly improve the prompt** — if the loop raises classification quality, report it. If it does not (the ceiling here is label ambiguity, not model horsepower), report *that*, honestly. Improvement is a result, never a gate (see §9).

---

## 2. Goals

| # | Goal |
|---|------|
| G1 | An agent optimizes the classifier prompt against the existing eval with **zero human input mid-run** — the agent decides when to stop. |
| G2 | The loop's design is **legible in under 5 minutes**: a reader can name the feedback signal, the done-condition, and the overfitting guard. |
| G3 | The **overfitting / Goodhart story** is told honestly — a held-out set the loop never sees, both numbers reported every iteration. |
| G4 | One artifact spans **backend (the loop) + frontend (a recorded-replay view on the project page)**. |
| G5 | *(Upside)* Report a measurable accuracy delta across iterations, in whichever direction it lands. |

---

## 3. Non-Goals

These are explicitly out of scope. Each has a reason, to prevent scope creep during build.

- **The agent-driven ML loop (rung 2).** A separate future spec. Rung 1 must teach us what rung 2 should be. *(Why: don't spec the harder loop before the simple one reveals its shape.)*
- **Live / on-demand execution on the page.** Recorded replay only. *(Why: live compute means hosting + per-visit token cost + can fail in front of a reviewer.)*
- **Beating the LLM, or any target accuracy as a release gate.** *(Why: the ceiling is label ambiguity — an outcome we cannot control. Gating "done" on it pressures us to game the eval, the exact failure this artifact exists to expose.)*
- **Deploying the optimized prompt into the live classifier.** This is a measurement + demonstration experiment, not a production swap. *(Mirrors the master PRD's stance.)*
- **New data labeling.** Reuse `data/synthetic_articles.csv` (300) and `data/gold/gold.csv` (the real gold set).
- **Changing the label schema or output contract.** Keeps this a MINOR, not a MAJOR.

---

## 4. Users

Personal portfolio project. Audience:

- **The author** — building the loop and learning loop-engineering design.
- **Technical reviewers** — skeptical senior engineers judging whether the author can design an autonomous system, not just prompt one.

No end-users, no SLA, no deployment target.

---

## 5. How It Works

### 5.1 The loop

```
  ┌─ start prompt ─┐
  │                ▼
  │   run classifier on set A ──► score on A (signal the agent reads)
  │                ▼
  │   read failures from A: misclassified examples + confusion stats
  │                ▼
  │   agent proposes a revised prompt (+ rationale)
  │                ▼
  │   re-score on A and on B; log everything
  │                ▼
  └── done-signal? ── no ──┘     yes ──► stop, emit run log
```

The agent's job is **error-driven**: it reads *why* the classifier failed and edits the prompt to address it. That qualitative judgment is what earns it a place over a mechanical hyperparameter sweep.

### 5.2 The 3-way split (the overfitting guard)

| Set | Source | Size | Role | Agent sees it? |
|-----|--------|------|------|----------------|
| **A — optimize** | `data/synthetic_articles.csv` | ~210 | The agent reads *these* failures and edits the prompt to fix them. | Yes (failures + confusion stats) |
| **B — validation** | `data/synthetic_articles.csv` | ~90 | Drives the done-signal (plateau / threshold). Keeps stop-detection honest. | No — never in the agent's context |
| **C — test** | `data/gold/gold.csv` (real, human-labeled) | n≈54 | The honest generalization number. Reported only; never used for any decision. | No |

**Two overfitting signals fall out of this, both shown on the replay:**
- **A-vs-B gap** = the prompt memorizing synthetic quirks.
- **B-vs-C gap** = the synthetic→real domain gap (the same limitation the master PRD's "circular eval" note already documents).

The leak this prevents: optimizing *and* measuring the done-signal on the same set makes plateau detection optimistically biased. B exists to break that.

**Region guardrail on C (added 2026-07-19, after `v3.0.0` shipped the `region` axis — [ADR-014](../../decisions/014-region-field-design.md)).** This spec was written against a two-axis classifier. The shipped classifier has three, and the proposer rewrites the *whole* system prompt — including a ~130-line region rubric this loop never optimizes and must not damage. The rubric is not separable from the rest of the prompt (all 25 worked examples carry three labels, and the tie-breaking list's clause (4) is region), so it cannot be withheld from the proposer; the defense is instead:

| Layer | What it does |
|---|---|
| **Freeze instruction** in `OPTIMIZER_SYSTEM_PROMPT` | Tells the proposer the classifier has three axes and names the four places region material lives, to be reproduced verbatim. |
| **Structural check, offline** (added 2026-07-19) | `region_rubric_violations()` compares the proposal against the prompt it was handed, before any scoring call: the `Region rules:` block must survive byte for byte, and no region label may appear *fewer* times than it did (which catches a region dropped from a worked example, outside the block). A violation retries the proposer; if every attempt mangles it, `propose()` raises `ProposalError` and the run stops. |
| **`region_guardrail` score on C** | Region macro-F1 + accuracy, computed on split C each iteration (`region_guardrail()` in `src/optimize.py`), written to the run log's `region_guardrail` field and printed on the console line. |

**The two layers do different jobs, and the order matters.** The structural check is
deterministic, free, and fires the instant the proposal returns — it catches deletion,
rewording, and dropped example labels before a scoring pass spends ~350 API calls. The
guardrail score catches what a string comparison cannot: a rubric that is textually intact
but whose surrounding prompt changes shifted region behavior anyway. Detection alone was the
first design; enforcement was added because the cheap check makes the expensive one a
backstop rather than the only line.

The structural check is deliberately conservative in one direction: it compares label counts
with *fewer*, not *different*, so a legitimate category-only edit that happens to add an
example mentioning a theater does not trip it. A guard that cries wolf on valid work gets
disabled.

The guardrail is **reported, never optimized** — the same standing rule that governs C itself. It is not in `scores`, not in `b_f1_history`, not read by `check_done_signal` or `select_best_iteration`. Wiring it into any of those would make C an optimization target and destroy the honest generalization number this whole section exists to protect.

It is scored on **C only** because `data/synthetic_articles.csv` (the source of A and B) has no `region` column, so region is not scoreable on the synthetic splits at all. Adding one would mean a fresh labeling pass — deliberately not done here; the gold set's real region labels are the guardrail's basis.

### 5.3 Feedback to the agent

Each iteration the agent receives, **computed on set A only**:
- Up to ~10–15 **raw misclassified examples** (`text`, true label, predicted label) for qualitative texture.
- **Confusion-matrix stats** (`confusion_matrix` from `src/eval.py`) showing where it systematically fails, e.g. `industry → procurement ×8`.

B and C stay blind so their scores remain trustworthy.

### 5.4 Done-signal

Stop on the **first** of:
- **Threshold** — primary metric on B reaches a configured target, or
- **Plateau** — no improvement on **B** for **N=3** consecutive iterations, or
- **Budget** — token budget or hard iteration cap reached.

The fired condition is recorded.

**Operational safety stop (outside the three above):** if the optimizer model's
`propose_revision` call cannot be turned into a usable prompt after retrying (e.g.
persistent truncation at `max_tokens`, missing a required field), the run stops with
`done_signal: "proposer_failed"` and reports the best iteration found so far, rather
than crashing an unattended run and losing every already-paid iteration. This is not
one of the three algorithmic stop conditions above — no threshold/plateau/budget logic
fired — it is a hardening measure for a live-observed failure mode (`src/optimize.py`'s
`AnthropicBackend.propose()` and its `ProposalError`).

### 5.5 Primary metric

**Macro-F1 on `category`**, computed via `macro_average(compute_metrics(...))` from `src/eval.py` — the repo's stated honest single number for an imbalanced problem. `operational_domain` is tracked and reported but `category` macro-F1 drives the done-signal. *(Confirm-point — see §13.)*

---

## 6. Functional Requirements

### 6.1 Must-Have (P0)

| ID | Requirement | Acceptance (Given/When/Then) |
|----|-------------|------------------------------|
| F1 | **Parameterized classify.** `classify()` accepts a custom prompt so the loop can vary it. | *Given* a prompt argument, *when* `classify()` runs, *then* it uses that prompt and the public default behavior is unchanged. |
| F2 | **The loop.** Agent runs classify on A → reads failures → proposes a revised prompt → re-scores. | *Given* a start prompt, *when* the loop runs, *then* it completes ≥2 full iterations with no human input. |
| F3 | **Two-set scoring.** Score A and B each iteration; C scored for reporting; B/C never enter the agent's context. | *Given* any iteration, *then* A and B scores are logged and the held-out sets never appear in the agent prompt. |
| F4 | **Explicit done-signal.** Threshold OR plateau-on-B (N=3) OR budget; record which fired. | *Given* a finished run, *then* the log names the exact stop condition. |
| F5 | **Run log.** Each iteration persisted as structured data (see §8); the run reconstructs from the log alone. | *Given* a completed run, *then* the replay renders entirely from the log. |
| F6 | **Recorded-replay view on the project page.** Step-through render of the log: prompt diffs, A/B/C curves, done-signal. | *Given* a published run, *when* a visitor opens the page, *then* it replays with no live compute. |
| F7 | **Honest writeup** on the page: design (signal/done/guard) + Goodhart explanation + result with the ceiling caveat. | *Given* a fresh reader, *then* they can restate the three design elements. |
| F8 | **Fail-safe bounds.** Hard iteration cap + token budget; partial progress persisted. | *Given* a runaway run, *then* it halts at the cap with the log intact. |

### 6.2 Nice-to-Have (P1)

- Side-by-side **prompt diff** per iteration.
- **A/B/C curves plotted** so the overfitting gaps are *visible*, not just tabulated.
- **"Why it stopped"** annotation naming the fired condition.
- **Cost/latency note** (loop's token spend).

### 6.3 Future Considerations (P2)

- **Rung 2** (agent-driven ML loop) reuses the **same run-log schema + replay player**.
- Optional **live "run it yourself"** button (hybrid showcase).
- **Scale C with the validated Opus judge** (ties to v2.1.0) to shrink the held-out noise floor.
- **Keep-best / revert-on-regression proposer policy.** The loop proposes each revision from the *previous* iteration's prompt (`src/optimize.py:1321`, `prompt = proposal.revised_prompt`), with no ratchet back to the best-scoring prompt so far — a regression is carried forward and the next proposal builds on the worse prompt. Adopting a "keep the best-so-far and propose from it, or revert when B drops past a threshold" policy would make extra `--token-budget` productive: more iterations would extend a climb instead of prolonging a random walk. See the matching limitation in §10.

---

## 7. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| N1 | Reuse `src/eval.py` metric functions (`compute_metrics`, `macro_average`, `confusion_matrix`) — no metric reimplementation, no sklearn. |
| N2 | Optimizer model: **claude-sonnet-4-6** (the SYS-002 / repo default). The loop doubles as an A/B harness to later test whether Opus pays. |
| N3 | API key from environment; never hardcoded. |
| N4 | Run is resume-safe (the existing eval pattern: append per-step, crash costs ≤1 step). |
| N5 | Output contract `{category, operational_domain}` unchanged. |

---

## 8. Run-Log Schema

The contract consumed by **both** the replay player and rung 2.

Per iteration:
```
iteration:        int
prompt:           full text
prompt_diff:      unified diff vs previous iteration
scores:           { A: {macro_f1, accuracy}, B: {...}, C: {...}, per_class_f1: {...} }
failures_read:    [ { id, text_snippet, true_label, predicted_label } ]   # from A only
confusion_stats:  { ... }                                                 # from A only
agent_rationale:  natural-language reasoning for the edit
edit_summary:     one-line "what changed"
tokens_spent:     int
done_signal:      null, or which condition fired (final iteration only)
region_guardrail: { macro_f1, accuracy, per_class_f1 } on C, or null   # added 2026-07-19
```
`region_guardrail` is a **sibling of `scores`, not a member of it** — `scores` holds the metrics the loop optimizes and reads; this is a read-only damage detector for an axis it must not break (§5.2). Keeping it out also leaves A/B/C the same shape for existing readers. `null` means "not measured", never "measured and zero".
Run-level metadata:
```
model · token_budget · iteration_cap · split_hashes · start_prompt · timestamp
```
`agent_rationale` + `edit_summary` are what make the replay tell a story rather than just show numbers climbing.

---

## 9. Success Criteria

Adapted from the usual leading/lagging frame — this is a portfolio artifact, not a product with a user base.

**Floor — Definition of Done (fully in our control):**
- [ ] Loop runs end-to-end, zero mid-run input, stops on a recorded done-signal.
- [ ] The project-page replay makes feedback signal + done-condition + overfitting guard legible (a fresh reader restates all three).
- [ ] Held-out C score logged beside A and B every iteration.

**Upside — reported result + stretch (never a gate):**
- Macro-F1 delta on A across the run (report whatever it is).
- Macro-F1 delta on C — the honest number; **the gap between the A and C deltas *is* the overfitting measurement.**
- *Stretch:* C improves without the A-vs-C gap blowing out (genuine generalization, not memorization).

---

## 10. Known Limitations & Risks

- **Goodhart / reward hacking.** A loop optimizing against a metric will game it. This is mitigated, measured, and reported — not hidden. It is the centerpiece of the writeup.
- **n≈54 noise floor on C.** The CLAUDE.md already frets about this; small C means its deltas are noisy. The done-signal therefore rides **B** (larger, lower-variance); C is read directionally. v2.1.0 (scale the gold set with the validated judge) would later strengthen C.
- **`classify()` refactor (F1) is the build linchpin.** The current signature does not obviously accept a prompt. First Phase 1 task is confirming and making this change without disturbing the public default behavior or the wire contract pinned in the tests.
- **Synthetic-only optimization.** Optimizing on synthetic and testing on real gold means the loop could learn synthetic-specific phrasing. That is precisely the B-vs-C gap we measure and report.
- **No ratchet: the loop hill-climbs from the last prompt, not the best.** Each proposal is generated from the previous iteration's prompt with no revert-to-best (`src/optimize.py:1320-1321`), so a bad proposal is compounded rather than discarded. Observed 2026-07-11 (pre-#69, on `claude-sonnet-4-6`): two runs at identical seed/split/config diverged sharply — one climbed B to 0.907 and stopped on `threshold`; the other peaked at 0.858, regressed to 0.841, and stopped on `budget_tokens`. Consequence: raising `--token-budget` buys more iterations, not a better result — it samples the weakly-upward random walk longer, it does not steer it. Candidate fix tracked in §6.3.

---

## 11. Versioning & Sequencing

- **Bump:** new **MINOR** (`v2.x.0`). Additive capability; the output contract is untouched, so by the repo's semver rule it cannot be a MAJOR. PATCH resets to 0.
- **Proposed sequence: after v2.1.0.** Two reasons: (1) the repo's "earn the right to spend by measuring first" principle, and (2) v2.1.0 shrinks the n≈54 noise floor that this loop's honest C-number depends on. It does not block the build — only the *trustworthiness* of C benefits from waiting.
- **Roadmap wiring:** adding a row to the CLAUDE.md versioning table is a separate, single-hand edit (roadmap is a shared/aggregated surface) — do it once, when this is scheduled, not in this spec branch.

---

## 12. Showcase & Cascade

- **Showcase:** recorded replay on the **classifier's project page** (`/projects/defense-news-classifier.html`), **step-through-on-click** for v1 (auto-play is P1). Backend (loop) + frontend (player) in one artifact. `/lab` is **not** the home — it stays a pure front-end sandbox (decided 2026-07-04); the player's front-end technique may earn a `/lab` learning-log entry, but the demo lives on the project page.
- **Cascade (one body of work, transformed per surface):**
  - **This repo** — the loop code, this spec, ADR 005, the run log (ground truth).
  - **architecture repo** — the cross-repo "how we build loop demos" pattern + portal link (SYS layer).
  - **portfolio project page** — the recorded artifact + a Decision→Why→Tradeoff writeup (outward showcase).
  - **learning-notes** — concept notes (*loop engineering*, *Goodhart in eval-driven optimization*, *held-out sets*), concept-first, not a project changelog.
  - Aggregated surfaces (portal, portfolio nav, learning-notes index/map) are wired by a **single integrator**, once, after content lands.

---

## 13. Open Questions

Most design questions are resolved (see §5–§9). Remaining:

- **[Eng]** `classify()` prompt-parameterization (F1): confirm the cleanest refactor that leaves the pinned wire contract green. *(verify first in Phase 1)*
- **[Eng]** Run-log persistence format: JSONL per run under `evals/`? Confirm location + naming alongside the existing `evals/` artifacts.
- **[Scope]** Primary metric = `category` macro-F1 (§5.5). Confirm, vs a combined category+domain score. *(Partly answered 2026-07-19: whatever the primary metric ends up being, the third axis `region` is **out** of it. `v3.0.0` made the classifier three-axis, and region is now tracked as a held-out **guardrail** on split C, not a target — see §5.2. Folding region into a combined score would point the optimizer at C, which the whole 3-way split exists to prevent. The category-vs-category+domain question itself is still open.)*
- **[Data]** Exact A/B split ratio (proposed ~210/90) and whether the split is seeded/recorded for reproducibility (`split_hashes`).
- **[Design]** Project-page replay: confirm step-through-on-click for v1, auto-play deferred to P1.
