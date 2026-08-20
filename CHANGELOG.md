# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versions are tagged by milestone; individual commits are noted where relevant.

---

## [Unreleased]

Work that landed after the `v3.2.1` tag. No version number is claimed yet. The shipped
classifier is unchanged: `src/classify.py` carries the same `SYSTEM_PROMPT`, and
`evals/metrics.json` carries the same published numbers.

### Added
- **A Ralph-style outer loop around the classifier prompt, graded on a split the agent
  never sees** ([ADR-026](decisions/archive/026-ralph-loop-honest-ruler.md), `loop/loop.ps1`,
  `loop/PROMPT_optimize.md`, `scripts/loop_metrics.py`, `loop/README.md`). The agent reads
  split A only. Split B is the acceptance gate, and an iteration commits only if B does not
  regress against the best accepted B. Split C decides nothing and is recorded as the honest
  final number. The splits come from the same `src/optimize.py` code, so both loops measure
  the same rows. The ledger that carries B and C is written outside the git worktree during a
  run, then copied into `evals/loop/` after the last iteration. The verdict the agent reads
  names the gate that fired and never quotes a number.

  **This is unmeasured, and deliberately so.** ADR-026 ships the harness and a smoke test,
  and it makes no claim that the loop improves the classifier prompt. The smoke test
  exercised the mechanics against the zero-API mock backend. ~~**No live optimization run has
  been made**~~ — **superseded 2026-08-20: the first live run has now been made, and its
  result was rejected.** See the Fixed entry below and the ADR-026 amendment. The prompt in
  `src/classify.py` is still unchanged. What the hidden split buys
  is stated as a bound, not as a result: the metric is not *convenient* to the agent. ADR-026
  cites this repo's own measured Goodhart catch (ADR-018, B up 6.0 points while held-out C
  fell 8.6) as the reason the ruler is hidden at all.

  All seven agent-ops ADR-016 rails live at the call site in `loop/loop.ps1`, not in the
  prompt: an iteration cap, a budget cap, a time cap, stuck detection that halts on three
  identical failures and writes `loop/state/stuck.json`, worktree isolation, pushes to the
  loop branch only, and a refusal on any permission-bypass flag. The blast radius is declared
  before the first iteration in `loop/blast-radius.txt`. **The loop merges nothing.** A second
  gate rejects any change to the frozen region rubric, compared byte for byte before scoring:
  ADR-024 adopted that clause on measured evidence, so a loop that optimizes `category` may
  not rewrite it. The loop therefore cannot improve `region` by construction, which ADR-026
  records as an accepted capability cost.
- **An agent task lane: dispatch a scoped task, get back a draft PR**
  ([ADR-025](decisions/archive/025-agent-task-lane.md), `.github/workflows/agent-task.yml`). This is
  the proposing counterpart to ADR-016's advisory review lane, assembled per agent-ops
  `conventions/agent-in-ci.md`. The lane is `workflow_dispatch` only and owner-gated. Its
  `contents:write` permission is bounded to proposal branches by the protection rules on
  `main`. The redline guards are fetched and wired before the agent's first tool call, and a
  failed fetch fails the job. The deterministic verifier is deliberately absent from the
  workflow: `tests.yml`, `evals.yml` and CodeQL gate the proposal PR the same way they gate
  any other PR. Rejected alternatives are recorded in ADR-025.
- **An injection harness for the L4 work graph, plus its pre-registration and power
  analysis** ([spec](docs/specs/l4-context-loss-injection.md), `src/l4_inject.py`,
  `tests/test_l4_inject.py`). SYS-022 Amendment 1 and the ladder spec both name the same
  asymmetry: ADR-020 built three governance primitives for the L4 work graph, all three guard
  against a bad critic, and nothing validates upstream state. This instrument measures that
  bill and nothing more. `InjectingBackend` satisfies the `L4Backend` Protocol structurally
  and corrupts the *consumer's argument*, never a producer's return value, so on
  `classify->critic` the critic reviews a corrupted label while the label that ships is
  untouched. There are zero edits to `src/l4_pipeline.py`.

  **No arm has been run and no API budget was spent.** Scoring is a rate over a five-way
  partition (CAUGHT, CONTAMINATED, ABSORBED, CORRECTED, CRASHED). Propagation distance is
  retired as the headline, because hop count is bounded by graph depth and depth is a free
  parameter. Ground truth is two references: the 54-row human gold answers "is it wrong", and
  the paired control plus McNemar answers "did the drop cause it". The spec states plainly
  that there is no gold for intermediate node output. The cell matrix is asserted against the
  spec file by a test, so post-hoc cell selection cannot happen quietly.

### Changed
- **The decision log is split by genre: 26 ADRs become 11 live ADRs, a verdict log and one
  current agent-practice document** (`decisions/README.md`, `decisions/verdicts.md`,
  `decisions/agent-practice.md`, `decisions/archive/`, `CLAUDE.md`). The set had reached 26
  numbered ADRs of which only 11 decided anything still in force. Ten were experiment
  verdicts, which accumulate and decide nothing by themselves. Five were overlapping
  statements of agent authority written between 2026-06-27 and 2026-08-11 at different levels
  of maturity, two of which stated the same rule in different words.

  **Nothing was deleted.** All fifteen superseded ADRs keep their full original text under
  `decisions/archive/`, every number ever issued is mapped in the index, and all 311 relative
  links in the repository resolve.

  `decisions/verdicts.md` is now the log for measured results: one dated row per experiment,
  with the number and the call. A new experiment adds a row and does not take an ADR number.
  `decisions/agent-practice.md` states the current rule for agent authority in six numbered
  points, plus what a hidden metric does not buy, plus a table of how the rule got there. The
  progression is the argument for keeping it current rather than immutable: what changed each
  time was the capability of the proposer, and the guard had to change with it.

  Also fixed in passing, because the restructure surfaced them: ADR-025 was absent from the
  index between 2026-08-11 and 2026-08-20, and ADR-001's title still names
  `claude-sonnet-4-6` while the workhorse is `claude-sonnet-5`. The stale title is now
  flagged in the index rather than silently wrong.

### Fixed
- **42 of the 300 synthetic labels contradicted the classifier's own convention, and the
  first live outer-loop run learned the defect** (`data/synthetic_articles.csv`,
  [ADR-026](decisions/archive/026-ralph-loop-honest-ruler.md) amendment,
  [ADR-003](decisions/003-synthetic-data-only.md), `docs/notes/project-notes.md`). A full
  read of all 300 rows found three defect classes, every one of them the documented
  convention applied backwards: 25 `industry` rows and 8 `technology` rows are government
  contract awards, which the prompt calls the buyer's story and labels `procurement`; 9
  `industry` rows are product unveilings or test milestones, which the prompt sends to
  `technology`. `procurement`, `operations` and `policy` were clean across all 180 rows.
  Counts move from a uniform 60 per class to procurement 93, technology 61, operations 60,
  policy 60, industry 26. Macro-F1 already averages per class, so the imbalance is carried
  rather than papered over, and ADR-003's "perfectly balanced dataset" claim is corrected
  in place.

  Two duplicate stories carrying opposite labels are the proof: rows 2 and 290 are both
  "Lockheed Martin has been awarded a $N contract by the U.S. [Air Force / Department of
  Defense]", and rows 41 and 221 are both the DGA awarding Thales Alenia Space the Syracuse
  5 contract. No surface rule separates either pair.

  **The defect is why `loop/prompt-optimize` is not merged.** The first live run gained
  +0.132 macro-F1 on split A and +0.131 on the hidden gate B while the real gold set C did
  not move at all (0.936 to 0.936). A and B are a 70/30 shuffle of the same synthetic pool,
  so they share the defect; C carries the correct convention and holds none of the affected
  rows. The loop's new rubric labeled `industry` whenever a named company led the sentence,
  which reverses the convention in `src/classify.py`. **Every A/B figure computed before
  2026-08-20 rests on the uncorrected labels.** Gold-set and scale-eval figures use
  different data and are unaffected.

### Changed
- **The L4 injection pre-registration is tiered, amended after its own power table and
  before the first paid call** (`docs/specs/l4-context-loss-injection.md`,
  `src/l4_inject.py`). Eleven co-equal live cells forced a choice between an uncorrected
  alpha carrying a family-wise error rate near 43% and a Bonferroni alpha needing 33 points
  at n=44. Three changes replace that: one confirmatory test rather than eleven
  (`triage->critic` on `critic`, `region_evidence`, `omit`, at an uncorrected alpha of 0.05),
  which drops the minimum detectable rate from 33 points to 24; the three backward-edge cells
  become **descriptive** because they fire only on rows that bounce (n is about 25, where
  even the uncorrected minimum is 36 points), so they report rates and no comparative claims;
  and ABSORBED becomes the headline with CONTAMINATED as the attribution number, because a
  proportion needs no significance test and its Wilson interval is usable at n=44 near the
  extremes. The Bonferroni figure is still printed, relabelled as the cost the tiering
  avoids rather than a threshold in force, and a test pins that wording.
- **The ladder spec applies SYS-022 claim discipline to L4** (`docs/specs/autonomy-ladder.md`).
  L4 is this system's one built-and-measured work graph, and SYS-022 Amendment 1 says the
  unqualified "does graph engineering" claim is not available. Section 4 now names the split
  in place. Mechanized: static routing, real observability through an append-only per-run
  audit JSONL, and code-enforced node policy. Never had: dynamic node spawning and
  cross-process state. The honest half is the gap the measurement exposed, and the section
  closes with why this is a re-description of L4 rather than a fifth level.
- **The README is cut to an operator front door** (`README.md`, 806 lines removed). It keeps
  the badges, the generated gold-metrics block, the run commands, and the measured tables.
  The v1-to-v3 narrative moves to the ADRs and the case study that already carry it.
