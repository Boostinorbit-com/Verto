"""Transactional, safe application of verified changes (Phase-1 item #9).

Verifying a change proves it's correct; *writing* it across a codebase is a
separate risk — a crash, a failed later verification, or a file that drifted since
it was verified can leave the tree half-edited or mis-edited. This makes apply
trustworthy:

  * atomic       — write a temp file then os.replace(); a reader never sees a
                   half-written source, and an interrupted write leaves the
                   original intact.
  * transactional— every write is snapshotted; one transaction wraps a whole
                   codebase --apply, so rollback() restores ALL of them (all-or-
                   nothing) and commit() keeps them.
  * anchored     — refuse to write if the file on disk no longer matches the exact
                   source that was verified (a correct patch applied to changed
                   text is still a bug).
  * thread-safe  — codebase apply can run in parallel (item #8).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from ..runtime.fs import unique_tmp


class ApplyError(Exception):
    """A write could not be completed safely (stale file / IO) — triggers rollback."""


class ApplyTransaction:
    def __init__(self, *, backup: bool = False) -> None:
        self._orig: dict[str, bytes] = {}          # path -> original bytes (for rollback)
        self._backup = backup
        self._lock = threading.Lock()

    def write(self, path: str, new_text: str, *, expected_before: str | None = None) -> None:
        p = Path(path)
        try:
            cur = p.read_bytes()
        except OSError as e:
            raise ApplyError(f"cannot read {path}: {e}") from e
        # anchored: the file must still be exactly what the gate verified.
        if expected_before is not None and cur != expected_before.encode("utf-8"):
            raise ApplyError(f"{path} changed since it was verified — "
                             "refusing to apply a stale patch")
        with self._lock:
            first = str(p) not in self._orig
            if first:
                self._orig[str(p)] = cur           # snapshot before the first write
        if first and self._backup:
            try:
                p.with_suffix(p.suffix + ".bak").write_bytes(cur)
            except OSError:
                pass
        tmp = unique_tmp(p, "boostopt-tmp")
        try:
            Path(tmp).write_text(new_text, encoding="utf-8")
            os.replace(tmp, p)                     # atomic
        except OSError as e:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise ApplyError(f"cannot write {path}: {e}") from e

    def rollback(self) -> list[str]:
        """Restore every file this transaction wrote to its pre-transaction bytes."""
        with self._lock:
            restored = []
            for path, data in self._orig.items():
                try:
                    Path(path).write_bytes(data)
                    restored.append(path)
                except OSError:
                    pass
            self._orig.clear()
            return restored

    def commit(self) -> None:
        with self._lock:
            self._orig.clear()
