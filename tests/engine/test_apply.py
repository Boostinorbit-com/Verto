"""--apply writes VERIFIED changes; the soundness guard refuses unsound writes.

Pins the write behavior (BOOSTOPT_Surfaces §CLI). Uses real compilation, so it's a
few seconds — run with `python -m tests.test_apply` or pytest.
"""
import pytest

import shutil
import tempfile
from pathlib import Path

from boostopt.engine.api import Engine
from boostopt.engine.config import Config

from tests import EXAMPLES
SRC = EXAMPLES / "packet_stats.cpp"


def _cfg(**kw):
    c = Config()
    c.model = "rules"
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _tmp_copy():
    d = tempfile.mkdtemp(prefix="boostopt-apply-test-")
    f = Path(d) / "p.cpp"
    shutil.copy2(SRC, f)
    return d, f


@pytest.mark.toolchain
def test_apply_writes_verified_change():
    d, f = _tmp_copy()
    try:
        before = f.read_text()
        vs = Engine(_cfg()).optimize(str(f), apply=True)
        after = f.read_text()
        assert any(v.accepted and v.applied for v in vs), "expected an applied accept"
        assert after != before and "emplace_back" in after, "source was not rewritten"
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.toolchain
def test_no_apply_does_not_write():
    d, f = _tmp_copy()
    try:
        before = f.read_text()
        Engine(_cfg()).optimize(str(f), apply=False)
        assert f.read_text() == before, "analyze/dry-run must not touch source"
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.toolchain
def test_backup_created_on_apply():
    d, f = _tmp_copy()
    try:
        Engine(_cfg()).optimize(str(f), apply=True, backup=True)
        assert (Path(d) / "p.cpp.bak").exists(), "--backup must save a .bak"
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.toolchain
def test_fast_apply_refuses_unsound_without_force():
    d, f = _tmp_copy()
    try:
        before = f.read_text()
        cfg = _cfg(fast=True, min_rung=1, reps_min=3, reps=6)
        vs = Engine(cfg).optimize(str(f), apply=True)          # no force
        assert f.read_text() == before, "unsound (--fast) result must not be auto-written"
        assert any(v.accepted and not v.applied for v in vs), "expected accepted-but-not-applied"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("all apply tests passed")