- **The classical bake-off LLM figures are frozen as a dated comparison, not live gold**
  (`README.md`, `scripts/gen_readme_metrics.py`). The classical baseline table carried
  `metric:category_accuracy` and `metric:domain_accuracy` markers at 92.6%, while current
  gold reads 94.4% and 98.1%. A live marker harness would overwrite a historical paired
  comparison, and a reader could confuse bake-off-era LLM figures with the v3.2.1 headline
  table. The markers are removed, the column is labelled as the bake-off snapshot, and the
  freeze rule is stated on the ADR-022 precedent. The generated gold-metrics block is
  untouched.

---

## [3.2.1] — 2026-08-03

### Fixed
- **The `global`-boundary prompt clause — re-run at adequate power, and adopted**
  ([ADR-024](decisions/archive/024-global-boundary-clause-adopted.md),
  [spec](docs/specs/global-boundary-clause-rerun.md), `src/region_clause_rerun.py`).
  ADR-023 measured this clause and reverted it at **p=0.0522** against a
  pre-registered p<0.05. It then named the one thing that would change the answer —
  a higher-power ruler — and that condition has now been met. The **same clause**,
  byte-identical and pinned by `sha256` to the fingerprint the paid ADR-023 run
  recorded, was re-registered and re-run against an extended ruler at **effective
  n=595** (295 frozen rows reused, 300 new, 5 exact duplicates excluded before
  anything was graded).

  **All four pre-registered rules passed.** Region **89.9% → 94.1%** (+4.2),
  discordants 35/10, **McNemar p=0.0002**, at a design power of **0.837** — computed
  before the numbers, not after. Guardrails clean: category flat (p=0.4807) and
  operational domain *improved* +3.5% (p=0.0011), so the kill condition never fired.
  Harness health clean on all three axes, 595 groups / 595 pairs / 595 eligible. The
  human-graded gold arm cleared its non-regression bar at **92.6%** against 87.0%.
  Named `global` pulls fixed: **20 of 32** on the scale ruler, 6 of 7 on the human one.

  **The honest lesson is about the first run's design, not its verdict.**
  `src/mcnemar_power.py` shows ADR-023 ran at about **49% power** against the effect
  it observed — a coin flip on whether it could detect its own effect. So that
  finding was *underpowered*, not *refuted*; the rule was right and honoring it was
  right, and it is precisely because the threshold was not renegotiated in the moment
  that this adoption means anything. ADR-023 is amended with a dated **pointer**
  rather than rewritten — its body stands verbatim, correct on its date.

### Changed
- **`classify.SYSTEM_PROMPT` carries the clause**, inside the region-rules block
  immediately after the "concrete identifiable location" bullet (the placement is
  load-bearing: `l4_pipeline` and `optimize` both freeze that block). The shipped
  prompt fingerprint moves `a59689e8…` → **`b0202d06…`** — byte-for-byte the
  candidate arm that was measured, pinned by a test so what ships is the arm the
  595-row report describes rather than a retyping of it.
- **The published n=54 human-graded gold record was re-run under the adopted prompt**
  (workhorse *and* judge — `judge_region_agreement` is a gated floor and had to be
  re-measured, not inherited). **Region accuracy 87.0% → 94.4%**, category 92.6% →
  94.4%, operational domain 92.6% → 98.1%. **All eight gated floors pass as written;
  none was moved, waived, or added.** The floor with real authority here was
  `judge_region_agreement`, which fell 100.0% → **96.3%** against a 0.93 floor — 2
  judge-vs-human disagreements against a budget of 3. Expected, since the clause is
  now in the judge's prompt too, but it is the number that would have stopped the
  release.
- **First `metrics.json` change since v3.0.0 where gold values actually move**, so the
  published-marker cascade is real this time: architecture, portfolio, learning-notes
  and kb-agent all carry figures that had been stable across two releases.
- **The re-run harness goes dormant and says so.** Every run and report entry point in
  `src/region_clause_rerun.py` now refuses once the clause is in `SYSTEM_PROMPT`. Both
  arms of both rulers were bought against the pre-adoption baseline, which the tree no
  longer contains, so no honest comparison can be re-derived — and specifically,
  `--gold-report` would otherwise have compared the candidate arm against itself and
  printed a 0.0-point lift. The committed reports are frozen records, read rather than
  regenerated; guard coverage is preserved by a fixture that reconstructs the baseline
  and verifies it against the recorded digest.

### Added
- **The higher-power re-run of the `global`-boundary clause — pre-registered and
  run-ready, not yet run**
  ([spec](docs/specs/global-boundary-clause-rerun.md), `src/mcnemar_power.py`,
  `src/region_clause_rerun.py`, `scripts/extend_scale_set.py`). ADR-023 declined the
  clause at **p=0.0522** and named the one thing that would change the answer: a
  higher-power ruler. `src/mcnemar_power.py` turns that into arithmetic — exact
  two-sided McNemar power, computed through the repo's own `mcnemar_exact` rather than
  a normal approximation — and the answer is that **ADR-023 ran at ~49% power against
  the effect it observed**. That reframes the verdict without changing it: the rule was
  right to revert, *and* the design could never have decided either way. 80% power
  needs **n=545**, 90% needs **n=713**, and "just collect 300 more" buys 84% only if
  the true effect is exactly the observed one (58% at three-quarters of it) — so the
  target is ~730 effective pairs, and **n=545 is a floor enforced in code**, not
  printed.

  **Two design changes make this cheaper and safer than the round it repeats.** The
  clause is applied **at run time** from a source pinned by digest to the fingerprint
  the paid ADR-023 run recorded, so `classify.SYSTEM_PROMPT` is never edited: no
  expected-red CI, no provenance waiver, no revert to perform, and — load-bearing — the
  Opus judge still grades under the shipped prompt, which it must, because `classify()`
  defaults *both* models to `SYSTEM_PROMPT`. And the 295 rows already measured are
  **reused rather than re-bought**, guarded by both sidecars, so only new snippets are
  classified at 3 calls each. The extension is collected by importing
  `build_scale_set.py`'s own queries and filters (a copy could drift; an import cannot),
  with one documented deviation — the per-query keep cap rises — and one new exclusion
  that is the ADR-023 lesson: **exact-duplicate snippet text is dropped before anything
  is graded**, not after. Offline tests throughout; no live call was made building it.
- **The `global`-boundary prompt clause experiment — measured and reverted**
  ([ADR-023](decisions/archive/023-global-boundary-clause-verdict.md),
  [spec](docs/specs/global-boundary-clause.md), `src/region_clause_ab.py`). The region axis
  had one named, systematic error: answer-key `global` rows pulled to a specific region by
  inferring a theater from the US *actor* — 17 of 70 at n=300, **49% of every region
  disagreement** (ADR-022), and all seven region misses on the human-graded gold 54. A one-
  bullet prompt clause was the cheap alternative to ADR-020's declined critic, which fixed
  6 of the 7 at ~4× cost. The clause and its decision rule were **pre-registered in the spec
  before a single call was made**, then narrowed after an independent adversarial review
  returned FIX FIRST: the first draft would have removed the only region evidence from ~14
  currently-correct rows and contradicted two ratified conventions. Paired exact McNemar
  against the frozen ADR-022 judge key, duplicates dropped from the pairing (**effective
  n=295** — one duplicate pair carries two different answer-key labels on identical text),
  category and domain carried as **kill-condition guardrails** rather than as optional
  extras, because a region-only report would have scored ADR-020's critic a success.

  **Verdict (same day, 408 calls): MARGINAL → reverted.** Scale region **88.5% → 92.2%**,
  12 of 17 named pulls fixed against 7 correct rows dragged to `global`, net +11 rows,
  discordants 19/8 — at **McNemar p=0.0522**, missing the pre-registered p<0.05 by 0.0022.
  Guardrails clean (category p=0.75; domain *improved* +3.7%, p=0.0192, recorded as an
  unexplained secondary observation and explicitly not counted toward shipping). Gold arm,
  human-graded: region **87.0% → 94.4%**, all seven named misses fixed against three broken,
  `global` recall 1.000, every `thresholds.toml` floor clear. The rule's own text calls a
  marginal result a revert, and it was honored — a pre-registration that binds only when
  convenient is theater, and this repo's Goodhart lineage (rung 2's held-out C vetoing the
  loop's own best iteration; ADR-020's restraint-in-a-prompt failure) is the reason it was
  written down first. **The shipped classifier is unchanged** — `SYSTEM_PROMPT` still hashes
  to `a59689e8…`, no published number moves, no version bump. Records:
  `evals/region_clause_ab.txt`, `evals/region_clause_candidate.csv` (+ sidecar),
  `evals/region_clause_gold_candidate.csv`, `evals/region_clause_gold_eval.txt`. The harness
  stays dormant with its 51 tests as the reproducible record and as the ruler a higher-power
  re-run would reuse (the ADR-013/ADR-019 pattern); what would change the answer is a larger
  human-labeled key, parked as a condition rather than scheduled.

