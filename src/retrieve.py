"""BM25 retrieval over the v2 corpus.

Loads the documents catalogued in ``data/corpus/manifest*.csv``, indexes each with
BM25 (rank-bm25), and returns the top-k most relevant docs for a query -- each carrying
the citation metadata (source + url + date) needed to ground a classification.

Why BM25 and not embeddings: it is pure-Python, needs no extra API key or model
download, and is the honest "start simple, measure first" baseline. If the eval later
shows retrieval quality is the bottleneck, that is the moment to reach for embeddings.

Why whole-doc indexing (no chunking): the corpus is short news items (~1-4 KB), so a
document is already a sensible retrieval unit. Chunking is a later refinement if docs
grow long.

CLI:
    uv run python src/retrieve.py "drone contract" --k 3

Importable:
    from retrieve import Retriever, load_corpus
    retriever = Retriever(load_corpus())
    hits = retriever.retrieve("hypersonic missile test", k=3)
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

CORPUS_DIR = Path(__file__).resolve().parent.parent / "data" / "corpus"
MANIFESTS = ("manifest.csv", "manifest_manual.csv")


@dataclass(frozen=True)
class Doc:
    """A corpus document plus the metadata a citation needs."""

    id: str
    title: str
    text: str
    category: str
    domain: str
    source: str
    source_url: str
    published_date: str


@dataclass(frozen=True)
class Hit:
    """A retrieved document and its BM25 relevance score."""

    doc: Doc
    score: float


def _tokenize(text: str) -> list[str]:
    """Lowercase and split on non-alphanumerics -- a plain BM25 tokenizer."""
    return re.findall(r"[a-z0-9]+", text.lower())


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> list[Doc]:
    """Load every doc listed across the manifests (auto + hand-collected).

    Args:
        corpus_dir: Directory containing the corpus manifests and ``<id>.txt``
            files. Defaults to ``data/corpus`` at the repo root.

    Returns:
        One :class:`Doc` per manifest row, deduplicated by id and skipping any
        row whose text file is missing.
    """
    docs: list[Doc] = []
    seen: set[str] = set()
    for manifest_name in MANIFESTS:
        manifest = corpus_dir / manifest_name
        if not manifest.exists():
            continue
        with manifest.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                doc_id = (row.get("id") or "").strip()
                path = corpus_dir / f"{doc_id}.txt"
                if not doc_id or doc_id in seen or not path.exists():
                    continue
                seen.add(doc_id)
                docs.append(
                    Doc(
                        id=doc_id,
                        title=(row.get("title") or "").strip(),
                        text=path.read_text(encoding="utf-8"),
                        category=(row.get("category") or "").strip(),
                        domain=(row.get("domain") or "").strip(),
                        source=(row.get("source") or "").strip(),
                        source_url=(row.get("source_url") or "").strip(),
                        published_date=(row.get("published_date") or "").strip(),
                    )
                )
    return docs


class Retriever:
    """A BM25 index over a list of docs, exposing top-k retrieval."""

    def __init__(self, docs: list[Doc]) -> None:
        """Build a BM25 index over ``docs``.

        Args:
            docs: Corpus documents to index; must be non-empty.

        Raises:
            ValueError: If ``docs`` is empty.
        """
        if not docs:
            raise ValueError("empty corpus: no documents loaded from data/corpus/")
        self.docs = docs
        self._bm25 = BM25Okapi([_tokenize(doc.text) for doc in docs])

    def retrieve(self, query: str, k: int = 3) -> list[Hit]:
        """Return the k highest-scoring docs for the query.

        Args:
            query: Free-text search query.
            k: Number of top documents to return.

        Returns:
            The top ``k`` hits, ranked by descending BM25 score.
        """
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(zip(self.docs, scores), key=lambda pair: pair[1], reverse=True)
        return [Hit(doc=doc, score=float(score)) for doc, score in ranked[:k]]


def _snippet(text: str, width: int = 160) -> str:
    """Flatten whitespace in ``text`` and truncate it to ``width`` chars for display."""
    flat = " ".join(text.split())
    return flat[:width] + ("..." if len(flat) > width else "")


def main() -> int:
    """CLI entry point: run a BM25 query against the corpus and print the top-k hits.

    Returns:
        Exit code (``0`` on success).
    """
    parser = argparse.ArgumentParser(description="BM25 retrieval over the v2 corpus.")
    parser.add_argument("query", help="the search query")
    parser.add_argument("--k", type=int, default=3, help="number of docs to return")
    args = parser.parse_args()

    retriever = Retriever(load_corpus())
    print(f"corpus: {len(retriever.docs)} docs\n")
    for rank, hit in enumerate(retriever.retrieve(args.query, k=args.k), start=1):
        doc = hit.doc
        print(
            f"#{rank}  score={hit.score:.2f}  [{doc.category}/{doc.domain}]  {doc.id}"
        )
        print(f"    {doc.title}")
        print(f"    {doc.source_url}")
        print(f"    {_snippet(doc.text)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
