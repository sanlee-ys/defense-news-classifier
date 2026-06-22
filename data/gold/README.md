# Gold test set (human-labeled)

`gold.csv` is the v2 eval's honest anchor: 54 real DVIDS news snippets, **disjoint from the
retrieval corpus** (no leakage). Your hand labels are the ground truth that both the
classifier and the LLM judge get measured against. This is the human truth that replaces
v1's circular, model-made answer key.

## Your task: label all 54 rows

Open `gold.csv` (Excel is fine). For each row, read the **`text`** and fill in two columns:

- **`category`** — one of: `procurement` · `operations` · `policy` · `technology` · `industry`
- **`domain`** — one of: `air` · `land` · `sea` · `cyber` · `space` · `multi`

Leave `id`, `dvids_id`, `source_url`, and `text` as they are. (`source_url` is there if you
ever want to open the full article to decide.)

### What the labels mean

**category** (what the snippet is *primarily* about):
- `procurement` — contracts, acquisitions, budgets, program awards
- `operations` — active conflict, deployments, exercises, military operations
- `policy` — a decision or framework that *governs* defense: legislation, treaties, strategy / doctrine (NDS, Nuclear Posture Review, QDR), formal rule changes, posture testimony
- `technology` — R&D, new systems, autonomous / drone / AI developments
- `industry` — defense-company business: earnings, mergers, acquisitions

**domain** (the warfighting domain involved):
- `air` · `land` · `sea` · `cyber` · `space` · `multi` (joint / spans more than one)

### How to decide

Pick the **single best** label for each — the *"if I could file this in only one folder,
which?"* call. Go with your gut on the primary topic; don't agonize over borderline cases.
Those borderline calls are exactly what the eval is designed to surface, so an honest
gut-label is more useful than an overthought one.

### Tricky calls

- **`policy` = the rule, not the doing.** Label `policy` only when the story is about a
  policy/strategy/treaty/rule *itself* (its creation, change, review, or articulation). A
  unit or official *implementing*, *visiting*, or just *name-dropping* a policy is doing an
  **action** — usually `operations`. (A snippet can say "Nuclear Posture Review" and still be
  `operations` if it's really about someone carrying it out.)
- **No personnel bucket.** Appointments, nominations, and "who got the job" stories fit none
  of the five categories — **drop them** rather than forcing a label.
- **`procurement` vs `industry`.** A *purchase / contract award* (the buyer's side) is
  `procurement`; a *company's own business* (earnings, mergers, acquisitions) is `industry`.

## Notes

- **Excel-open is safe here.** Unlike `manifest.csv`, nothing auto-writes this file — the
  judge and eval only *read* it. Label, save, done.
- **Industry is likely absent.** These snippets come from the DoD news wire, which carries
  almost no company-business news. Backfill `industry` by hand: append rows at the next free
  ids (e.g. `g054`+) with short SEC snippets (different from the corpus's `901`–`906`), label
  them `industry`, and leave `dvids_id` blank.
