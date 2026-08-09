"""Scale: parallel processing + --changed git filter (Phase-1 item #8).

(a) --changed restricts a codebase run to the TUs git reports as modified.
(b) jobs > 1 processes TUs in parallel and MUST produce identical results to the
    sequential run (the thread-safety fixes: thread-local parse flags, thread-unique
    temp names, locked ledger).
"""
import pytest

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from boostopt.engine.api import Engine
from boostopt.engine.config import Config

from tests import LINKED


def _cfg():
    c = Config()
    c.model = "rules"
    c.use_cache = False        # determinism check: both runs must recompute, not reuse a cached best
    return c


_MEASURED = re.compile(r"\d+(?:\.\d+)?%")   # a PERCENTAGE only — `p99` must stay `p99`


def _reason(r: str | None) -> str:
    """The reason with MEASURED numbers masked out.

    What this test pins is that parallel and sequential reach the same VERDICTS. Reason strings
    embed live benchmark figures — the same rejection legitimately reads "p99 regressed 0.9%" in
    one run and "1.0%" in the other, because the two runs time the binary independently and the
    parallel one does so under four-way load. Comparing those digits asserts that two benchmarks
    agree to the decimal, which is not a property the engine has or should claim; it made this
    test fail roughly one CI run in three while the decisions matched perfectly."""
    return _MEASURED.sub("N", r or "")


def _summary(results):
    return {Path(f).name: (sorted((v.accepted, _reason(v.reason)) for v in vs), err, len(sk))
            for f, vs, err, sk in results}


@pytest.mark.toolchain
def test_parallel_matches_sequential():
    db = str(LINKED / "compile_commands.json")
    seq = _summary(Engine(_cfg()).optimize_codebase(db, apply=False, jobs=1))
    par = _summary(Engine(_cfg()).optimize_codebase(db, apply=False, jobs=4))
    assert seq == par, f"parallel must match sequential\n seq={seq}\n par={par}"
    assert any(a for verds, _err, _n in par.values() for a, _r in verds), \
        "sanity: the run should have accepted at least one change"


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


@pytest.mark.toolchain
def test_changed_filters_to_git_diff():
    d = Path(tempfile.mkdtemp(prefix="boostopt-scale-"))
    try:
        for f in LINKED.iterdir():
            if f.is_file():
                shutil.copy2(f, d / f.name)
        _git(d, "init", "-q")
        _git(d, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
        _git(d, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")

        # modify exactly one source file
        (d / "route.cpp").write_text((d / "route.cpp").read_text() + "\n// touched\n")

        results = Engine(_cfg()).optimize_codebase(
            str(d / "compile_commands.json"), apply=False, changed="")
        files = {Path(f).name for f, _, _, _ in results}
        assert files == {"route.cpp"}, f"--changed should scan only the modified TU; got {files}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("all scale tests passed")


@pytest.mark.toolchain
def test_on_done_fires_once_per_tu_in_order():
    """Live-progress hook: on_done fires once per TU, index 1..N, total constant — so codebase
    mode can report each file as it finishes instead of going silent."""
    db = str(LINKED / "compile_commands.json")
    calls = []
    Engine(_cfg()).optimize_codebase(
        db, apply=False, on_done=lambda i, total, f, *_: calls.append((i, total, f)))
    n = len(calls)
    assert n > 0
    assert [c[0] for c in calls] == list(range(1, n + 1))   # 1..N, in order
    assert all(c[1] == n for c in calls)                    # total consistent
