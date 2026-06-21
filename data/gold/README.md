# Gold test set (human-labeled)

`gold.csv` is the v2 eval's honest anchor: 45 real DVIDS news snippets, **disjoint from the
retrieval corpus** (no leakage). Your hand labels are the ground truth that both the
classifier and the LLM judge get measured against. This is the human truth that replaces
v1's circular, model-made answer key.

## Your task: label all 45 rows

Open `gold.csv` (Excel is fine). For each row, read the **`text`** and fill in two columns:

- **`category`** — one of: `procurement` · `operations` · `policy` · `technology` · `industry`
- **`domain`** — one of: `air` · `land` · `sea` · `cyber` · `space` · `multi`

Leave `id`, `dvids_id`, `source_url`, and `text` as they are. (`source_url` is there if you
ever want to open the full article to decide.)

### What the labels mean

**category** (what the snippet is *primarily* about):
- `procurement` — contracts, acquisitions, budgets, program awards
- `operations` — active conflict, deployments, exercises, military operations
- `policy` — legislation, treaties, strategy, doctrine, testimony
- `technology` — R&D, new systems, autonomous / drone / AI developments
- `industry` — defense-company business: earnings, mergers, acquisitions

**domain** (the warfighting domain involved):
- `air` · `land` · `sea` · `cyber` · `space` · `multi` (joint / spans more than one)

### How to decide

Pick the **single best** label for each — the *"if I could file this in only one folder,
which?"* call. Go with your gut on the primary topic; don't agonize over borderline cases.
Those borderline calls are exactly what the eval is designed to surface, so an honest
gut-label is more useful than an overthought one.

## Notes

- **Excel-open is safe here.** Unlike `manifest.csv`, nothing auto-writes this file — the
  judge and eval only *read* it. Label, save, done.
- **Industry is likely absent.** These snippets come from the DoD news wire, which carries
  almost no company-business news, so you may not find any `industry` items. That's fine. If
  you want the eval to cover `industry` too, append a few rows (ids `g046`, `g047`, …) with
  short SEC snippets and label them `industry` — optional.
