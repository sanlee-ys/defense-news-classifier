# Pre-registration: the loop-candidate category clauses, measured at power

**Status:** Registered 2026-08-23, before any candidate arm was run.
**Harness:** `src/loop_candidate_eval.py` (guards enforce everything stated here).
**This document is canonical for the decision rule.** The report restates it; the
report does not redefine it.

## 1. What is under test

The Ralph outer loop's second live run (2026-08-23, ADR-026/ADR-027; log
`evals/loop/run_20260823T182804Z.jsonl`, branch `loop/prompt-optimize-2`, commit
`951aa83`) accepted two additions to the category rubric:

1. **procurement vs technology:** a system being marketed, unveiled, or offered
   for sale is technology; procurement needs an actual buyer, award, or contract
   named in the story.
2. **industry vs technology:** a partnership/teaming/MoU story is industry only
   when the arrangement's formation is the news; parties jointly demonstrating or
   operating a system is technology.

The candidate prompt is the live `SYSTEM_PROMPT` plus these two clauses, composed
at run time and pinned by digest to
`7386953ca9365855c06866551b394ca620b69722b9ecf298cde4c89118a7ea32` — the exact
prompt the loop measured. `classify.SYSTEM_PROMPT` never carries the clauses
during this experiment; no branch does.

**Why the loop's own numbers cannot decide this.** Best-by-B was B 0.868→0.974
(+0.106), but A and B are judge-labeled *synthetic* text — the loop may have
learned the synthetic generator's dialect. Held-out C moved 0.914→0.925, but
+0.011 at n=54 is half a row. The loop produced a candidate; it did not produce
evidence.

## 2. The arms and the ruler

| Piece | Source | Spend |
|---|---|---|
| Baseline arm | `evals/region_clause_candidate.csv` + `evals/region_clause_ext_candidate.csv` — the shipped prompt's (`b0202d06…`) predictions over the combined scale set, paid for by ADR-023/ADR-024 | none (frozen; sidecars checked against the live prompt) |
| Answer key | `evals/scale_predictions_v3.csv` + `evals/scale_ext_predictions.csv` — Opus judge labels, all three axes | none (frozen) |
| Candidate arm | new: `evals/loop_candidate_scale.csv` | ~600 workhorse calls |
| Gold arm (rule 3) | new: `evals/loop_candidate_gold.csv` vs the frozen human labels | 54 workhorse calls, zero judge calls |

Effective n after exact-duplicate removal: **595**. The key is the v3.0.0-era
judge configuration (`a59689e8…`). It is a fixed ruler shared by both arms, so
the paired lift is internally consistent; the category axis is untouched by the
ADR-024 region clause. Absolute accuracies inherit the key's documented
self-inconsistencies (ADR-023 §2.1) — the paired lift is the finding.

## 3. Design power (rule 0), stated before any data

Computed by `src/mcnemar_power.py` (exact two-sided McNemar, alpha 0.05) at
n=595. There is no prior discordant structure on real text for this candidate,
so these are a registered sensitivity band, not an anchor. Baseline category
agreement with the key is 94.1% (35 misses in 595), so the candidate's headroom
is real but bounded.

| true net lift | discordant rate | power at n=595 | n for 80% power |
|---|---|---|---|
| +1% | 3.5% | 0.19 | 2 892 |
| +1% | 5%   | 0.14 | 4 086 |
| +2% | 3.5% | 0.70 | 735 |
| +2% | 5%   | 0.52 | 1 035 |
| +3% | 3.5% | 0.99 | 309 |
| +3% | 5%   | 0.90 | 463 |

**What this buys and what it does not.** This design decides a ≥3% effect. If
the true effect is the ~+1% the gold arm hinted at, the run will most likely
return null — and that null means "no effect ≥~2–3% exists", not "no effect
exists". Detecting +1% would need roughly 3 000–4 000 pairs (a new corpus
collection, ~5× this cost); that is a separate decision and a separate
registration.

**Rule 0 (registered):** the effective n is fixed at 595 (the full paid reuse;
the harness refuses below it). If the result is null, the verdict row records it
with this table, and **no extension run may be started in response to the
observed p-value without a new pre-registration** — chasing n after seeing data
is the outcome-switching ADR-023 exists to warn about.

## 4. The decision rule (registered)

Adoption requires **all** of:

- **Rule 1 (primary):** category accuracy vs the judge key, candidate over
  baseline, exact McNemar p < 0.05 over all category-discordant pairs, with the
  lift positive.
- **Rule 2 (guardrails):** neither `operational_domain` nor `region` is harmed
  at p < 0.05 (vs the judge key, same pairing). A significant harm on either
  kills adoption regardless of rule 1 — ADR-020 is the measured precedent for
  why. A significant *improvement* on a guardrail is recorded, not banked.
- **Rule 3 (gold non-regression, run only if rules 1–2 pass):** human-graded
  gold category accuracy under the candidate ≥ **94.4%** (the published v3.2.1
  figure). Domain and region on gold are context, not gates. The second half —
  no gated `thresholds.toml` floor breached — is an adoption-time question by
  construction: this arm cannot touch the published record.
- **Rule 4 (harness health):** both arms complete (exactly one row per snippet;
  sentinel rows for truncated/refused/invalid responses per ADR-021), pairing
  clean, every excluded row named in the report. A lift computed over a harness
  that dropped rows is not a finding.

A marginal result is a **decline** — p ≥ 0.05 is p ≥ 0.05, per ADR-023, whose
verdict was honored at p=0.0522.

**On adoption:** the ADR-024 shape — the clauses enter `SYSTEM_PROMPT`
byte-identically, a full paid gold re-run regenerates the published record, all
floors as written, PATCH version, marker cascade per
`docs/v3.2.0-release-runbook.md`. **On decline:** a dated row in
`decisions/verdicts.md`; the loop's story records that its candidate was
measured and declined, which is the honest-ruler design working end to end.

## 5. Protocol (owner-driven; every `--run-*` spends)

From the repo root, in order:

```bash
uv run --env-file .env python src/loop_candidate_eval.py --run-candidate --batch
uv run python src/loop_candidate_eval.py --report
```

Cost: ~600 workhorse calls, ≈ $2.6 batch (≈ $5 synchronous without `--batch`).
The report is free and offline; it refuses on an incomplete arm, a digest
drift, or n < 595. Then, **only if rules 1 and 2 pass**:

```bash
uv run --env-file .env python src/loop_candidate_eval.py --run-gold
uv run python src/loop_candidate_eval.py --gold-report
```

Cost: 54 workhorse calls ≈ $0.32, zero judge calls. Truncated or refused rows
are recorded as sentinels and excluded from scoring (ADR-021) — six truncations
in run 2 are the measured reason the runners work this way.

## 6. What is never touched

`classify.SYSTEM_PROMPT`; both scale sets; the frozen key files and their
sidecars; the frozen baseline-arm files and their sidecars; the gold set; the
published gold record and `evals/metrics.json`; every `region_clause_*`
artifact. Everything this experiment writes is new and `loop_candidate_*`-named,
and the harness's write guards enforce the gold-side list mechanically.
