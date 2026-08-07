"""Range-based for-loop reserve — the detector reach fix.

The reserve detectors only saw counted `for(i=0;i<n;i++)` loops; real code uses range-based
`for (x : container)` constantly (a `CXX_FOR_RANGE_STMT`, which the detectors didn't even
collect). The bound is `container.size()`. Sound: reserve is only a capacity hint, so any
bound is behavior-preserving; the gate verifies it's actually faster.
"""
from pathlib import Path

from boostopt.adapters.language.cpp.regex_detect import (detect_all_growth,
                                                      detect_all_string_growth)
from boostopt.engine.api import Engine
from boostopt.engine.config import Config

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


def test_braced_initlist_pushback_not_emplaced():
    """Robustness: the reserve transform rewrites push_back → emplace_back, but a braced-init-list
    arg — `push_back({a, b})` — must stay push_back, because `emplace_back({...})` is INVALID C++
    (a braced-init-list can't be perfect-forwarded). Previously this emitted uncompilable code
    (a build_failed → spurious REJECT of a real reserve opportunity)."""
    from boostopt.adapters.language.cpp.transforms import ALL
    from boostopt.adapters.language.cpp.mutator import CppMutator
    from boostopt.engine.models import Target
    import tempfile, os
    src = ("#include <vector>\n#include <cstddef>\n"
           "std::vector<std::vector<int>> f(std::size_t n){ std::vector<std::vector<int>> m;\n"
           "  for(std::size_t i=0;i<n;++i) m.push_back({(int)i, (int)(i*2)});\n"
           "  return m; }\n")
    d = tempfile.mkdtemp(); fp = os.path.join(d, "f.cpp"); open(fp, "w").write(src)
    t = next(x for x in ALL if x.name == "reserve_before_pushback").bind("f")
    assert t.matches(src)
    after = CppMutator(Config()).apply(Target(file=fp, symbol="f", line=0, language="cpp"), t).source_after
    assert "m.reserve(" in after                          # reserve still applied
    assert "emplace_back({" not in after                  # braced-init-list NOT emplaced (invalid)
    assert "push_back({" in after                          # left as push_back
