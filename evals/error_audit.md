# Error analysis — auditing the 67 misclassifications

*Purpose: separate **genuine classifier errors** from **label-scheme ambiguity**, so the
gap between 79% category accuracy and 100% can be attributed honestly. This directly
addresses the "model-asserted ground truth" limitation — if the answer key itself is
debatable on a case, a "wrong" prediction isn't really the model's fault.*

> **Status: proposed reads, pending human ratification.** The verdicts below are a manual
> pass over every miss, but they are still *my* adjudication. Where the label scheme is
> genuinely ambiguous I say so rather than crowning a winner. Treat the "Proposed read"
> column as a starting point to agree with or override, not a second answer key.

---

## Where the errors are

Of 67 misclassified articles: **63 are category misses, 8 are domain misses** (4 articles
miss on both fields).

**Category — true → predicted (63 misses):**

| Count | Transition |
|---|---|
| 35 | `industry` → `procurement` |
| 12 | `industry` → `technology` |
| 10 | `technology` → `procurement` |
| 3  | `operations` → `technology` |
| 2  | `policy` → `procurement` |
| 1  | `operations` → `cyber` (invalid — see below) |

**Domain — true → predicted (8 misses):**

| Count | Transition |
|---|---|
| 2 | `cyber` → `multi` |
| 1 | `air` → `multi` |
| 1 | `land` → `cyber` |
| 1 | `cyber` → `air` |
| 1 | `cyber` → `land` |
| 1 | `cyber` → `sea` |
| 1 | `cyber` → `space` |

---

## The headline

**57 of the 63 category misses (90%) live in one triangle: `industry` / `procurement` /
`technology`.** Every one is a defense company doing something with money and a system —
"BAE wins a £3.1B contract to deliver Typhoons," "Elbit unveils a new UAV," "the Army awards
a contract to *develop* an AI targeting module." By our own definitions these match two
labels at once:

- `procurement` = *contracts, acquisitions, budgets, program awards*
- `industry` = *defense-company business, earnings, mergers*
- `technology` = *R&D, new systems, autonomous/drone/AI developments*

A company winning a contract is **both** "a company's business" (industry) **and** "a
program award" (procurement). The generator picked one; the classifier picked the other.
That isn't the model being dumb — it's the **label scheme having overlapping definitions**,
and a short snippet rarely carries the signal to break the tie the way the answer key did.

The same is true on the domain side: **5 of 8 domain misses are cyber-vs-platform** — a
cyber/EW system *for* a tank, ship, satellite, or aircraft. Our own domain definitions file
"electronic warfare" under `cyber`, so a counter-drone EW suite bolted to a howitzer is
defensible as either `cyber` or `land`.

**So the honest read: of 67 misses, exactly one (id 95) is an unambiguous defect. The rest
sit on contestable boundaries.** You could reasonably re-tag a few of the cyber-domain cases
(270, 275, 277, 279 — where the article's *subject* is plainly the cyber system, not the
platform) as outright classifier errors. Even on the strictest reading, the clear-error
count stays small: **the bulk of the 21-point category gap is label overlap, not model
horsepower.** That is exactly why macro-F1 (0.765) and the `industry`/`procurement`
discussion already lead the README — this audit quantifies *why*.

---

## The one real defect: an out-of-enum prediction (id 95)

Article 95 (a North-Korean cyber-intrusion story; true labels `operations` / `cyber`) came
back with **`category="cyber"` — which is not a valid category at all.** The model echoed the
topic word into the category slot.

This matters beyond one row, because it falsifies a claim the README and case study made:
that tool-use makes the API *reject* out-of-enum output "at the API layer." It does not.
**An Anthropic tool `input_schema` enum is a strong guide for the model, not a hard
server-side constraint** (it is not constrained decoding). The enum makes violations rare —
1 in 300 here — but `classify()` returns `tool_block.input` *without validating it*, so the
bad value passed straight into the metrics.

