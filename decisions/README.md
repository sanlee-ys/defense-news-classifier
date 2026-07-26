# Architecture Decision Log

Decisions are recorded here as they are made. Each ADR captures the context, the decision, and the consequences — including trade-offs accepted.

| # | Title | Status |
|---|-------|--------|
| [001](001-llm-provider.md) | Use Anthropic API with claude-sonnet-4-6 | Accepted |
| [002](002-structured-output-via-tool-use.md) | Enforce structured output via tool use, not prompt engineering | Accepted |
| [003](003-synthetic-data-only.md) | Use synthetic data only — no real news articles | Accepted |
| [004](004-no-ml-framework-for-eval.md) | Implement eval metrics in plain Python — no ML framework | Accepted |
| [005](005-agentic-prompt-optimization-loop.md) | Optimize the classifier prompt with an autonomous, error-driven agent, guarded by a 3-way split | Accepted |
| [006](006-autonomy-ladder-portfolio-spine.md) | Make an autonomy ladder the portfolio spine, with the classifier as the single protagonist | Accepted |
| [007](007-evals-as-ci-gate.md) | Wire the v2 gold-set evals into CI as a two-gate quality gate, split by API cost and fork-PR secret safety | Accepted |
| [008](008-strict-structured-outputs.md) | Enforce enum validity server-side with `strict: true`, retire the client-side re-sample | Accepted |
| [009](009-message-batches-for-bulk-runs.md) | Add a Message Batches API path for non-latency-sensitive bulk classification | Accepted |
| [010](010-rag-path-model-pin.md) | Pin the RAG-grounded path to claude-sonnet-4-6 after the Sonnet-5 workhorse migration | Superseded by [012](012-retire-bm25-grounding.md) |
| [011](011-reaim-tiered-routing-technology-operations.md) | Re-aim v2.2.0 tiered routing at technology-vs-operations, not industry-vs-procurement | Closed by [013](013-decline-tiered-routing.md) |
| [012](012-retire-bm25-grounding.md) | Retire BM25 retrieval grounding — it no longer pays under the improved prompt | Accepted |
| [013](013-decline-tiered-routing.md) | Decline tiered model routing — measured, it buys nothing at ~2x the cost | Accepted |
| [014](014-region-field-design.md) | Region field design — six labels with a `global` catch-all, gold-first scope | Accepted |
| [015](015-public-domain-data-sourcing.md) | All text is public-domain or synthetic — DVIDS + SEC + generated, never scraped or licensed | Accepted |
| [016](016-claude-code-action-pr-review.md) | Agentic PR review as an advisory lane, not a gate — comments only, never fails the build; **on-demand via `@claude` only** since 2026-07-26 (Amendment 1) | Accepted |
| [017](017-classical-baseline-bakeoff.md) | Classical ML baseline bake-off — TF-IDF+logreg measured; the LLM wins by 20+ points, the spend is justified with a number | Accepted |
| [018](018-agent-driven-ml-loop.md) | Rung 2: agent-driven ML loop on the bake-off substrate — rung 1's A/B/C + done-signal architecture reused as shared code | Accepted |
| [019](019-knn-exemplar-fewshot.md) | kNN-exemplar few-shot — measured and declined as a clean null (n=300 paired, p=0.70); completes the three-shape retrieval series | Accepted |
| [020](020-l4-multi-agent-pipeline.md) | L4 built + measured: the backward edge fixed 6/7 of the named cluster, but the over-challenging critic did net harm (scale domain p=0.016) at 4× cost — declined as configured | Accepted |

## Format

Each ADR follows this structure:

- **Context** — what problem or decision point prompted this
- **Decision** — what was chosen
- **Consequences** — what the decision enables, what it costs, what it forecloses
- **Alternatives Considered** — what was ruled out and why

Statuses: `Proposed` → `Accepted` → `Superseded` / `Deprecated`
