"""Range-based for-loop reserve — the detector reach fix.

The reserve detectors only saw counted `for(i=0;i<n;i++)` loops; real code uses range-based
`for (x : container)` constantly (a `CXX_FOR_RANGE_STMT`, which the detectors didn't even
collect). The bound is `container.size()`. Sound: reserve is only a capacity hint, so any
bound is behavior-preserving; the gate verifies it's actually faster.
"""
from pathlib import Path

from verto.adapters.language.cpp.regex_detect import (detect_all_growth,
                                                      detect_all_string_growth)
from verto.engine.api import Engine
from verto.engine.config import Config

EX = Path(__file__).resolve().parent.parent / "examples"


def _cfg():
    c = Config()
    c.model = "rules"
    return c


def test_detects_range_for_vector():
    src = (EX / "range_reserve.cpp").read_text()
    assert [(s.func, s.var, s.bound) for s in detect_all_growth(src)] == \
        [("map_doubled", "out", "in.size()")]


def test_detects_range_for_string():
    src = ("#include <string>\n#include <vector>\n"
           "std::string f(const std::vector<char>& cs){ std::string o;"
           " for(char c: cs) o += c; return o; }")
    assert [(s.var, s.bound) for s in detect_all_string_growth(src)] == [("o", "cs.size()")]


def test_already_reserved_range_for_skipped():
    src = ("#include <vector>\nstd::vector<int> f(const std::vector<int>& in){"
           " std::vector<int> o; o.reserve(in.size()); for(int x: in) o.push_back(x); return o; }")
    assert detect_all_growth(src) == []


def test_call_range_gets_no_bound():
    """A call/subscript range → no bound (would double-evaluate a side-effecting expr)."""
    src = ("#include <vector>\nstd::vector<int> f(){ std::vector<int> o;"
           " for(int x: make()) o.push_back(x); return o; }")
    assert all(s.bound is None for s in detect_all_growth(src))


def test_accepts_end_to_end():
    vs = Engine(_cfg()).optimize(str(EX / "range_reserve.cpp"), apply=False)
    acc = [v for v in vs if v.accepted]
    assert acc and acc[-1].candidate.transform.name == "reserve_before_pushback"
    assert acc[-1].correctness.rung >= 3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
