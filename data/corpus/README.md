# Corpus (v2 retrieval source)

Real, short, **public-domain** defense items that v2 retrieves over to ground a
classification and return a citation. This is the *retrieval corpus*, not the test set:
the hand-labeled gold snippets that measure quality (Step 2) are kept **separate** so we
never retrieve the exact article we are classifying (that would be leakage).

## The two hard rules

1. **Public-domain text only.** U.S. government works (defense.gov, the service branches,
   DARPA, DVIDS, etc.) are public domain and safe to commit here. Do **not** paste the body
   of copyrighted commercial news (Defense News, Breaking Defense, Reuters, etc.) into this
   repo. When in doubt, link it in the manifest but don't copy the text.
2. **Record where it came from.** Every doc needs a `source_url` and a `published_date` in
   the manifest. That is what makes a returned citation real.

## How to add a document

1. Save the article **body** as `data/corpus/NNN-short-slug.txt` (plain UTF-8). Trim nav,
   menus, "related stories", and footers; a headline as the first line is fine. Keep it
   short, the way a release actually reads (~1-5 paragraphs). See `_TEMPLATE.txt`.
2. Add one row to `manifest.csv`. **The manifest is the source of truth** — only docs listed
   there get indexed, so a stray file (like `_TEMPLATE.txt`) is simply ignored.

## Manifest columns

| column | required | meaning |
|---|---|---|
| `id` | yes | filename stem, e.g. `014-darpa-autonomous-resupply` |
| `title` | yes | the headline |
| `source` | yes | publisher host, e.g. `defense.gov`, `darpa.mil` |
| `source_url` | yes | full URL the text came from |
| `published_date` | yes | `YYYY-MM-DD` |
| `license` | yes | `public-domain-usgov` for U.S. gov works |
| `category` | recommended | best-guess v1 category (see below) — used only to track coverage |
| `domain` | recommended | best-guess v1 domain — used only to track coverage |
| `notes` | no | anything worth remembering |

`category` and `domain` are not labels the classifier sees; they just help us collect a set
that actually spans the label space instead of 40 operations stories.

### Worked example

`data/corpus/014-darpa-autonomous-resupply.txt`:

```
DARPA Selects Performers for Autonomous Ground Resupply Program

The Defense Advanced Research Projects Agency has selected three teams to develop
autonomous ground vehicles for contested-logistics resupply ...
```

`manifest.csv` row:

```
014-darpa-autonomous-resupply,DARPA Selects Performers for Autonomous Ground Resupply Program,darpa.mil,https://www.darpa.mil/news/...,2026-05-12,public-domain-usgov,technology,land,
```

## Target

Aim for **~30-50 docs**, roughly spread across the five categories and six domains. Perfect
balance is not needed, but try for a handful of each category so retrieval has something
relevant to surface for every kind of article.

## Where to find public-domain text (mapped to the label space)

Hand-collecting in a browser sidesteps the bot-blocking that stops automated fetchers, and
these are all public domain:

| category | good public-domain sources |
|---|---|
| `procurement` | **defense.gov/News/Contracts** (daily contract awards — short, abundant, ideal) |
| `operations` | defense.gov releases, the combatant commands (CENTCOM/EUCOM/INDOPACOM), DVIDS |
| `policy` | DoD strategy/posture statements, defense.gov policy releases, White House |
| `technology` | **darpa.mil/news**, service research labs (AFRL, ARL, ONR) |
| `industry` | *hardest to source clean.* Company business news is mostly copyrighted. The clean option is **SEC EDGAR** (sec.gov/edgar) filing text — public records covering earnings/mergers. Expect this category to stay lighter than the others. |

| domain | good public-domain sources |
|---|---|
| `air` | af.mil |
| `land` | army.mil |
| `sea` | navy.mil |
| `space` | spaceforce.mil, spacecom |
| `cyber` | cybercom, NSA/CISA releases |
| `multi` | joint commands, OSD/defense.gov joint announcements |

> **Heads-up on `industry`:** it was v1's worst category (recall 0.22) *and* it is the hardest
> to source as public-domain text. If clean industry docs are scarce, that is fine to note as a
> known corpus gap rather than padding it with copyrighted text.