**Fixes (recommended):**
1. Correct the wording in `README.md` and `docs/CASE_STUDY.md` — tool-use enforces *shape*
   (you always get the two fields), and *strongly biases* toward the enum, but does not
   guarantee enum membership.
2. Add a defensive check in `classify()` that validates the returned labels against
   `CATEGORIES` / `DOMAINS` and raises (or flags) on a miss — so the guarantee is real *in
   our code*, where we can actually enforce it. Cover it with a unit test.

---

## Per-case detail

| ID | Field | True → Pred | Proposed read |
|---|---|---|---|
| 62 | domain | `air` → `multi` | boundary — joint/cross-service vs single dominant domain |
| 67 | category | `operations` → `technology` | boundary — a live-fire *test/eval* of a new system, not a deployment |
| 81 | category | `operations` → `technology` | boundary — a live-fire *test/eval* of a new system, not a deployment |
| 94 | domain | `cyber` → `multi` | boundary — cyber subject vs the physical platform it runs on (our defs file EW under *cyber*) |
| 95 | category | `operations` → `cyber` | **out-of-enum** — invalid category; genuine classifier error |
| 106 | category | `operations` → `technology` | boundary — a live-fire *test/eval* of a new system, not a deployment |
| 128 | category | `policy` → `procurement` | boundary — a procurement decision wrapped in a policy framework |
| 138 | category | `policy` → `procurement` | boundary — a procurement decision wrapped in a policy framework |
| 183 | category | `technology` → `procurement` | boundary — a contract to *develop* new tech reads as either |
| 191 | category | `technology` → `procurement` | boundary — a contract to *develop* new tech reads as either |
| 196 | domain | `land` → `cyber` | boundary — cyber subject vs the physical platform it runs on (our defs file EW under *cyber*) |
| 204 | category | `technology` → `procurement` | boundary — a contract to *develop* new tech reads as either |
| 213 | category | `technology` → `procurement` | boundary — a contract to *develop* new tech reads as either |
| 215 | category | `technology` → `procurement` | boundary — a contract to *develop* new tech reads as either |
| 217 | category | `technology` → `procurement` | boundary — a contract to *develop* new tech reads as either |
| 218 | category | `technology` → `procurement` | boundary — a contract to *develop* new tech reads as either |
| 221 | category | `technology` → `procurement` | boundary — a contract to *develop* new tech reads as either |
| 229 | category | `technology` → `procurement` | boundary — a contract to *develop* new tech reads as either |
| 239 | category | `technology` → `procurement` | boundary — a contract to *develop* new tech reads as either |
| 240 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 241 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 242 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 244 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 245 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 246 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 247 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 248 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 249 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 250 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 252 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 253 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 254 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 255 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 256 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 257 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 258 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 260 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 264 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 265 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 266 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 267 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 268 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 269 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 270 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 270 | domain | `cyber` → `air` | boundary — cyber subject vs the physical platform it runs on (our defs file EW under *cyber*) |
| 272 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 273 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 273 | domain | `cyber` → `land` | boundary — cyber subject vs the physical platform it runs on (our defs file EW under *cyber*) |
| 275 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 275 | domain | `cyber` → `multi` | boundary — cyber subject vs the physical platform it runs on (our defs file EW under *cyber*) |
| 276 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 277 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 277 | domain | `cyber` → `sea` | boundary — cyber subject vs the physical platform it runs on (our defs file EW under *cyber*) |
| 278 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 279 | domain | `cyber` → `space` | boundary — cyber subject vs the physical platform it runs on (our defs file EW under *cyber*) |
| 280 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 281 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 282 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 285 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 286 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 287 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 288 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 289 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 290 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 293 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |
| 294 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 295 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 296 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 297 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 298 | category | `industry` → `procurement` | boundary — contract/award language fits *procurement* as well as *industry* |
| 299 | category | `industry` → `technology` | boundary — company product-launch of a new system fits *technology* too |

---

*Generated from `evals/misclassifications.csv`. Re-run the audit by regenerating that file
(`uv run python src/eval.py`) and re-bucketing.*
