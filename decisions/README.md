# Architecture Decision Log

Decisions are recorded here as they are made. Each ADR captures the context, the decision, and the consequences — including trade-offs accepted.

| # | Title | Status |
|---|-------|--------|
| [001](001-llm-provider.md) | Use Anthropic API with claude-sonnet-4-6 | Accepted |
| [002](002-structured-output-via-tool-use.md) | Enforce structured output via tool use, not prompt engineering | Accepted |
| [003](003-synthetic-data-only.md) | Use synthetic data only — no real news articles | Accepted |
| [004](004-no-ml-framework-for-eval.md) | Implement eval metrics in plain Python — no ML framework | Accepted |
| [005](005-agentic-prompt-optimization-loop.md) | Optimize the classifier prompt with an autonomous, error-driven agent, guarded by a 3-way split | Proposed |
| [006](006-autonomy-ladder-portfolio-spine.md) | Make an autonomy ladder the portfolio spine, with the classifier as the single protagonist | Accepted |

## Format

Each ADR follows this structure:

- **Context** — what problem or decision point prompted this
- **Decision** — what was chosen
- **Consequences** — what the decision enables, what it costs, what it forecloses
- **Alternatives Considered** — what was ruled out and why

Statuses: `Proposed` → `Accepted` → `Superseded` / `Deprecated`
