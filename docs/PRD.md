# Product Requirements Document — Defense News Classifier

**Version:** 1.0  
**Status:** Complete (v1)  
**Author:** San Lee  
**Last updated:** 2026-06-20

---

## 1. Problem Statement

Defense-related news and reports cover a wide range of topics — procurement decisions, active operations, policy shifts, technology developments, and industry news — across multiple warfighting domains. Manually categorizing this material is time-consuming and inconsistent across readers.

This project asks: *can a single well-prompted LLM call, with structured output, reliably classify a defense-news snippet into the right category and domain?* The answer, measured on a held-out labeled dataset, is the deliverable.

---

## 2. Goals

| # | Goal |
|---|------|
| G1 | Demonstrate a working LLM-based text classifier with rigorous, reproducible eval |
| G2 | Measure classification quality honestly, including failure modes and limitations |
| G3 | Keep the project small, completable, and fully reproducible by others |
| G4 | Serve as a portfolio artifact showing practical AI engineering judgment |

---

## 3. Non-Goals (v1)

The following are explicitly out of scope. They may be revisited in v2.

- Web UI or any user-facing interface
- Scraping, ingesting, or storing real news articles
- RAG / retrieval over a document corpus
- Model fine-tuning
- A third classification field (e.g., `region`)
- Authentication, multi-user support, or any production infrastructure

---

## 4. Users

This is a personal portfolio project. The primary audience is:

- **The author** — building and evaluating the system
- **Technical reviewers** — hiring managers, peers, or collaborators assessing the work

There are no end-users, no service-level requirements, and no operational deployment target.

---

## 5. Classification Schema

### 5.1 `category` — what the article is primarily about

| Label | Description |
|-------|-------------|
| `procurement` | Contracts, acquisitions, budgets, program awards |
| `operations` | Active conflict, deployments, military operations |
| `policy` | Legislation, treaties, strategy, doctrine |
| `technology` | R&D, new systems, autonomous/drone/AI developments |
| `industry` | Defense-company business, earnings, mergers |

### 5.2 `operational_domain` — the warfighting domain involved

| Label | Description |
|-------|-------------|
| `air` | Aircraft, air operations, airspace |
| `land` | Ground forces, land warfare |
| `sea` | Naval operations, maritime |
| `cyber` | Cybersecurity, information warfare |
| `space` | Space systems, satellites |
| `multi` | Joint or cross-domain operations |

Each article receives exactly one label per field. Multi-label output is not supported in v1.

---

## 6. Functional Requirements

### 6.1 Dataset Generator

| ID | Requirement |
|----|-------------|
| F1 | Generate synthetic, labeled defense-news snippets via LLM |
| F2 | Cover all 30 category × domain combinations |
| F3 | Produce at least 10 articles per combination (300 total) |
| F4 | Output a single CSV with columns: `text`, `category`, `operational_domain` |
| F5 | Use structured output (tool use / JSON schema) to guarantee valid labels |

### 6.2 Classifier

| ID | Requirement |
|----|-------------|
| F6 | Accept a plain-text article as input |
| F7 | Return `{category, operational_domain}` as structured JSON |
| F8 | Use a single LLM API call per article |
| F9 | Enforce valid label values at the API layer via schema validation |
| F10 | Be runnable as a standalone script for quick sanity checks |

### 6.3 Eval Harness

| ID | Requirement |
|----|-------------|
| F11 | Run the classifier against the full labeled dataset |
| F12 | Report overall accuracy for both fields |
| F13 | Report per-label precision, recall, and F1 for both fields |
| F14 | Produce confusion matrices for both fields |
| F15 | Output a log of every misclassified article |
| F16 | Support resuming an interrupted eval run without re-classifying articles already processed |

---

## 7. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| N1 | All data is synthetic — no proprietary, scraped, or non-public text |
| N2 | API key read from environment variable; never hardcoded |
| N3 | Fully reproducible: pinned dependencies via `uv.lock` |
| N4 | No ML framework dependencies — plain Python + `anthropic` + `pandas` |
| N5 | Each script runnable and inspectable independently |

---

## 8. Success Criteria (Definition of Done — v1)

- [ ] Generator produces a labeled CSV of ≥ 300 synthetic articles covering all 30 label combinations
- [ ] Classifier accepts arbitrary article text and returns a valid structured prediction
- [ ] Eval produces accuracy, per-label precision/recall/F1, confusion matrices, and a misclassification log
- [ ] README leads with the eval numbers and explains the design and limitations honestly
- [ ] Test suite passes with mocked API calls (no live key required to run tests)

---

## 9. Known Limitations

These are documented here and in the README — not omissions, but honest constraints.

- **Circular eval:** the same model generates and classifies the data. The numbers measure in-distribution consistency, not generalization to real-world news.
- **Single-label constraint:** articles spanning two categories (e.g., a procurement story about drones — both `procurement` and `technology`) receive one forced label.
- **Synthetic text uniformity:** generated snippets are stylistically more uniform than real news, which could inflate performance.
- **`multi` domain ambiguity:** `multi` acts as a catch-all for joint operations, making it easier to recall but harder to be precise about.

---

## 10. v2 Considerations (Deferred)

- Add a `region` field: `indo-pacific`, `europe`, `middle-east`, `americas`, `africa`, `global`
- Eval against human-labeled real news articles
- RAG over a small corpus of public defense reports
- Thin Streamlit UI for interactive demos