### Fixed
- **The re-run's step 5 would have deleted the published gold record, spent 108 calls,
  and measured the baseline** (`src/region_clause_rerun.py`,
  `docs/specs/global-boundary-clause-rerun.md`, `tests/test_region_clause_rerun.py`).
  The spec's step 5 said to run "ADR-023 spec §7 step 2 verbatim" — an instruction
  written for the ADR-023 design, where the clause lived inside `classify.SYSTEM_PROMPT`
  on a branch, so deleting `evals/gold_predictions_v3.csv` and re-running `gold_eval.py`
  really did measure the candidate. The spec's own §3 replaced that with **run-time**
  clause application and step 5 was never updated. On `main` it would have (a) deleted
  the published v3.2.0 gold record that markers in several repos hang off, restored only
  by a hand-typed `git checkout --` that an aborted run leaves unrun, (b) spent ~108
  calls, and (c) measured the **baseline** — `main`'s prompt carries no clause, and
  neither CLI had any way to point a gold pass at the clause-applied prompt.

  **A purpose-built gold arm replaces it: `--run-gold` / `--gold-report`.** The clause is
  composed through the same run-time mechanism and the same `sha256` pin to ADR-023's
  `b0202d06…` that `--run-candidate` uses, plus an assertion on the exact string going on
  the wire and a report-side refusal of any arm whose sidecar records the shipped prompt
  — so the pass cannot run under the shipped prompt at either end. `evals/metrics.json`,
  `evals/gold_predictions_v3.*`, `evals/gold_eval_v3.txt` and ADR-023's frozen gold arm
  are made **mechanically unwritable** (resolved-path comparison, not a naming
  convention), which is what deletes the undo line rather than rewording it. And the cost
  halves to **54 calls with zero judge calls**: rule 3's answer key is the frozen *human*
  labels, so the judge — a scalable stand-in for exactly those labels — answers no part
  of it. The report states rule 3's verdict against the pre-registered 87.0% bar with the
  per-claim fixed/broken ids, and says plainly that rule 3's "no gated floor breached"
  half is an **adoption-time** question the shipped prompt owns. **No pre-registered rule,
  threshold, or verdict wording changed** — the procedure was broken, not the bar.
