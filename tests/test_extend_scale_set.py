"""Tests for scripts/extend_scale_set.py (the DVIDS snippet-set extension).

Offline: ``select`` and ``number`` are pure by design so the collection *rules* can be
verified without a key or a network, and ``main``'s early exits are exercised the same
way. Nothing here calls DVIDS.

The rule worth the most is text de-duplication. ADR-023 discovered its four duplicate
groups only after they had been judge-graded, and one of them (s024/s025) is identical
text the answer key labels two different regions -- an unwinnable row for any
classifier, bought and paid for. Doing it before collection is the cheap fix, so it is
pinned here in both directions: against the frozen set and within the new batch.
"""

import csv
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
)

import extend_scale_set as ext  # noqa: E402


def _result(asset_id, title="Carrier strike group operates in the South China Sea"):
    return {
        "id": asset_id,
        "title": title,
        "short_description": f"Snippet {asset_id}. " + "x" * ext.MIN_SNIPPET,
        "url": f"https://www.dvidshub.net/news/{asset_id}",
    }


def _select(results, exclude=None, texts=None, ids=None, limit=100):
    return ext.select(results, exclude or set(), texts or set(), ids or set(), limit)


def test_ids_continue_past_the_highest_one_already_spent():
    """Derived from the ids present, not from row count -- a gap must not recycle."""
    assert ext.next_index([]) == 1
    assert ext.next_index([{"id": "s001"}, {"id": "s300"}]) == 301
    assert ext.next_index([{"id": "s001"}, {"id": "s300"}, {"id": "bad"}]) == 301


def test_numbering_is_contiguous_and_zero_padded():
    rows = ext.number([{"dvids_id": "news:1"}, {"dvids_id": "news:2"}], 301)
    assert [row["id"] for row in rows] == ["s301", "s302"]
    assert rows[0]["dvids_id"] == "news:1"


def test_the_frozen_sets_dvids_ids_are_excluded():
    """Re-collecting an existing snippet would pair it against two key rows."""
    kept = _select([_result("news:1"), _result("news:2")], exclude={"news:1"})
    assert [row["dvids_id"] for row in kept] == ["news:2"]


def test_duplicate_text_is_dropped_before_anything_is_graded():
    """The ADR-023 lesson, applied at collection time instead of at pairing time."""
    duplicate = _result("news:2")
    duplicate["short_description"] = _result("news:1")["short_description"]
    kept = _select([_result("news:1"), duplicate])
    assert [row["dvids_id"] for row in kept] == ["news:1"]


def test_duplicate_text_is_dropped_against_the_frozen_set_too():
    """Not just within the new batch: the combined set is what gets paired."""
    already = ext.normalize(_result("news:9")["short_description"])
    assert _select([_result("news:9")], texts={already}) == []


def test_de_duplication_holds_across_queries():
    """`seen_texts` and `seen_ids` are threaded through, so query 2 sees query 1."""
    texts, ids = set(), set()
    first = ext.select([_result("news:1")], set(), texts, ids, limit=10)
    second = ext.select([_result("news:1")], set(), texts, ids, limit=10)
    assert len(first) == 1
    assert second == []


def test_whitespace_only_differences_still_count_as_duplicates():
    """Normalization matches region_clause_ab's, so nothing survives to be dropped later."""
    spaced = _result("news:2")
    spaced["short_description"] = "  " + _result("news:1")["short_description"].replace(
        " ", "  "
    )
    kept = _select([_result("news:1"), spaced])
    assert len(kept) == 1


def test_the_inherited_filters_still_apply():
    """Same title deny-list and same 200-character minimum as build_scale_set."""
    short = _result("news:1")
    short["short_description"] = "too short"
    ceremony = _result("news:2", title="Change of command ceremony held at the base")
    untitled = _result("news:3", title="")
    assert _select([short, ceremony, untitled]) == []


def test_the_per_query_limit_is_respected():
    """The one documented deviation is a bigger limit, not an unbounded one."""
    kept = _select([_result(f"news:{i}") for i in range(10)], limit=3)
    assert len(kept) == 3


def test_snippet_text_is_stored_whitespace_normalized():
    """What is collected is what will be hashed for duplicates and sent to the model."""
    messy = _result("news:1")
    messy["short_description"] = "a  b\n c " + "x" * ext.MIN_SNIPPET
    kept = _select([messy])
    assert kept[0]["text"].startswith("a b c x")


def test_main_refuses_to_overwrite_an_existing_extension(tmp_path, monkeypatch, capsys):
    """Same rule build_scale_set applies: a collected set is not silently rebuilt."""
    existing = tmp_path / "scale_set_ext.csv"
    existing.write_text("id,dvids_id,source_url,text\n", encoding="utf-8")
    monkeypatch.setattr(ext, "EXT_CSV", existing)
    monkeypatch.setenv("DVIDS_API_KEY", "public-key")
    assert ext.main([]) == 0
    assert "refusing to overwrite" in capsys.readouterr().out


def test_main_says_what_is_missing_when_the_key_is_not_set(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(ext, "EXT_CSV", tmp_path / "absent.csv")
    monkeypatch.delenv("DVIDS_API_KEY", raising=False)
    assert ext.main([]) == 1
    assert "DVIDS_API_KEY is not set" in capsys.readouterr().out


def test_main_writes_numbered_rows_and_names_the_ceiling_when_it_falls_short(
    tmp_path, monkeypatch, capsys
):
    """The 'state the ceiling' requirement, and its warning against quietly widening.

    Drives ``main`` end to end with the network stubbed: one usable result per query,
    against a target it cannot reach.
    """
    frozen = tmp_path / "scale_set.csv"
    with frozen.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ext.FIELDNAMES)
        writer.writeheader()
        writer.writerow(
            {
                "id": "s300",
                "dvids_id": "news:frozen",
                "source_url": "u",
                "text": "frozen text",
            }
        )
    out = tmp_path / "ext.csv"
    monkeypatch.setattr(ext, "SCALE_CSV", frozen)
    monkeypatch.setattr(ext, "EXT_CSV", out)
    monkeypatch.setattr(ext, "excluded_dvids_ids", lambda: {"news:corpus"})
    monkeypatch.setattr(ext, "QUERIES", ["query one", "query two"])
    monkeypatch.setenv("DVIDS_API_KEY", "public-key")

    served = {"query one": [_result("news:1")], "query two": [_result("news:2")]}
    monkeypatch.setattr(ext, "search_news", lambda _key, query: served[query])

    assert ext.main(["--target", "50"]) == 0
    with out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["id"] for row in rows] == ["s301", "s302"]
    assert "CEILING REACHED" in capsys.readouterr().out


def test_main_stops_at_the_target_without_walking_every_query(
    tmp_path, monkeypatch, capsys
):
    """A target that IS reachable must not over-collect."""
    monkeypatch.setattr(ext, "SCALE_CSV", tmp_path / "absent.csv")
    monkeypatch.setattr(ext, "EXT_CSV", tmp_path / "ext.csv")
    monkeypatch.setattr(ext, "excluded_dvids_ids", set)
    monkeypatch.setattr(ext, "QUERIES", ["a", "b"])
    monkeypatch.setenv("DVIDS_API_KEY", "public-key")
    monkeypatch.setattr(
        ext,
        "search_news",
        lambda _key, _query: [_result(f"news:{_query}{i}") for i in range(5)],
    )

    assert ext.main(["--target", "3"]) == 0
    with ext.EXT_CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert "CEILING REACHED" not in capsys.readouterr().out
