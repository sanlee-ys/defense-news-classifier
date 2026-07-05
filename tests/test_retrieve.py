"""
Tests for src/retrieve.py.

No network or API: a tiny corpus is written to a temp dir, so these check the
real loading / dedup / ranking logic offline.
"""

import csv

import pytest

import retrieve
from retrieve import Retriever, load_corpus

MANIFEST_COLUMNS = [
    "id",
    "title",
    "source",
    "source_url",
    "published_date",
    "license",
    "category",
    "domain",
    "notes",
]


def _row(doc_id, title="", category="", domain=""):
    return {
        "id": doc_id,
        "title": title,
        "source": "test",
        "source_url": f"http://example/{doc_id}",
        "published_date": "2024-01-01",
        "license": "public-domain-usgov",
        "category": category,
        "domain": domain,
        "notes": "",
    }


def _write_manifest(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def corpus_dir(tmp_path):
    """A 3-doc corpus split across both manifests, with a missing file and a dup."""
    # Main manifest: two real docs + one row whose .txt is absent (must be skipped).
    _write_manifest(
        tmp_path / "manifest.csv",
        [
            _row("001-alpha", "Alpha drone contract", "procurement", "air"),
            _row("002-bravo", "Bravo carrier ship", "operations", "sea"),
            _row("003-missing", "No file here", "policy", "land"),
        ],
    )
    (tmp_path / "001-alpha.txt").write_text(
        "drone contract award unmanned aircraft procurement", encoding="utf-8"
    )
    (tmp_path / "002-bravo.txt").write_text(
        "aircraft carrier strike group at sea naval operations", encoding="utf-8"
    )
    # Manual manifest: one new doc + a duplicate of 001-alpha (must not double-load).
    _write_manifest(
        tmp_path / "manifest_manual.csv",
        [
            _row("901-charlie", "Charlie earnings", "industry", "multi"),
            _row("001-alpha", "dup", "procurement", "air"),
        ],
    )
    (tmp_path / "901-charlie.txt").write_text(
        "company quarterly earnings revenue backlog dividend", encoding="utf-8"
    )
    return tmp_path


# --- _tokenize -----------------------------------------------------------


def test_tokenize_lowercases_and_splits():
    assert retrieve._tokenize("F-35 Contract!") == ["f", "35", "contract"]


# --- load_corpus ---------------------------------------------------------


def test_load_corpus_reads_both_manifests(corpus_dir):
    ids = {doc.id for doc in load_corpus(corpus_dir)}
    assert ids == {"001-alpha", "002-bravo", "901-charlie"}


def test_load_corpus_skips_missing_files_and_dedupes(corpus_dir):
    docs = load_corpus(corpus_dir)
    # 003-missing dropped (no .txt); 001-alpha loaded once despite the dup row.
    assert len(docs) == 3
    assert sum(doc.id == "001-alpha" for doc in docs) == 1


def test_load_corpus_populates_metadata(corpus_dir):
    alpha = next(doc for doc in load_corpus(corpus_dir) if doc.id == "001-alpha")
    assert alpha.category == "procurement"
    assert alpha.domain == "air"
    assert alpha.source_url == "http://example/001-alpha"
    assert "drone" in alpha.text


def test_load_corpus_skips_a_manifest_file_that_does_not_exist(tmp_path):
    # Only the auto manifest is written; manifest_manual.csv is entirely absent
    # (not just empty), which is the branch a corpus_dir with both files can't hit.
    _write_manifest(
        tmp_path / "manifest.csv",
        [_row("001-alpha", "Alpha drone contract", "procurement", "air")],
    )
    (tmp_path / "001-alpha.txt").write_text("drone contract", encoding="utf-8")
    docs = load_corpus(tmp_path)
    assert [doc.id for doc in docs] == ["001-alpha"]


# --- Retriever -----------------------------------------------------------


def test_retriever_ranks_lexical_match_first(corpus_dir):
    hits = Retriever(load_corpus(corpus_dir)).retrieve("drone contract", k=1)
    assert len(hits) == 1
    assert hits[0].doc.id == "001-alpha"


def test_retriever_finds_industry_doc(corpus_dir):
    hits = Retriever(load_corpus(corpus_dir)).retrieve("earnings dividend backlog", k=1)
    assert hits[0].doc.id == "901-charlie"


def test_retriever_respects_k(corpus_dir):
    assert len(Retriever(load_corpus(corpus_dir)).retrieve("operations", k=2)) == 2


def test_retriever_empty_corpus_raises():
    with pytest.raises(ValueError):
        Retriever([])


# --- _snippet --------------------------------------------------------------


def test_snippet_flattens_internal_whitespace():
    assert retrieve._snippet("line one\n  line   two") == "line one line two"


def test_snippet_leaves_short_text_untruncated():
    text = "short enough"
    assert retrieve._snippet(text, width=160) == text


def test_snippet_truncates_and_marks_long_text():
    text = "x" * 200
    snippet = retrieve._snippet(text, width=160)
    assert snippet == "x" * 160 + "..."


# --- main (CLI) --------------------------------------------------------------


def test_main_prints_top_hit_for_query(monkeypatch, capsys, corpus_dir):
    monkeypatch.setattr(retrieve, "load_corpus", lambda: load_corpus(corpus_dir))
    monkeypatch.setattr("sys.argv", ["retrieve.py", "drone contract", "--k", "1"])

    exit_code = retrieve.main()

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "corpus: 3 docs" in out
    assert "001-alpha" in out
    assert "procurement/air" in out
    assert "http://example/001-alpha" in out