- **`MIN_CACHEABLE_PREFIX_TOKENS` carried inferred floors that were both wrong, and the
  "caching is a no-op on the judge passes" claim rested on one of them** (`src/classify.py`,
  `scripts/cache_diagnostics.py`, `docs/specs/global-boundary-clause-rerun.md`). The table
  recorded `claude-sonnet-5: 2048` and `claude-opus-4-8: 4096`; re-fetched from
  [Anthropic's prompt-caching docs](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching)
  on 2026-08-02, **both are 1024**. The sonnet-5 entry was explicitly commented as
  *inferred* from a same-tier sibling, and that is the root cause worth naming: the floor
  does not track model tier or recency — the same page lists Opus 5 at 512, Opus 4.7 at
  2048, and Opus 4.6/4.5 and Haiku 4.5 at 4096 — so a per-model table is right in shape and
  can only be filled by transcription. A new test pins the three values against the
  published figures so the next drift fails CI instead of propagating.

  **The consequence is a retracted claim, not a code change.** No shipped behavior moves:
  `cacheable_prefix_gap()` already returned "clears the floor" for the workhorse, and the
  v2.3.0 live check (`cache_creation=2350` then `cache_read=2350`) had confirmed that
  empirically. What the stale 4096 produced was a *false negative on the judge*: the
  ~2425-token prefix looked incapable of caching on Opus 4.8, and the rerun spec had
  hardened that inference into "a measured no-op on the judge passes." It was never
  measured. The judge is not a distinct call shape — `gold_eval.py` reaches it via
  `classify_retry(..., JUDGE_MODEL)`, the same `cache_control`-marked system block with the
  model swapped — so with the real 1024 floor it should cache like the workhorse does.
  ADR-009's incidental "~2048" reference is left as-written: it is a correct-on-its-date
  record whose conclusion (caching carries over to the batch path) does not depend on the
  floor's value.

- **Judge-side caching confirmed live** (`src/classify.py`,
  `docs/specs/global-boundary-clause-rerun.md`). Running
  `scripts/cache_diagnostics.py --live --model claude-opus-4-8` on 2026-08-02 closed the
  question the entry above left open: `call 1: cache_creation=3625, cache_read=0` →
  `call 2: cache_creation=0, cache_read=3625`. **Prompt caching engages on the Opus
  judge.** The run is also a self-contained disproof of the stale floor — it cached at
  **3625 tokens, below the 4096** the old table claimed — so the correction stands on
  measurement, not only on the docs.

- **The "~2425-token cacheable prefix" figure was stale by a full minor version, and the
  first attempt to explain the discrepancy was wrong** (`src/classify.py`, both
  `docs/specs/global-boundary-clause*.md`). Measuring both models on 2026-08-02 gives
  **3764 tokens on Sonnet 5 and 3700 on Opus 4.8**. The ~2425 figure was recorded at
  **v2.1.0 (2026-07-17)** and obsoleted the next day by **v3.0.0**, which added the
  `region` label and its boundary rubric to `SYSTEM_PROMPT`; the prose was never updated
  and the number propagated for a fortnight.

  An intermediate revision of these notes explained the gap as a *tokenizer* difference —
  claiming the same prefix counted ~50% larger under Opus 4.8 than under Sonnet 5. That is
  refuted by the workhorse measurement: the two models differ by **64 tokens (~1.7%)**,
  ordinary variation. The real cause is simply that the prompt grew. The retraction is kept
  here rather than quietly edited away, because the failure repeated a pattern worth
  naming: the same fortnight produced an *inferred* cacheable floor and an
  *over-generalized* token count, both propagated as fact. **Prefix size tracks the prompt,
  so any prompt edit invalidates every quoted figure** — the code and specs now say to
  re-run `scripts/cache_diagnostics.py` rather than cite a number from prose.

  The rerun spec's cost table is deliberately **not** recomputed. All three of its rows —
  not just the judge — undersize input tokens by ~50%, while its no-cache-discount
  assumption is now measured false; the discount dominates, so the totals should come in
  under $5.75. A spend ceiling is more useful honest-and-high than re-derived from two
  estimates. What remains genuinely open is narrower than before: not *whether* the prefix
  caches, but what fraction of ~1300 dispatched calls hit it under the 5-minute TTL and
  Batches scheduling, which only the run itself can answer.

---

## [3.2.0] - 2026-08-02

Milestone: **the ruler shrinks.** The region axis had shipped with a single number — 87.0% on
n=54, a 95% Wilson interval **18 points wide** — inside which no future region change could be
told apart from noise. The scaled region eval grades 300 DVIDS snippets with the Opus judge
that validated at 100.0% region agreement against the human labels, and brings that interval
down to **7 points** ([ADR-022](decisions/archive/022-scaled-region-eval-verdict.md)).

This tag also releases everything accumulated since `v3.1.0`: the API error taxonomy and the
truncation assertion (ADR-021), the paired-comparison layer, the browser-portable ADR-017
baseline, the two provenance pins, and two CI lanes.

The shipped classifier is **unchanged** — same prompt (`SYSTEM_PROMPT` still hashes to
`a59689e8…`), same single call, same `{category, operational_domain, region}` contract — so
this is a MINOR: capability and measurement were added, nothing a caller relies on moved. The
gold numbers published in `evals/metrics.json` are still `v3.0.0`'s measurements, because the
thing they measure did not change; the only byte that moved in the artifact is `version`.

### Added
- **The scaled region eval, measured** ([ADR-022](decisions/archive/022-scaled-region-eval-verdict.md),
  [spec](docs/specs/scaled-region-eval.md), `src/scale_region_eval.py`) — 300 DVIDS snippets
  (`data/scale/scale_set.csv`, the same ids v2.1.0 used: reused rather than resampled, so every
  row lines up with the frozen v2 snapshot and the judge never grades its own validation data),
  workhorse `claude-sonnet-5`, answer key the `claude-opus-4-8` judge on the frozen
  configuration that cleared ADR-014's gate.

  **Region 88.3%, 95% CI [84.2%, 91.5%] (265/300), macro-F1 0.904**; category 91.7%
  [88.0%, 94.3%]; domain 89.3% [85.3%, 92.3%]. The deliverable is the interval, not the point
  estimate: 18 points wide at n=54, 7 at n=300, and 88.3% against the gold set's 87.0% is
  corroboration rather than a new headline.

  **The named `global` cluster is confirmed systematic.** On the gold 54, all seven region
  misses were `global` rows the model pulled to a specific region by inferring a theater from
  the US *actor*; seven rows could not separate a behavior from a run of luck. At n=300: 70
  answer-key `global` rows, **17 pulled to a region** (16 of them to `americas`), which is
  **49% of all 35 region disagreements**. That is the evidence a HANDOFF-job-2 prompt clause
  gets measured against, and the at-scale price comparison for ADR-020's declined critic — the
  clause itself is deliberately *not* implemented here, because measuring first is the method.

  Read **alongside** the human-graded n=54 figures, never instead of them: this is
  workhorse-vs-judge agreement, and the judge's measured disagreement with humans on region was
  0/54 — itself a wide interval. The report says so in its own header. Artifacts:
  [`evals/scale_eval_v3.txt`](evals/scale_eval_v3.txt), `evals/scale_predictions_v3.csv` (+ its
  provenance sidecar), `evals/scale_confusion_v3_region.csv`. **No threshold was added** —
  floors come from measured runs *with run-to-run noise under them* (ADR-007), and one pass
  cannot supply that; a scale run is a dated measurement, not a live gate.
- **A paired-comparison layer, with harness health reported separately** (`src/paired_compare.py`).
  Every A/B in this repo — ADR-012, ADR-013, ADR-017, ADR-019 — re-derived the same plumbing by
  hand, and the part that kept getting re-litigated was the bookkeeping, because a comparison
  that quietly drops rows reports a lift that never happened. Now: a deterministic group key
  that fails loud rather than merging two inputs into one "pair"; metrics computed only over
  pairs where **both** arms scored (a missing observation is never imputed and never zero, or an
  arm that crashes on the hard rows looks better the more it crashes); nothing eligible returns
  `None`, never `0.0`. Non-participating rows come back as diagnostics under their own heading,
  because "is this comparison trustworthy" is a different question from "what did it find". It
  is additive and reads already-materialized CSVs, so it cannot perturb a published number, and
  it independently reproduces the ADR-017 bake-off result as a test.
- **The ADR-017 classical baseline is now portable to the browser**, with a parity gate
  (`scripts/export_baseline.py`, `web/baseline_export.json`, `web/baseline_infer.js`,
  `scripts/generate_parity_fixture.py`, `scripts/parity_check.mjs`). The baseline is a
  TF-IDF vectorizer plus one logistic regression per axis — a linear model over a sparse
  bag of n-grams, which is small enough to ship as JSON and evaluate client-side with no
  server and no dependencies. The export fits the ADR-017 configuration on the ADR-017
  training data by calling `baseline_ml.fit_baseline` itself, so the two cannot drift.

  Nothing here re-measures anything: the published 72.2% / 66.7% figures remain the frozen
  record in `evals/baseline_eval.txt`, and the export reproduces that fit exactly (verified
  as a build check, not published as a new number). The risk this change actually carries is
  the hand-ported preprocessing — a JS reimplementation of sklearn's tokenize → stop-word →
  n-gram → idf → L2 pipeline fails *quietly*, returning a plausible label rather than the
  measured model's. So it is gated: `scripts/parity_check.mjs` (bare `node`, no npm) runs the
  module over 354 committed rows of sklearn's own predictions and decision scores and fails
  the build on any disagreement beyond 1e-6. The gate additionally asserts that the fixture
  exercises **every** vocabulary term, because the first draft — gold rows only — could be
  shown not to catch a perturbed coefficient on a term those 54 rows didn't contain.

### Changed
- **Two CI lanes.** The serving image is now **built and smoke-tested on `/health`** before
  merge (`.github/workflows/docker.yml`, path-filtered to `Dockerfile`,
  `requirements-api.txt`, `src/api.py`, `src/classify.py`) — before it, a base-image bump could
  go fully green without the shipped artifact ever being built. And the advisory review lane
  walked back to **on-demand only** ([ADR-016](decisions/archive/016-claude-code-action-pr-review.md)
  Amendment 1): the automatic `pull_request: [opened]` pass is gone, and the remaining gate was
  a fiction until it was fixed — supplying a `prompt:` puts the action in **agent mode**, which
  bypasses `@claude` mention checking entirely, so the effective trigger was *any* OWNER comment
  (`lgtm`, `merging`), each one spending a billed review. It now requires the phrase explicitly.

### Fixed
- **One API error taxonomy, and a truncated response is never scored**
  ([ADR-021](decisions/021-api-error-taxonomy-and-incomplete-responses.md), `src/api_retry.py`,
  `src/run_isolation.py`). Five modules had grown the same wrong
  `except (InternalServerError, RateLimitError)` tuple, wrong in both directions: **too narrow**
  — `OverloadedError` (529) is a *sibling* of `InternalServerError`, not a subclass, so the most
  common transient failure on a long unattended run aborted it, and `APIConnectionError` /
  `APITimeoutError` were missed the same way — and **too wide**, since a spend cap arriving as a
  429 was slept on and retried, which cannot succeed. `api_retry` is now the single taxonomy:
  the non-retryable pattern (quota/billing/credit/auth) is tested first and wins over exception
  type, then deterministic types fail fast, then transient ones retry; an **unrecognized error
  fails fast**, because retrying an unknown failure silently triples spend on a bug. Backoff is
  byte-for-byte the old policy and every call site keeps its signature.

  Separately, `classify()` now asserts the call *finished*. With forced tool use and
  `max_tokens=256`, a truncated `ToolUseBlock` can still **validate** — the axes that survived
  are individually legal labels — and that partial answer was being scored right-or-wrong
  against gold. `IncompleteResponseError` is a deny-list (`max_tokens`, `pause_turn`,
  `model_context_window_exceeded`), not an allow-list, so an unrecognized `stop_reason` never
  breaks a caller the day the API adds a terminal value. `paired_compare` gained the landing
  spot: `HARNESS_ERROR_SENTINELS` (`__unclassified__`, `__incomplete__`, `__refused__`) all pair
  but are never scored as a miss, because a harness failure attributed to the model is a
  fabricated error rate. **Not verified live** — the taxonomy is exercised offline against
  constructed SDK errors, never a real 529.
- **The published metrics can no longer be stamped with a version whose prompt never
  produced them** (`src/provenance.py`, `scripts/gen_metrics_artifact.py`,
  `src/gold_eval.py`). `evals/gold_predictions_v3.csv` is a frozen snapshot of a paid
  live run, and nothing tied it to the prompt behind it. `--check` only ever compared
  the artifact against the gold set, that snapshot, and the version string — so editing
  `SYSTEM_PROMPT` and bumping the version, without paying for a gold re-run, left CI
  green while regeneration stamped the **new** version onto the **old** prompt's
  predictions. That is the same retyped-number drift the artifact was built on
  2026-07-18 to prevent, arriving through the generator instead of through a human,
  which makes it worse: a generated number carries the authority of having been computed.

  A run that makes API calls now records its identity — `prompt_sha256` plus both model
  ids, `hashlib` only, no new dependency — to a sidecar
  `evals/gold_predictions_v3.provenance.json`, and `gen_metrics_artifact.py` refuses to
  publish **or** to verify when that record no longer matches the code on disk. Models
  are fingerprinted alongside the prompt because a model swap invalidates a snapshot
  just as thoroughly (commit `6efbddf` migrated the workhorse to Sonnet 5).

  Three design points worth their record. **The sidecar, not `metrics.json`**: putting
  both the live and the recorded value in the artifact would be no guard at all, since
  `build_artifact()` would recompute both from the same live prompt and they could never
  disagree — the record has to be written by the producer, not the consumer. **The
  sidecar, not the CSV header**: twelve call sites read these prediction files with a
  plain `pd.read_csv`, where a `#` metadata line does not raise but silently collapses
  the frame to one garbage column. **The waiver**: a prompt edit otherwise hard-blocks
  CI until someone pays for a full gold re-run, and a guard that expensive gets deleted;
  a waiver must name the exact new fingerprint and carry a reason, so it converts the
  staleness from *silent* to *on the record* and auto-expires on the next change.

  The backfilled fingerprint states a verified fact, not an assumption: the
  `SYSTEM_PROMPT` literal was AST-extracted at `ad449db` (the commit that froze the
  snapshot) and at `HEAD` and hashes identically — `a59689e8…`, 9584 chars. The one
  `classify.py` commit in between (`cd7f6df`) touched only `InvalidLabelError` and
  `_validate`. Resuming a partial snapshot under a changed prompt is now refused too,
  since the finished file would be a blend of two classifiers that no single fingerprint
  could honestly describe. 26 tests across `tests/test_provenance.py` and
  `tests/test_metrics_artifact.py`.
- **The CI gate can no longer report the measured floors as met for a classifier that
  never produced the predictions** (`src/eval_gate.py`, `src/provenance.py`). The guard
  above closed the *publishing* path; the identical failure was still reachable one file
  over. `src/eval_gate.py` grades the same frozen `evals/gold_predictions_v3.csv` against
  `evals/thresholds.toml` as the `offline-gate` job on every push and PR, and had no
  pairing check — so editing `SYSTEM_PROMPT` and skipping the paid gold re-run left the
  gate printing eight green floors for a classifier that is not the one shipped. The
  gate's own claim is "the shipped numbers still clear the bar"; *shipped* is the word
  that had stopped being true.

  `main()` now runs `provenance.check()` before grading and exits `1` on divergence,
  **before printing any floors**. Its own exit path, deliberately: folding it into the
  floor result would report a stale snapshot as "a metric is below its floor" and send
  the reader hunting a regression that never happened. `provenance.check()` grew one
  optional `consequence` argument so each caller names its own failure (publish vs.
  grade) while sharing the identical remedy — the wrong consequence would send someone
  debugging the gate to `gen_metrics_artifact.py`.

  **Scoped to the default v3 snapshot, on purpose.** `gold_eval.py` writes exactly one
  sidecar, describing `PREDS_PATH`, so that is the only file whose pairing is *knowable*;
  deriving a per-preds sidecar path would invent a convention nothing produces. `--preds`
  pointed elsewhere reports `UNPINNED` rather than failing — an ad-hoc predictions file
  legitimately has no record, and the frozen v2 snapshot must never acquire a hand-written
  one, since a fabricated fingerprint asserts a pairing nobody verified. A *missing*
  sidecar for the v3 path is a hard failure, not a skip, or `rm` on one file would be a
  one-command bypass. The live CI leg is unaffected: it deletes the CSV and the sidecar,
  re-runs `gold_eval.py` to rewrite both, then grades. 10 new tests in
  `tests/test_eval_gate.py` and `tests/test_provenance.py`, including a real
  `SYSTEM_PROMPT` edit turning the gate red.

---

## [3.1.0] - 2026-07-25

Milestone: **the autonomy ladder, built to the top.** L3's second rung and all of L4 land
here, together with the classical-ML bake-off that finally measured whether the LLM was
worth paying for at all ([ADR-017](decisions/archive/017-classical-baseline-bakeoff.md) through
[ADR-020](decisions/archive/020-l4-multi-agent-pipeline.md)). Four verdicts, three of them negative:
the agent-driven ML loop improved the split it could see and degraded the held-out one,
retrieved exemplars did nothing, and the multi-agent pipeline did measurable harm at roughly
four times the calls. Each was kept as a record rather than deleted.

The shipped classifier is **unchanged** — same prompt, same single call, same
`{category, operational_domain, region}` contract — so this is a MINOR: capability was added,
nothing a caller relies on moved. The gold numbers below are still `v3.0.0`'s measurements
because the thing they measure did not change. The roadmap's scaled region eval, previously
pencilled in at this number, moves to `v3.2.0`.

### Added
- **L4: the multi-agent pipeline** ([ADR-020](decisions/archive/020-l4-multi-agent-pipeline.md),
  [spec](docs/specs/l4-multi-agent.md), `src/l4_pipeline.py`) — triage (verbatim evidence
  spans) → the untouched shipped `classify()` (blind to triage) → a critic whose narrow
  charter allows challenges only on rubric-checkable evidence claims, with the ladder's
  honesty test built in: a valid challenge bounces the label **backward** for exactly one
  re-classify (structural cap; a second challenge lands `contested`, never loops). The
  challenge gate is deterministic code (`challenge_violations`, fail-closed to accept); the
  critic's region rubric is extracted from the live prompt, never retyped; every step lands
  in an append-only audit JSONL (`evals/l4/`, gitignored). All three agents run the
  workhorse — no premium tier (ADR-013's constraint). Dry-run backend covers all four
  terminal statuses offline. **The autonomy ladder is now fully built, L1–L4. Verdict
  (same day, live runs): hypothesis CONFIRMED — the backward edge fixed 6/7 of the named
  region cluster — but the pipeline is DECLINED as configured: the all-axes critic
  over-challenged (57% vs ~13% expected; the spec's red-flag rule fired), did net harm on
  every other measure (scale domain 91.3→86.7, McNemar p=0.016 — the repo's first
  statistically significant harm) at ~4× calls per row. The shipped single call stays
  production. Record: `evals/l4_eval.txt` + both prediction CSVs.**
- **kNN-exemplar few-shot experiment harness** ([ADR-019](decisions/archive/019-knn-exemplar-fewshot.md),
  `src/exemplar_eval.py`) — the third and last untried retrieval-augmentation shape: k=3
  BM25-retrieved **labeled** exemplars appended to the system prompt (boundary placement,
  not topical context). Paired exact McNemar on the scale set vs judge labels with a
  fresh same-prompt baseline arm (the PR #81 fair-baseline lesson applied up front);
  gold read directionally with region as a guardrail. Stated prior going in is negative
  (ADR-012, ADR-018 amendment). Resume-safe per-row runs; offline-testable. **Verdict
  (same day): a clean null — category 91.0% vs 90.0% (p=0.70), domain flat, gold
  directionally unmoved, region guardrail exact — exemplars declined; the three-shape
  retrieval series is complete (harmful / harmful off-distribution / inert) and the
  single-call classifier stays the measured optimum. Record: `evals/exemplar_eval.txt`
  + the three arm CSVs.**
- **Rung 2 of the autonomy ladder: the agent-driven ML loop**
  ([ADR-018](decisions/archive/018-agent-driven-ml-loop.md), `src/ml_loop.py`) — an agentic outer
  loop (read out-of-fold errors on split A → propose the next experiment: vectorizer
  changes, regularization, error-driven keyword features) wrapping the mechanical sklearn
  inner loop of the ADR-017 bake-off baseline. Reuses rung 1's honesty architecture as
  shared code: `check_done_signal` / `select_best_iteration` imported from `optimize.py`
  (B-only decisions, C reported never read), same append-only JSONL run-log format
  (`evals/ml_loop/`, gitignored), and a deterministic pre-scoring proposal guard
  (`validate_experiment` — the rung-2 counterpart of the region-rubric freeze). Feedback is
  built from 5-fold out-of-fold predictions inside A, never fit-on-self (a test pins it).
  Only the proposer spends tokens; scoring is local. `--dry-run` runs the full loop offline
  with a canned proposer. Two axes, per ADR-017's disclosed region limit. **Verdict (same
  day, first live run — six iterations, stopped on plateau): the agent improved the metric it
  could see and degraded the one that matters, and the harness caught it. Best-by-B iteration
  2 scored B 0.699 (+6.0 over baseline) while held-out C fell to 0.545 (−8.6). The mechanism
  is distribution shift, not peeking — A and B are both judge-labeled DVIDS wire text, so
  keywords mined from A's errors genuinely generalize there and mislead on C's
  human-labeled mix. Every guard behaved: plateau fired, best-iteration selection read B
  alone, and C exposed the trade precisely because nothing was allowed to optimize it. This
  is the Goodhart centerpiece demonstrated end-to-end rather than merely designed for.
  Record: the ADR-018 amendment.**
- **Classical ML baseline bake-off** ([ADR-017](decisions/archive/017-classical-baseline-bakeoff.md),
  [spec](docs/specs/ml-baseline-bakeoff.md)): `src/baseline_ml.py` trains TF-IDF + logistic
  regression on the 300 judge-graded snippets (`judge_*` labels only) and scores it once
  against the human gold set through the existing hand-rolled metrics. Verdict: the LLM wins
  decisively (category 92.6% vs 72.2%, McNemar p=0.013; domain 92.6% vs 66.7%, p=0.0005) —
  the first measured justification of the foundational LLM spend. Report in
  `evals/baseline_eval.txt`, per-row predictions in `evals/baseline_predictions.csv`, offline
  tests in `tests/test_baseline_ml.py`. scikit-learn enters the dev/eval dependency group
  only; the shipped classifier's runtime deps and behavior are unchanged. This harness is the
  substrate the autonomy ladder's rung-2 agent loop will wrap.
- **Published `/classify` contract artifact** (`contracts/classify-response.schema.json`,
  `scripts/gen_contract_schema.py`, `tests/test_contract_schema.py`) — this repo is the
  **provider** on the SYS-004 seam, so it now publishes the wire contract as a committed
  artifact consumers assert against. Generated from `ClassifyResponse` plus
  `CATEGORIES`/`DOMAINS`/`REGIONS`, never hand-edited, with `additionalProperties: false`
  so an added field is a detectable breaking change. A test regenerates in memory and
  compares byte-for-byte, and CI runs `--check`, so editing the response model or a label
  constant without regenerating turns the build red. The generator also refuses to publish
  a response field that has no backing enum, closing the "fourth axis silently published as
  an unconstrained string" path.

  **Why:** SYS-004 claimed "contract tests on both sides… turn any drift into a red build."
  That was false in kind — each repo asserted against its *own* copy of the shape, so when
  `region` shipped in v3.0.0 the provider's fixture moved with it, the consumer's did not,
  and both suites stayed green through a breaking change. This artifact is the shared thing
  that was missing. Output contract untouched, so per this project's own precedent (the
  evals-CI gate in v2.1.0) it earned no version bump on its own; it rides the `v3.1.0` tag.

### Fixed
- **The prompt-optimization loop can no longer silently destroy the `region` axis**
  (`src/optimize.py`, `src/classify.py`). `src/optimize.py` had not been touched since
  2026-07-11 and knew nothing about the `region` axis that shipped in `v3.0.0`
  ([ADR-014](decisions/014-region-field-design.md)) — `grep region src/optimize.py`
  returned zero hits. Three concrete hazards, all fixed:

  1. **`OPTIMIZER_SYSTEM_PROMPT` told the proposer the classifier had two axes**, handed it
     the live `SYSTEM_PROMPT` (now carrying a ~130-line region rubric), asked for "the full
     revised prompt text", and only ever said "the five categories and six domains are
     fixed". Nothing instructed it to preserve the region rubric, so the agent could delete
     the hardest-won axis (87.0% at `v3.0.0`, including the no-guessing rule) and the run
     log would show only a category improvement. The prompt now names all three axes and
     freezes the region rubric verbatim, calling out each of the four places region material
     lives — the label list, the `Region rules:` section, the third label on every worked
     example, and clause (4) of the tie-breaking sentence. The rubric is *not* separable
     from the rest of the prompt (all 25 worked examples carry three labels), so withholding
     it from the proposer was never an option; an explicit freeze plus a guardrail score is.

     The freeze is now **enforced, not just instructed**: `region_rubric_violations()`
     compares each proposal against the prompt it was handed before any scoring call —
     the `Region rules:` block must survive byte for byte, and no region label may appear
     fewer times than it did (catching a region dropped from a worked example, which lives
     outside the block). A violation retries the proposer; if every attempt mangles the
     rubric, `propose()` raises `ProposalError` and the run stops rather than scoring a
     damaged prompt. This is deterministic and free, where the guardrail score below only
     reveals damage after a scoring pass costing ~350 API calls. Count comparison uses
     *fewer*, not *different*, so a category-only edit that adds an example mentioning a
     theater is not punished — a guard that cries wolf on valid work gets disabled.
  2. **No region number in the run log.** Each iteration now records a `region_guardrail`
     score (region macro-F1 / accuracy / per-class F1) on split C — the gold set is the only
     region-labeled data the loop has, since `data/synthetic_articles.csv` has no `region`
     column — printed on the console line and summarized baseline-vs-best in the run
     trailer. It is **reported, never optimized**: not in `scores`, not in the B-F1 history,
     not read by `check_done_signal()` or `select_best_iteration()`. Wiring it into a
     decision would make the held-out set an optimization target, the exact failure ADR-005's
     3-way split exists to prevent.
  3. **A region-only invalid label scored as a category miss.** `AnthropicBackend.score()`
     caught `InvalidLabelError` and set *both* `pred_category` and `pred_domain` to the
     `__unclassified__` sentinel, so a bad `region` polluted the very metric that drives the
     done-signal. The sentinel is now applied **per axis** (`_salvage_labels()`): valid axes
     keep their labels, only the failed one is counted a miss. `classify.InvalidLabelError`
     gained an optional `result` payload to make this possible; it re-checks every axis
     against its own enum rather than trusting which one `_validate` happened to report
     first. An error raised without a payload still degrades to all-three sentinels.

## [3.0.0] - 2026-07-18

Milestone: **the `region` field.** The roadmap's planned breaking change: the output contract
becomes `{category, operational_domain, region}` ([ADR-014](decisions/014-region-field-design.md)).
Six labels — `indo-pacific`, `europe`, `middle-east`, `africa`, `americas`, and `global` as the
single catch-all for no-anchor and multi-region stories, mirroring `multi` on the domain axis.

### Changed — BREAKING
- **Output contract: `{category, operational_domain}` → `{category, operational_domain, region}`**
  (`src/classify.py`, `src/api.py`) — `region` is a required strict-enum field on `CLASSIFY_TOOL`
  (ADR-008 pattern), a required key on the `/classify` response, and a third hand-labeled column
  on the gold set. The SYS-004 frozen-contract literals moved with it; kb-agent's side of that
  contract needs its own update before it re-pins. `SYSTEM_PROMPT` gains the region axis:
  definitions, boundary rules (theater of the subject activity; snippet-stated places only — no
  world-knowledge guessing; ratified conventions: Hawaii→indo-pacific, Mediterranean→europe,
  Afghanistan+Central Asia→middle-east), worked examples, and a region tie-break.

### Added
- **Gold set: hand-labeled + adversarially audited `region` column** (`data/gold/gold.csv`,
  `data/gold/README.md`) — all 54 rows pre-labeled offline, owner-reviewed row by row, then the
  full set verified against every snippet's source article on **all three axes** (multi-agent
  pass: one verifier per row, adversarial skeptics on challenges, cross-row consistency audit).
  Category and domain survived 108/108 — the v2 hand labels and the published numbers stand
  untouched; region took two review corrections (g003→europe, g024→americas). The labeling
  rules are recorded in the gold README, including the snippet-decidable/article-confirmable
  rule that keeps gold truth consistent with what the classifier can actually see.
- **First live three-axis gold run** (`evals/gold_eval_v3.txt`, `gold_predictions_v3.csv`,
  `gold_confusion_v3.*`) — category **92.6%** (macro-F1 0.911), domain **92.6%** (0.933),
  region **87.0%** (0.927); judge-vs-human agreement **92.6% / 98.1% / 100.0%**. The 100.0%
  judge-region agreement clears ADR-014's gate for the v3.1.0 scaled region eval. The region
  misses are a single named cluster: 7/7 are gold=`global` rows pulled to a specific region
  (6× americas, 1× indo-pacific) — the model infers a region from the US actor where the
  no-guessing rule says no anchor. All v3 eval outputs use new `_v3` filenames; the v2
  snapshots are frozen records and are never regenerated.
- **Region floors in the CI gate** (`evals/thresholds.toml`, `src/eval_gate.py`) — measured,
  never aspirational: region_accuracy 0.78 (vs 0.870 measured), judge_region_agreement 0.93
  (vs 1.000 measured). Deliberately no region macro-F1 floor (europe support n=1 — one flip
  moves it ~0.17). The gate's default target graduates to the committed v3 snapshot, grades
  all eight floors, and refuses a two-axis file loudly; `--preds` lets the live CI job grade
  its freshly regenerated run.

### Fixed
- **Transient strict-mode blips no longer kill the live pass** (`src/gold_eval.py`) — the first
  v3 live run died at row 13 when the Opus judge returned a tool input with no `category` at
  all despite `strict: true`; the identical replay was clean. Diagnosed as a transient
  constrained-decoding anomaly (it recurred twice more in the completed run), so the harness's
  `classify_retry` now retries `InvalidLabelError` with the same bounded backoff as 500s/429s —
  `classify()` itself stays single-call-fail-loud per ADR-008. The `InvalidLabelError` backstop
  kept "in case the guarantee is ever violated" fired in the wild and did its job.
- **Interrupted runs can't masquerade as results** (`src/eval_confusion.py`) — the crashed
  partial run produced a clean-looking n=12 confusion report; the report now leads with a
  PARTIAL RUN banner whenever predictions cover fewer rows than the gold set.

## [2.2.0] - 2026-07-18

Milestone: **tiered model routing — measured and declined.** The roadmap's v2.2.0 ships as a
measured negative result ([ADR-013](decisions/archive/013-decline-tiered-routing.md)), the project's
second after the BM25 grounding retirement: the routing harness was built, the cost/quality
trade was measured, and the verdict is that routing buys nothing at ~2x the cost. The shipped
classifier stays single-model, single-call.

### Added
- **Tiered-routing experiment: runner-up trigger + offline-replayable measurement harness** (`src/route.py`, `src/route_eval.py`) — the build for the roadmap's **v2.2.0 "tiered model routing"**, aimed at the `technology`-vs-`operations` boundary per [ADR-011](decisions/archive/011-reaim-tiered-routing-technology-operations.md). The shipped classifier forces tool use and so emits no confidence signal; `route.py` manufactures one — a routing-only variant of the classify tool adds a required `runner_up_category` field, and `route()` escalates to the Opus tier exactly when the workhorse reports {technology, operations} as its top-two. `classify_routed()` keeps the `{category, operational_domain}` contract byte-for-byte. `route_eval.py` measures the cost/quality trade with three honesty guards baked in: quality is graded **only on the n=54 human gold set** (the scale set's answer key is the Opus judge — the escalation target itself — so it reports rate/cost, never "accuracy"); escalations are **replayed from the stored judge predictions** (same model, same call shape), so the live spend is one workhorse pass and zero new Opus calls; and the runner-up schema's perturbation of the workhorse's own labels is measured, not assumed away. Shipped with the stated hypothesis that the #79 prompt fix already cleared the target cluster (technology recall 1.000 vs human) and routing likely no longer pays.
- **The measured verdict** (`evals/route_eval.txt`, [ADR-013](decisions/archive/013-decline-tiered-routing.md)) — the hypothesis held, decisively. On the human-graded gold set, routing moved **+0 rows on both axes** (94.4% / 92.6%, identical to the workhorse); the escalated rows read **fixed 0, broke 1, unchanged 8**, where the one change was Opus overriding a correct workhorse answer with the judge's own known tech→ops error (g007). Even all-Opus scores the same 94.4% category as the workhorse — no category router has headroom to capture on this set. On 299 real DVIDS snippets the trigger fires on **19.4%** of articles (changing only 2 labels), pricing the routed pipeline at **~1.97x** the workhorse per article at the 5:1 list-price ratio. Routing is therefore **declined**: the harness, artifacts, and tests stay dormant as the reproducible record, and the shipped path is unchanged. The schema perturbation was small (2/54 category, 0/54 domain) but included one finding worth the record: the runner-up field flipped s151 — a chem-bio *defense* program story the baseline had classified cleanly — into a safety-layer refusal.

