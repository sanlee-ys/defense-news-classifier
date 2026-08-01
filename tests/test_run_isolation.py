"""Atomic report writes: no partial files, no leaked temp files, no swallowed errors."""

import os

import pytest

from run_isolation import atomic_write_text


def _scratch_files(directory):
    return [p.name for p in directory.iterdir() if p.name.startswith(".")]


def test_writes_the_content(tmp_path):
    target = tmp_path / "report.txt"
    atomic_write_text(target, "hello\nworld\n")
    assert target.read_text(encoding="utf-8") == "hello\nworld\n"


def test_overwrites_an_existing_file(tmp_path):
    target = tmp_path / "report.txt"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_leaves_no_temp_file_behind(tmp_path):
    atomic_write_text(tmp_path / "report.txt", "content")
    assert _scratch_files(tmp_path) == []


def test_failed_write_leaves_the_destination_untouched(tmp_path, monkeypatch):
    target = tmp_path / "report.txt"
    target.write_text("original", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_write_text(target, "replacement")

    # The old file survived intact, and the scratch file was cleaned up.
    assert target.read_text(encoding="utf-8") == "original"
    assert _scratch_files(tmp_path) == []


def test_write_and_cleanup_failures_are_both_surfaced(tmp_path, monkeypatch):
    """A leaked temp file must never hide the error that caused it."""
    target = tmp_path / "report.txt"

    def bad_replace(*_args, **_kwargs):
        raise OSError("disk full")

    def bad_unlink(*_args, **_kwargs):
        raise OSError("file is locked")

    monkeypatch.setattr(os, "replace", bad_replace)
    monkeypatch.setattr(os, "unlink", bad_unlink)

    with pytest.raises(ExceptionGroup) as info:
        atomic_write_text(target, "content")

    messages = [str(exc) for exc in info.value.exceptions]
    assert "disk full" in messages[0]
    assert "file is locked" in messages[1]
