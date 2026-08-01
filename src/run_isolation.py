"""Scratch-state isolation for eval runs: write via a temp file, clean up in finally.

The pattern is lifted from the pi agent harness
(https://github.com/earendil-works/pi, ``packages/evals/src/pi-harness.ts``),
which gives every eval run a fresh ``mkdtemp`` workspace, tears it down in a
``finally``, and -- the part that is easy to skip -- **never swallows the
cleanup failure**: if the run failed *and* cleanup failed, both are raised
together as an ``AggregateError`` rather than one hiding the other. The Python
equivalent is ``ExceptionGroup`` (3.11+, which this project already requires).

**What does not port, and why.** pi relocates the whole run into a temp
directory because its agent sessions are disposable. This repo's eval runs
deliberately write into ``evals/`` as they go: ``eval.py``, ``gold_eval.py``,
and ``scale_eval.py`` append each prediction the moment it lands so a crash
costs at most one API call, and the next run resumes from what is on disk.
Moving those under ``mkdtemp`` would delete resume and change a published
metric's generation path. So the discipline is applied where it actually buys
something -- the *whole-file* writes, where a crash or a full disk mid-write
leaves a truncated report behind and there is no resume to recover it.

``atomic_write_text`` is that: content goes to a temp file **in the destination
directory** (same filesystem, so the final ``os.replace`` is atomic), and the
temp file is removed in a ``finally`` whether or not the write succeeded. A
reader therefore only ever sees the old file or the complete new one, never a
half-written one.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: str | os.PathLike[str], text: str) -> None:
    """Write ``text`` to ``path`` atomically, cleaning up the temp file in finally.

    The write lands in a temp file beside the destination and is then moved
    into place with ``os.replace``, which is atomic on POSIX and on Windows.
    If the write fails, the destination is left exactly as it was.

    Both failures are surfaced when both happen: a write error plus a failure
    to remove the temp file is raised as an ``ExceptionGroup`` carrying both,
    so a leaked scratch file can never mask the error that caused it (pi's
    ``AggregateError`` rule).

    Args:
        path: Destination file. Its parent directory must already exist.
        text: Full file content, written as UTF-8.

    Raises:
        ExceptionGroup: If the write failed *and* removing the temp file also
            failed. The write error is the first member.
        OSError: If only the write failed, or only the cleanup failed.
    """
    destination = Path(path)
    handle, temp_path = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    write_error: BaseException | None = None
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, destination)
    except BaseException as exc:
        # Captured, never swallowed: re-raised below, possibly grouped with a
        # cleanup failure so neither error can hide the other.
        write_error = exc
    finally:
        # os.replace consumed the temp file on the success path; on any failure
        # path it may still exist and must not be left behind.
        cleanup_error: BaseException | None = None
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            cleanup_error = exc

        if write_error is not None and cleanup_error is not None:
            # BaseExceptionGroup, not ExceptionGroup: it accepts BaseException
            # members and still constructs a plain ExceptionGroup when (as here,
            # in practice) both members are ordinary Exceptions.
            raise BaseExceptionGroup(
                "atomic write failed and its temp file could not be removed",
                [write_error, cleanup_error],
            ) from None
        if write_error is not None:
            raise write_error
        if cleanup_error is not None:
            raise cleanup_error