### Fixed
- **Runner-up passes survive safety-layer refusals** (`src/route_eval.py`) — the first live scale batch crashed retrieving results when s151 came back `stop_reason='refusal'` (the loop caught transport errors and invalid labels, but a refusal escaped and aborted the retrieval). Both passes now record a `refused` sentinel row and continue: the id counts as done on resume (no re-buying a permanently-refused row every rerun), `_load_runner` excludes sentinel rows from every metric, and the report names the excluded ids so the shrunken n is stated, not silent. The conftest batch fake learned to simulate a refusal (a *succeeded* item with `stop_reason='refusal'` and no tool_use block) so the guard is under test.

## [2.1.0] - 2026-07-17

Milestone: **scale the eval**. This tag also releases everything that had accumulated under
`[Unreleased]` since v2.0.1 (the v2.0.2 hardening, the evals-CI gate, the prompt-optimization
loop, OTel tracing), plus the tech-vs-ops prompt improvement and the BM25 grounding retirement.

### Added
- **Scaled eval with the validated Opus judge** (`src/scale_eval.py`, `scripts/build_scale_set.py`, and `wilson_interval` in `src/eval.py`) — the tooling for the roadmap's **v2.1.0 "scale the eval"**. Grades a ~300-snippet real DVIDS set with the Opus judge as the answer key (validated at 94.4% / 94.4% agreement vs the human gold labels), reporting workhorse accuracy with **95% Wilson confidence intervals** so the n=54 gold set's ~13-point-wide CI shrinks to ~5 points at n=300 — the report shows that narrowing against the committed gold snapshot side by side. Reuses `gold_eval.run_predictions`/`run_predictions_batch` (now `preds_path`-parameterized) and `eval.py`'s metric helpers, so every number is computed identically to the rest of the harness; resume-safe, with an optional `--batch` path. `scripts/build_scale_set.py` sources the snippets from DVIDS disjoint from **both** the corpus and the gold set (no leakage into the judge's own validation data), unlabeled — the workhorse and judge produce the labels at eval time. **Measured on 300 DVIDS snippets:** category **93.3%** (95% CI [89.9%, 95.6%]), domain **90.3%** (95% CI [86.5%, 93.2%]) — half the n=54 CI width, corroborating the gold-set accuracy rather than replacing it. Honest caveats baked into the report (`evals/scale_eval.txt`): it measures workhorse-vs-judge agreement (inherits the judge's ~5–6% human-disagreement ceiling), and the operations-heavy DVIDS skew (`operations` 66%, `industry` n=1) makes the category macro-F1 uninformative — read overall accuracy + the well-populated per-label rows. `{category, operational_domain}` output contract untouched.
- **OpenTelemetry tracing over the `classify()` LLM call** (`src/telemetry.py`) — the classifier's single LLM call is instrumented against the OTel API always; the recording SDK is configured only when `CLASSIFIER_TRACING` is set, so the eval hot path (hundreds of `classify()` calls per optimize iteration) and the offline suite stay a zero-overhead no-op. When on, each call emits a `chat <model>` span with GenAI-semconv attributes (`gen_ai.usage.*` tokens, `gen_ai.response.finish_reasons`) plus the resulting `classifier.category` / `classifier.operational_domain`. Console exporter to stderr by default; OTLP is the optional `otlp` extra. Mirrors the `kb-agent` tracing so the two services share one observability language, and closes the classifier half of the SYS-007 "OTel across notes-api + `/classify`" item. Output contract (`{category, operational_domain}`) is untouched, so this rides `[Unreleased]` without earning a bump.
- **`Jenkinsfile`** — the CI pipeline expressed as a declarative Jenkins pipeline (checkout → `uv sync` → parallel ruff/black/mypy → unit tests with the coverage gate), mirroring `.github/workflows/tests.yml`. GitHub Actions stays the live gate; this is pipeline-as-code for a Jenkins controller (none runs it here, so it has no status check).
- **Evals-as-CI capability gate** (`.github/workflows/evals.yml`, `src/eval_gate.py`, `evals/thresholds.toml`) — wires the v2 gold-set evals (`gold_eval.py`, `gold_eval_rag.py`) into CI as two gates split by API cost: a free offline gate on every push/PR that grades the prediction CSVs already committed against threshold floors, and a paid live gate on `workflow_dispatch` + a weekly schedule only (never `pull_request`, and never `pull_request_target`) that re-runs the real models first and never commits the refreshed numbers back. `build_report()` in both eval scripts now reads from an extracted `metrics()` function — same printed output, now also machine-readable. `Jenkinsfile` gets a matching parity-only offline stage. See [ADR-007](decisions/007-evals-as-ci-gate.md).
- **Rung-1 prompt-optimization loop** (`src/optimize.py`, autonomy ladder L3) — an agent-driven loop that reads the classifier's eval failures on a held-out A split, proposes a revised system prompt, re-scores A/B/C, and repeats until an explicit done-signal fires (threshold, then plateau, then budget). The orchestrator (`run_optimization`) talks to an injected `OptimizerBackend` (`score`, `propose`) rather than the Anthropic client directly, which makes the Goodhart guard structural — B/C never reach the code path that builds the proposer's feedback — and gives a zero-API `--dry-run` mode for free via `DryRunBackend`. Run log is append-only JSONL for resume-safety. See [ADR-005](decisions/archive/005-agentic-prompt-optimization-loop.md) and [the loop spec](docs/specs/prompt-optimization-loop.md). **Per the spec's §11 sequencing, this was held for `v2.1.0`** — which shrinks the n≈54 noise floor its honest held-out number depends on — and, that milestone having shipped in this release, it is released here.
- **Backfilled the v2 eval modules' orchestration tests** — offline tests for the API-driving run-loops and `main()` entrypoints in `src/stability.py`, `src/gold_eval_rag.py`, `src/gold_eval_haiku.py`, and `src/retrieval_error_analysis.py` that the existing pure-function tests deliberately skipped (the run loops, the transient-error retry/backoff, batch polling, and the CLI dispatch/resume-skip branches). They reuse the conftest fake-client / fake-batch stand-ins plus `monkeypatch`ed path constants, so they stay offline — no API key, no network. Lifts those four modules from 58–86% to 99% line coverage — only the `if __name__` guard lines remain, matching `gold_eval.py` — and overall `src/` coverage from 90% to 97% (+18 tests); the `{category, operational_domain}` output contract and all runtime behavior are unchanged. This is the "v2.0.2" hardening from the CLAUDE.md versioning roadmap — recorded here rather than tagged, so it rides the next release like the evals-CI gate above.

### Changed
- **Prompt refinement: technology-vs-operations + the `land` domain default** (`SYSTEM_PROMPT`) — the per-cell gold confusion breakdown showed the clustered misses were `technology`→`operations` (a new system tested/demoed in an operational setting, read as `operations`) and over-assignment to `land`. Two targeted rubric clauses fixed both, **measured on the gold set**: category **90.7% → 94.4%**, domain **90.7% → 92.6%** (`technology` recall to 1.000), nothing regressed. The #78 confusion tool (`src/eval_confusion.py`) is what surfaced the clusters; ADR-011 re-aimed the v2.2.0 tiered-routing target at this pair as a result. Output contract untouched.

### Removed
- **BM25 retrieval grounding, retired** ([ADR-012](decisions/archive/012-retire-bm25-grounding.md)) — once the prompt improved, a **fair same-prompt re-measure** (the earlier grounding "lift" had been scored against a stale, pre-prompt baseline) showed BM25 grounding no longer pays: neutral on category, a domain regression — **0 domain calls fixed and 4 broken across a 3-pass confirm**. It was removed from the shipped path and the CI gate (which now scores only the ungrounded classifier), and `[rag]` was dropped from `thresholds.toml`. The grounding code, corpus, and measurement scripts stay in the repo dormant and reproducible. Supersedes [ADR-010](decisions/archive/010-rag-path-model-pin.md)'s 4.6 pin. `src/api.py` never grounded, so the live service and kb-agent are unaffected.

### Changed (earlier in this release, since superseded)
- **Eval snapshot refreshed post-rubric** — `evals/gold_predictions.csv`, `gold_rag_predictions.csv`,
  and both report files re-run fresh under the extended-rubric prompt, with README numbers swept to
  match (one self-consistent run, mirroring the live CI gate's procedure). Baseline (Sonnet 5):
  category 90.7% (macro-F1 0.902), domain 90.7% (0.919); judge agreement 90.7% / 92.6%. Grounded
  (Sonnet 4.6 pin): category 94.4% (0.950), domain 96.3% (0.964) — grounding's flip ratio improved
  from break-even at the v2 ship to 8 fixed / 1 broken, strengthening the no-embeddings verdict.
  Every gated metric clears its `thresholds.toml` floor. Noted honestly in the README: the
  pre-rubric refresh had Sonnet 5 domain at 94.4% vs 90.7% now (a two-flip swing inside n=54
  noise). ADR-010's Sonnet-5 grounding regression was then re-measured under the new rubric
  (`scripts/adr010_remeasure.py`, 3 passes): it persists at −3.7/−3.7/−5.6 domain, each pass
  breaching the −3.0 floor — smaller than the original −9.3 but not cured, so the RAG pin
  stands (recorded in ADR-010's re-measurement section).
- **`SYSTEM_PROMPT` gains an extended rubric, making prompt caching real** — the prompt now
  encodes the gold set's own labeling conventions (contract award = the buyer's story →
  `procurement`; policy = the rule, not the doing; cyber-vs-host-platform; uncrewed systems
  by operating medium) plus 16 worked examples and an explicit tie-break order, targeting the
  `industry`/`procurement`/`technology` triangle where 90% of the v1 category misses lived
  (`evals/error_audit.md`). Sizing is deliberate: the cacheable prefix (tool schema + system
  prompt) grows from ~876 to ~2425 tokens, clearing claude-sonnet-5's 2048-token minimum
  cacheable-prefix floor — verified live via `scripts/cache_diagnostics.py --live` (call 1:
  `cache_creation=2350`, call 2: `cache_read=2350`), where before the change both calls
  showed the `cache_control` marker as a silent no-op. Bulk paths (eval runs, batches, the
  optimize loop) now re-read the prefix at the 90%-discounted cache rate. The script's
  misleading "not surfaced by this SDK version" message for a null diagnostics field is also
  fixed (null is the API's "no divergence found" answer, per the cache-diagnostics docs).

The `{category, operational_domain}` output contract is unchanged throughout. The
classifier's live surface remains the `/classify` HTTP provider.

## [2.0.1] - 2026-07-05

Dead-code hardening release: removes the Kafka consumer path outright instead of
continuing to carry it as inactive weight. No change to the `{category,
operational_domain}` output contract.

### Removed
- **Kafka consumer (`src/consumer.py`) and its test suite.** The consumer was added as
  an event-driven alternative to the `/classify` HTTP path — reading `NoteCreated`
  events off a `note-events` topic, classifying them in-process, and writing labels back
  onto the note as namespaced tags. It was later reclassified from active integration to
  inactive reference implementation once notes-api's Python/FastAPI port dropped Kafka
  in favor of a `BackgroundTasks` writeback loop: nothing has published `note-events`
  since, so the consumer had become a no-op against the live system. Keeping a dead
  consumer and its Testcontainers-backed integration test (`tests/test_consumer.py`,
  `tests/test_consumer_integration.py`) green in CI cost ongoing maintenance for zero
  live coverage, so both are deleted here; the reference implementation itself remains
  available in git history and the project's ADRs for anyone who wants to see the
  event-driven design. The now-unused `kafka-python` and `testcontainers[kafka]`
  dependencies are dropped from `pyproject.toml` and `requirements.txt` accordingly.
  `README.md`'s project-structure listing, `.env.example`'s now-orphaned
  `KAFKA_BOOTSTRAP_SERVERS`/`NOTE_EVENTS_TOPIC`/`KAFKA_GROUP_ID`/`NOTES_API_BASE_URL`
  block, and `docs/integration-testing.md` (which existed solely to document the
  now-deleted integration test) are updated/removed to match. The CI `integration-test`
  job (the Testcontainers Kafka lane in `.github/workflows/tests.yml`) is dropped along
  with it, since it had no integration test left to run. The classifier's live
  surface remains the unchanged `/classify` HTTP provider.

## [2.0.0] — 2026-06-21

Moved the eval off synthetic, self-graded data and onto **real public-domain text**, with retrieval grounding and a non-circular, human-labeled answer key. v1 measured in-distribution *consistency* (the model classifying snippets it wrote itself); v2 measures real-world *accuracy* against labels a human assigned. The arc between them is the headline.

### Added
- **Real public-domain corpus** (`data/corpus/`, 62 docs) — 56 pulled from the [DVIDS](https://www.dvidshub.net/) DoD news wire (public-domain U.S. government text) spanning procurement / operations / technology / policy across all six domains, plus 6 hand-collected SEC filings for the `industry` class the military wire doesn't carry. Collected by `scripts/fetch_corpus.py` (DVIDS API; the service sites hard-block bots, so the API + hand-collection are the clean-room way in). New dependency: `rank-bm25`.
- **BM25 retriever** (`src/retrieve.py`) — whole-doc lexical retrieval over the corpus, reading both the auto-generated and hand-curated manifests. Chosen as the deliberate "measure first" baseline; embeddings are escalated only if the eval shows retrieval is the bottleneck.
- **Human-labeled gold set** (`data/gold/gold.csv`, 54 snippets) — hand-labeled against a written guide (`data/gold/README.md`) that sharpened the `policy` definition, disjoint from the corpus so grounding a snippet never retrieves itself. Builder scripts `scripts/build_gold.py` and `scripts/add_policy_gold.py`.
- **Honest eval harness** (`src/gold_eval.py`) — the workhorse classifier graded against the human labels: category **88.9%** (macro-F1 **0.906**), operational domain **88.9%** (macro-F1 **0.894**) — the non-circular numbers v1's self-grading could not produce. Headline fix: **`industry` F1 1.000** on real SEC earnings/M&A, v1's worst class (recall 0.217 → caught 1 in 5); honest caveat is `n=5` clear-cut filings. An **Opus judge** is validated against the human labels at **88.9%** category / **94.4%** domain agreement, so it can serve as a scalable answer key where hand-labeling doesn't reach. Report in `evals/gold_eval.txt`.
- **Retrieval-grounded classification + citations** (`src/classify_rag.py`) — prepends the top-k label-tagged BM25 neighbors as reference context and returns the citations that grounded the call. Lift measured by `src/gold_eval_rag.py` with a flip analysis: **+1.9%** category accuracy (2 wrong→right, 1 right→wrong), domain **flat** (3 fixed / 3 broke). Conclusion: lexical BM25 grounding does **not** justify upgrading to embeddings here — the negative result is the finding (`evals/gold_rag_eval.txt`).
- `model=` parameter on `classify()` so the Opus judge runs the identical prompt, tool schema, and label validation as the workhorse — baseline vs judge differ only by model tier.
- `DVIDS_API_KEY` documented in `.env.example` (the read-only **public** key only; the secret key is unused).
- Unit tests for the retriever, the gold-eval metrics, and grounded classification — all offline/mocked, no API key needed.

### Changed
- **README rewritten to lead with the v2 numbers**, structured as a v1→v2 arc: v2's honest, human-graded results up top; v1's synthetic self-graded eval kept as the foundation and the `industry` blind spot it surfaced (which v2's real SEC text then closed).
- `pyproject.toml` version bumped `1.1.0` → `2.0.0`.

---

## [1.1.0] — 2026-06-21

Tightened the measurement around the v1.0.0 classifier: macro-F1, a multi-run stability harness, a full error audit, and an enum-validation guard (which caught and corrected an inaccurate docs claim along the way).

### Added
- `LICENSE` — MIT license
- README status badges (CI, release, license, Python version)
- `docs/how-it-works.md` — plain-language one-pager on the three-stage pipeline and why the classifier/evaluator separation is the point, with a "Threats to validity" section
- `docs/CASE_STUDY.md` — narrative writeup (problem, key decisions, the reverted experiment, honest limitations, what's next); linked from the README
- **Macro-averaged precision/recall/F1** in the eval report (`macro_average` in `src/eval.py`) — every label weighted equally, so a collapsed minority class is no longer hidden by raw accuracy. Category macro-F1 is **0.765** (below its 79.0% accuracy); domain is **0.973**. Two new unit tests cover it.
- **Multi-run stability harness** (`src/stability.py`) — runs the full eval N times and reports mean / std / min / max per headline metric, so a config difference can be checked against the run-to-run noise floor (clears ~2x std?) instead of trusting a single run. Optional `--temperature` flag; per-run predictions saved to `evals/runs/`, summary to `evals/stability.txt`. `classify()` and `classify_with_retry()` gained an optional `temperature` parameter. Six new unit tests cover the pure aggregation/reporting functions. First run (5 passes) puts category accuracy's run-to-run std at 0.24 points and domain accuracy's at 0.50 points; the reverted prompt experiment's 2.3-point drop clears that noise floor by ~10x, confirming it was a real regression rather than sampling noise.
- `.env.example` — committed template documenting the `ANTHROPIC_API_KEY` the project needs; copy to `.env` (gitignored) and load with `uv run --env-file .env`. README gained an "API key & secrets" subsection covering the pattern, the rationale, and the machine-local caveat (`.env` is recreated on a fresh clone — the deliberate trade-off of keeping secrets out of git).
- `evals/error_audit.md` — manual audit of all 67 misclassifications, separating genuine classifier errors from label-scheme ambiguity. 90% of category misses fall in the `industry`/`procurement`/`technology` triangle, where a company winning a contract matches two label definitions at once — so the gap is label overlap, not model capability.
- **Enum validation guard** in `classify()` (`InvalidLabelError` + `_validate`) — the result is checked against the allowed `CATEGORIES`/`DOMAINS` and the call is re-sampled once on an out-of-enum response before raising. A tool-use `enum` is a guided prior, not a hard server-side constraint: one prediction in a 300-article run came back as an invalid category (`category="cyber"`), and this guards against it. New unit tests (plus a sequence-returning test client) cover validation, the re-sample, and the raise.

### Fixed
- Corrected an inaccurate claim across `README.md`, `docs/CASE_STUDY.md`, `docs/how-it-works.md`, and PRD requirement F9 that out-of-enum output is "rejected/enforced at the API layer." Tool use enforces the response *shape* and strongly biases toward valid labels, but enum membership is validated in our code, not guaranteed by the API. (Surfaced by the error audit; see above.)

### Changed
- `pyproject.toml` version bumped `0.1.0` → `1.0.0` to match the released tag
- README results table now reports macro-F1 alongside accuracy
- `evals/metrics.txt` regenerated to include the macro-average rows (recomputed from existing predictions, no re-classification)
- Added a plain-language definition of precision, recall, and F1/macro-F1 to `docs/how-it-works.md` (with a short gloss in the README results section), so the headline metric isn't unexplained jargon
- Readability pass over `README.md`, `docs/CASE_STUDY.md`, and `docs/how-it-works.md`: trimmed heavy em-dash use in favor of colons, commas, and periods

---

## [1.0.0] — 2026-06-20

First complete version of the defense news classifier. All v1 success criteria met.

### Added
- Synthetic dataset generator (`src/generate.py`) — 300 labeled articles across all 30 category × domain combinations, produced via Anthropic API with structured (tool-use) output
- LLM classifier (`src/classify.py`) — single API call per article returning validated `{category, operational_domain}` JSON
- Eval harness (`src/eval.py`) — accuracy, per-label precision/recall/F1, confusion matrices, misclassification log, and resume-on-interrupt support
- Eval artifacts (`evals/`) — predictions, metrics, confusion matrices, misclassification log
- Unit test suite (`tests/`) covering classifier, generator, and eval metrics with mocked API calls (`dd2d727`)
- `pytest-cov` dev dependency for coverage reporting (`478b6a1`)
- `uv` for dependency management — `pyproject.toml`, `uv.lock`, `.venv` (`8e1db6d`)
- `requirements.txt` kept as a pip fallback
- README leading with eval results (79.0% category accuracy, 97.3% domain accuracy)
- `docs/PRD.md` — product requirements document
- `CLAUDE.md` — project guidance for Claude Code

### Tooling
- Black for code formatting (`uv run black src/ tests/`); configured in `pyproject.toml`
- Ruff for linting (`uv run ruff check src/ tests/`); configured in `pyproject.toml`
- mypy for static type checking (`uv run mypy src/`); configured in `pyproject.toml`
- pre-commit for running the above checks before each commit
- GitHub Actions CI running the test suite on push and pull request
- `.gitattributes` marking notebooks as documentation so the GitHub language bar reflects the Python source rather than embedded notebook output

### Fixed
- `metrics.txt` written with explicit UTF-8 encoding to avoid platform-default encoding errors on Windows (`2cf797c`)

### Investigated
- **Prompt experiment — sharpening the procurement/industry definitions (reverted).**
  Hypothesis: adding an explicit "a firm *winning a specific contract* is procurement; a firm
  *reporting earnings or merging* is industry" distinction to the system prompt would lift
  `industry` recall, the weakest label (0.217). Re-ran the full 300-article eval — the change
  **regressed** the target: category accuracy 79.0% → 76.7%, `industry` recall 0.217 → 0.100.
  The sharper wording made the model even more willing to route borderline company stories into
  `procurement`. Reverted the prompt and kept the 79.0% baseline. Recorded as a negative result —
  the eval, not intuition, decided.

---

## [0.1.0] — 2026-06-19

### Added
- Initial project scaffold: `src/`, `data/`, `evals/` directory structure (`c64c074`)
- Core scripts: `generate.py`, `classify.py`, `eval.py`
- Synthetic dataset (`data/synthetic_articles.csv`)

---

[Unreleased]: https://github.com/sanlee-ys/defense-news-classifier/compare/v3.2.1...HEAD
[3.2.1]: https://github.com/sanlee-ys/defense-news-classifier/compare/v3.2.0...v3.2.1
[3.2.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v2.2.0...v3.0.0
[2.2.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/sanlee-ys/defense-news-classifier/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/sanlee-ys/defense-news-classifier/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/sanlee-ys/defense-news-classifier/releases/tag/v0.1.0
</content>
</invoke>
