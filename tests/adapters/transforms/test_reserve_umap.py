"""unordered_map reserve transform (transform-coverage).

A std::unordered_map grown in a loop with no reserve() rehashes ~log2(n)×;
`reserve(n)` removes them. Reuses `_ReserveBase`, so it's a tiny transform — the
detector + one subclass. Sensor untouched (generic-sensor payoff).
"""

import pytest

from boostopt.adapters.language.cpp.regex_detect import detect_all_umap_growth
from boostopt.adapters.language.cpp.transforms.reserve import ReserveUnorderedMap
from boostopt.engine.api import Engine
from boostopt.engine.config import Config

from tests import EXAMPLES as EX


def _cfg():
    c = Config()
    c.model = "rules"
    return c


def test_detects_umap_growth():
    src = (EX / "umap_build.cpp").read_text()
    sites = detect_all_umap_growth(src)
    assert [(s.func, s.var, s.bound) for s in sites] == [("build_index", "m", "n")]


def test_rewrite_inserts_reserve():
    src = (EX / "umap_build.cpp").read_text()
    t = ReserveUnorderedMap().bind("build_index")
    assert t.matches(src)
    new, _patch = t.rewrite(src)
    assert "m.reserve(n);" in new


def test_already_reserved_is_not_a_candidate():
    src = ("#include <unordered_map>\n#include <cstddef>\n"
           "long f(std::size_t n){ std::unordered_map<int,long> m; m.reserve(n);"
           " for(std::size_t i=0;i<n;++i) m[(int)i]=(long)i; long s=0; for(auto&k:m) s+=k.second; return s; }")
    assert detect_all_umap_growth(src) == []


@pytest.mark.toolchain
def test_accepts_end_to_end():
    vs = Engine(_cfg()).optimize(str(EX / "umap_build.cpp"), apply=False)
    acc = [v for v in vs if v.accepted]
    assert acc and acc[-1].candidate.transform.name == "reserve_unordered_map"
    assert acc[-1].correctness.rung >= 3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
