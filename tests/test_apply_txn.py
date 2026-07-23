"""Safe apply: transactional / atomic / anchored writes (Phase-1 item #9)."""
import shutil
import tempfile
from pathlib import Path

import pytest

from verto.engine.apply_txn import ApplyError, ApplyTransaction


def _tmpfile(text="original\n"):
    d = Path(tempfile.mkdtemp(prefix="verto-txn-"))
    f = d / "f.txt"
    f.write_text(text)
    return d, f


def test_rollback_restores_all_writes():
    d = Path(tempfile.mkdtemp(prefix="verto-txn-"))
    try:
        a, b = d / "a.txt", d / "b.txt"
        a.write_text("A0"); b.write_text("B0")
        t = ApplyTransaction()
        t.write(str(a), "A1")
        t.write(str(b), "B1")
        assert a.read_text() == "A1" and b.read_text() == "B1"     # written in place
        t.rollback()
        assert a.read_text() == "A0" and b.read_text() == "B0"     # all-or-nothing revert
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_commit_keeps_writes():
    d, f = _tmpfile("v0")
    try:
        t = ApplyTransaction()
        t.write(str(f), "v1")
        t.commit()
        t.rollback()                                               # no-op after commit
        assert f.read_text() == "v1"
    finally:
        shutil.rmtree(d.parent if d.name == "f.txt" else d, ignore_errors=True)


def test_stale_file_is_refused():
    d, f = _tmpfile("verified-source")
    try:
        t = ApplyTransaction()
        with pytest.raises(ApplyError):
            t.write(str(f), "new", expected_before="something-else")  # drifted
        assert f.read_text() == "verified-source", "must not write when the file drifted"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_backup_written_once_of_original():
    d, f = _tmpfile("orig")
    try:
        t = ApplyTransaction(backup=True)
        t.write(str(f), "one")
        t.write(str(f), "two")                                     # second write, same file
        assert (d / "f.txt.bak").read_text() == "orig", ".bak is the ORIGINAL, written once"
        assert f.read_text() == "two"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_atomic_no_tmp_left_behind():
    d, f = _tmpfile()
    try:
        ApplyTransaction().write(str(f), "x")
        leftovers = [p.name for p in d.iterdir() if "verto-tmp" in p.name]
        assert not leftovers, f"temp files must be renamed away, found {leftovers}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_codebase_apply_is_all_or_nothing(monkeypatch):
    """A write failure part-way through a codebase --apply must roll back EVERY
    file already written — never leave a half-edited tree."""
    from verto.engine import apply_txn
    from verto.engine.api import Engine
    from verto.engine.config import Config
    from verto.engine.ledger import JsonlLedger

    linked = Path(__file__).resolve().parent.parent / "examples" / "linked"
    d = Path(tempfile.mkdtemp(prefix="verto-txn-cb-"))
    try:
        for f in linked.iterdir():
            if f.is_file():
                shutil.copy2(f, d / f.name)
        before = {name: (d / name).read_text() for name in ("route.cpp", "report.cpp")}

        real_write = apply_txn.ApplyTransaction.write
        calls = {"n": 0}

        def flaky(self, path, new_text, *, expected_before=None):
            calls["n"] += 1
            if calls["n"] == 2:                       # fail on the second applied file
                raise apply_txn.ApplyError("injected write failure")
            return real_write(self, path, new_text, expected_before=expected_before)

        monkeypatch.setattr(apply_txn.ApplyTransaction, "write", flaky)

        cfg = Config(); cfg.model = "rules"
        eng = Engine(cfg); eng.ledger = JsonlLedger(str(d / "ledger.jsonl"))
        with pytest.raises(apply_txn.ApplyError):
            eng.optimize_codebase(str(d / "compile_commands.json"), apply=True)

        after = {name: (d / name).read_text() for name in ("route.cpp", "report.cpp")}
        assert calls["n"] >= 2, "test needs at least two applied writes to be meaningful"
        assert after == before, "a mid-batch failure must roll back all applied files"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as e:
                print(f"  FAIL {name}: {e}")
    print("done")
