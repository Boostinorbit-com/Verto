"""Test-reuse correctness oracle (Phase-1 item #3).

The project's OWN tests re-confirm an accepted change. Pins the three outcomes:
  * a safe change (reserve) → project tests still pass → confirmed
  * a behavior-changing variant → project tests fail → rejected
  * project tests fail on the ORIGINAL → oracle unavailable (won't blame the change)
and the end-to-end path (a real optimize run annotates `tests_confirmed`). Uses
real compilation, a few seconds.
"""
import shutil
import tempfile
from pathlib import Path

from boostopt.adapters.domain.performance import reuse as reuse_mod
from boostopt.adapters.domain.performance.reuse import TestReuseOracle
from boostopt.engine.api import Engine
from boostopt.engine.config import Config
from boostopt.engine.models import Target, Variant

SERIES = ("#include <vector>\n#include <cstddef>\n"
          "std::vector<int> series(std::size_t n){ std::vector<int> out;"
          " for(std::size_t i=0;i<n;++i) out.push_back((int)(i*3+1)); return out; }\n")
SERIES_RESERVE = SERIES.replace("std::vector<int> out;", "std::vector<int> out; out.reserve(n);")
SERIES_WRONG = SERIES.replace("i*3+1", "i*3+2")            # changes output → tests must fail
TEST_MAIN = ("#include <vector>\n#include <cstddef>\n"
             "std::vector<int> series(std::size_t n);\n"
             "int main(){ auto v=series(100); if(v.size()!=100) return 1;"
             " long s=0; for(int x:v) s+=x; return s==14950?0:1; }\n")
CMD = "clang++ -std=c++20 series.cpp series_test.cpp -o _t && ./_t"


def _project(series=SERIES):
    d = Path(tempfile.mkdtemp(prefix="boostopt-reuse-"))
    (d / "series.cpp").write_text(series)
    (d / "series_test.cpp").write_text(TEST_MAIN)
    return d


def _oracle(d):
    reuse_mod._BASELINE.clear()                            # fresh baseline per test
    c = Config()
    c.test_command = CMD
    c.test_dir = str(d)
    return TestReuseOracle(c)


def _target(d):
    return Target(file=str(d / "series.cpp"), symbol="series", line=0, language="cpp")


def test_confirms_safe_change():
    d = _project()
    try:
        orig = _target(d)
        rv = _oracle(d).confirm(orig, Variant(orig, "", SERIES_RESERVE))
        assert rv.available and rv.passed, rv.detail
        assert (d / "series.cpp").read_text() == SERIES, "original must be restored"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_rejects_behavior_change():
    d = _project()
    try:
        orig = _target(d)
        rv = _oracle(d).confirm(orig, Variant(orig, "", SERIES_WRONG))
        assert rv.available and not rv.passed, "a change the project's tests reject must fail the oracle"
        assert (d / "series.cpp").read_text() == SERIES, "original must be restored even on failure"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_unavailable_when_baseline_fails():
    d = _project(series=SERIES_WRONG)                      # ORIGINAL already fails its own test
    try:
        orig = _target(d)
        rv = _oracle(d).confirm(orig, Variant(orig, "", SERIES_WRONG.replace(
            "std::vector<int> out;", "std::vector<int> out; out.reserve(n);")))
        assert not rv.available, "can't use tests as an oracle if the original already fails them"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_end_to_end_annotates_tests_confirmed():
    d = _project()
    try:
        c = Config()
        c.model = "rules"
        c.test_command = CMD                              # cwd defaults to the file's dir
        reuse_mod._BASELINE.clear()
        vs = Engine(c).optimize(str(d / "series.cpp"), apply=False)
        acc = [v for v in vs if v.accepted]
        assert acc, "reserve should be accepted"
        assert acc[-1].tests_confirmed, "accepted change should be re-confirmed by the project's tests"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("all test-reuse tests passed")
