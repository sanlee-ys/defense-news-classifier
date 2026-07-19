# ADR-015: All text in this repo is public-domain or synthetic

**Status:** Accepted
**Date:** 2026-07-19
**Deciders:** San Lee

---

## Context

This constraint has governed every dataset in the project since v2, and until now it was
**asserted in four places and decided in none**:

- `README.md:12` — "public-domain text (DoD news wire + SEC filings)"
- `README.md:383-384` — "sources that are legitimately free to use"
- `README.md:366` — "All data is synthetic: no proprietary text, no scraping, no real news sources" *(scoped to the v1 section; now misleading out of context)*
- `docs/PRD.md` N1 — "All data is synthetic — no proprietary, scraped, or non-public text"

Two problems with leaving it there.

**It is partly stale where it is written.** N1 and the v1 line both say *all data is
synthetic*. That stopped being true at v2, when 62 real documents landed. The rule that
actually survived is narrower and different: not *synthetic only*, but *public-domain or
synthetic, never scraped or licensed*.

**A requirement is not a decision.** N1 records what is required without recording what was
rejected or why, so a future session weighing "should we add a few Reuters snippets to fix
the operations skew?" finds a rule with no reasoning attached and no alternatives table.
[ADR-003](003-synthetic-data-only.md) is the nearest thing, but its amendment explicitly
notes this is out of its scope — it governs the *synthetic* corpus.

The trigger for writing it down now: the [ML baseline bake-off](../docs/specs/ml-baseline-bakeoff.md)
introduces a training set, and "where may training data come from" is exactly the question
this rule answers.

## Decision

**Every piece of text in this repository is either public domain or synthetic. No scraped,
licensed, paywalled, or otherwise proprietary text, ever — including in training data.**

Permitted sources:

| Source | Why it qualifies |
|---|---|
| **DVIDS** (Defense Visual Information Distribution Service) | U.S. government public-affairs works, public domain by 17 U.S.C. § 105. Retrieved via the official API, not scraped. |
| **SEC filings** | U.S. government documents, public domain. Hand-pulled. |
| **LLM-generated synthetic text** | Authored for this repo ([ADR-003](003-synthetic-data-only.md)). |

This binds the **repository**, not just the eval: the corpus is committed and the repo is
public, so every source is redistributed to anyone who clones it. A source that is merely
*readable* is not thereby *redistributable*.

## Consequences

- **Licensing is not a per-dataset judgment call.** Any new dataset either comes from the
  table above or needs a superseding ADR. No case-by-case reasoning about fair use.
- **The DVIDS skew is a permanent, accepted measurement cost.** The wire is
  operations-heavy: `operations` is 66% of the 300-snippet scaled set and `industry` is a
  single snippet, which is why that run documents its category macro-F1 as **uninformative**
  and reports overall accuracy plus the well-populated per-label rows instead. The region
  axis inherits the same problem — `europe` n=1, `africa` n=2 on the gold set. **This is a
  cost of the sourcing rule, not a flaw in the eval**, and it should be described that way
  rather than apologized for. Fixing the skew by adding commercial newswire text is the one
  fix this ADR forecloses.
- **"Just add a few real articles" is closed.** Reuters, Defense News, Breaking Defense, and
  every other commercial outlet are out — not on cost or complexity grounds, which is how
  [ADR-003](003-synthetic-data-only.md) framed it in June and which has since expired, but on
  redistribution grounds, which have not.
- **The baseline bake-off's training data is already governed.** The 300-snippet judge-graded
  set is DVIDS, so it qualifies. No separate sourcing decision is needed for that work.
- **Two surfaces now under-describe the rule** and should be corrected when next touched:
  PRD N1 ("all data is synthetic") and `README.md:366`, both of which predate v2. Neither is
  wrong about the *spirit*; both are wrong about the *fact*.

## Downstream surfaces

Surfaces this decision touches, and their state as of 2026-07-19:

| Surface | State |
|---|---|
| `docs/PRD.md` N1 — "All data is synthetic — no proprietary, scraped, or non-public text" | **Stale.** True at v1, wrong since v2. Should become "public-domain or synthetic," citing this ADR. Not edited here: the PRD is a versioned requirements doc and rewriting a numbered requirement is its own change. |
| `README.md:366` — "All data is synthetic: no proprietary text, no scraping, no real news sources" | **Stale out of context.** Correct *within* the v1 section it sits in, misleading to a reader who lands on it. Same treatment as N1. |
| `README.md:12`, `:33`, `:383-384`, `:704` | Accurate. These already describe public-domain sourcing and need no change. |
| `data/gold/README.md` | Accurate. Describes DVIDS + SEC provenance; now has an ADR to cite. |
| [ADR-003](003-synthetic-data-only.md) | Amended 2026-07-19 to point here for real-text sourcing. Done. |
| [`docs/specs/ml-baseline-bakeoff.md`](../docs/specs/ml-baseline-bakeoff.md) | Its training set (the 300-snippet judge-graded DVIDS set) is governed by this ADR. No separate sourcing call needed. |
| Any future corpus expansion | Gated by this ADR. A new source needs a superseding record, not a judgment call. |

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Leave it in the PRD as requirement N1 | A requirement records what is mandated, not what was rejected or why. The next person weighing a licensed source finds no reasoning and no alternatives, so the rule gets re-litigated from scratch — the failure ADRs exist to prevent. N1 is also now factually wrong ("all data is synthetic"). |
| Allow commercial news under fair use for research | Fair use is a defense, not a permission, and it is weakest exactly here: the repo is public and redistributes full text. A portfolio project is not worth a licensing question, and "probably fine" is not a standard this repo applies to anything else it measures. |
| Allow scraping public-web defense news | Public to read is not public to redistribute. Also adds a scraper to maintain and a robots/ToS surface, for text whose license is still unresolved. |
| Broaden sources to fix the operations skew | The skew is real and it costs a usable category macro-F1. But buying balance with a licensing problem trades a *documented* measurement limit for an *undocumented* legal one. The honest fix is more public-domain breadth (other government wires) or stating the limit, which is what the scaled eval does. |
| Say nothing and let ADR-003 imply it | ADR-003 governs the synthetic corpus and its amendment says so explicitly. Reading a real-text sourcing rule into it is exactly the kind of inference that made this constraint homeless in the first place. |
