# Decision log

This directory holds three kinds of record, and keeping them apart is the point.

| Record | What it is | Where |
|---|---|---|
| **ADR** | A decision that governs how the code is built from now on. Few, stable, numbered. | This directory |
| **Verdict** | An experiment result. Accumulates. Decides nothing by itself. | [`verdicts.md`](verdicts.md) |
| **Current practice** | The rule as it stands today, synthesized from several superseded ADRs. | [`agent-practice.md`](agent-practice.md) |

Between 2026-06-25 and 2026-08-11 all three went into the numbered ADR set, which reached 26
entries of which only 11 decided anything still in force. The restructure on 2026-08-20 split
them apart. **Nothing was deleted**: every superseded ADR keeps its full original text under
[`archive/`](archive/), and the number map below says where each one went.

## Live decisions

| # | Title | Status |
|---|-------|--------|
| [001](001-llm-provider.md) | Use Anthropic API with claude-sonnet-4-6 | Accepted. **Title is stale**: the workhorse is `claude-sonnet-5` (see [ADR-010](archive/010-rag-path-model-pin.md) for the migration) |
| [002](002-structured-output-via-tool-use.md) | Enforce structured output via tool use, not prompt engineering | Accepted |
| [003](003-synthetic-data-only.md) | Use synthetic data only — no real news articles | Accepted; amended 2026-07-19 (scope narrowed) and 2026-08-20 (the balance claim corrected) |
| [004](004-no-ml-framework-for-eval.md) | Implement eval metrics in plain Python — no ML framework | Accepted; amended 2026-07-19 |
| [006](006-autonomy-ladder-portfolio-spine.md) | Make an autonomy ladder the portfolio spine, with the classifier as the single protagonist | Accepted |
| [007](007-evals-as-ci-gate.md) | Wire the v2 gold-set evals into CI as a two-gate quality gate, split by API cost and fork-PR secret safety | Accepted |
| [008](008-strict-structured-outputs.md) | Enforce enum validity server-side with `strict: true`, retire the client-side re-sample | Accepted |
| [009](009-message-batches-for-bulk-runs.md) | Add a Message Batches API path for non-latency-sensitive bulk classification | Accepted |
| [014](014-region-field-design.md) | Region field design — six labels with a `global` catch-all, gold-first scope | Accepted |
| [015](015-public-domain-data-sourcing.md) | All text is public-domain or synthetic — DVIDS + SEC + generated, never scraped or licensed | Accepted |
| [021](021-api-error-taxonomy-and-incomplete-responses.md) | One API error taxonomy, plus a stop-reason assertion so a truncated response is never scored | Accepted |

## Number map

Every number ever issued, and where its record lives now.

| # | Now |
|---|---|
| 001–004, 006–009, 014, 015, 021 | Live, above |
| 005, 016, 018, 025, 026 | Superseded as the statement of the rule by [`agent-practice.md`](agent-practice.md). Full text in [`archive/`](archive/) |
| 010, 011, 012, 013, 017, 019, 020, 022, 023, 024 | Indexed in [`verdicts.md`](verdicts.md). Full text in [`archive/`](archive/) |

ADR-025 was absent from this index between 2026-08-11 and 2026-08-20. That is the kind of
drift a 26-entry hand-maintained table produces, and it is part of why the set was split.

## When to write which

**Write a verdict row** when you measured something. That is the common case, and it is the
default. Six of the ten experiments in this project declined the thing they measured, which is
the house style working.

**Write an ADR** only when the result changes how the code is built from now on. The ADR
records that change and cites the verdict row for the evidence. If you cannot name what a
future contributor would do differently because of it, it is a verdict, not an ADR.

**Amend an existing record** rather than adding a new one when the subject already has an
owner. A dated amendment inside the ADR that owns the topic is preferred over a new number.
If a change makes a documented claim false, correct that claim in the same pull request:
that is part of the change, not unrelated editing.

## Format

Each ADR follows this structure:

- **Context** — what problem or decision point prompted this
- **Decision** — what was chosen
- **Consequences** — what the decision enables, what it costs, what it forecloses
- **Alternatives Considered** — what was ruled out and why
- **Downstream surfaces** — the files a change to this decision would move

Statuses: `Proposed` → `Accepted` → `Superseded` / `Deprecated`
