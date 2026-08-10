"""pass-by-value → const& transform (transform-coverage).

A heavy parameter passed by value is copied every call; `const&` removes the copy.
Sound by gate: a read-only param → accept (real win); a mutated param → `const&`
won't compile → reject. Also demonstrates the generic-sensor payoff — the whole
transform is one file + one `ALL` entry; the sensor is untouched.
"""
import pytest

import shutil
import tempfile
from pathlib import Path

from boostopt.adapters.language.cpp.regex_detect import detect_byval_params
from boostopt.adapters.language.cpp.transforms.pass_by_const_ref import PassByConstRef
from boostopt.engine.api import Engine
from boostopt.engine.config import Config

from tests import EXAMPLES as EX


def _cfg():
    c = Config()
    c.model = "rules"
    return c


def test_detects_and_rewrites_byval():
    src = (EX / "byval_sum.cpp").read_text()
    sites = detect_byval_params(src)
    assert [s.func for s in sites] == ["sum_all"]
    assert sites[0].old_text == "std::vector<int> v"
    assert sites[0].new_text == "const std::vector<int>& v"
    t = PassByConstRef().bind("sum_all")
    assert t.matches(src)
    new, _patch = t.rewrite(src)
    assert "const std::vector<int>& v" in new


def test_skips_reference_and_pointer_and_primitive():
    # already a reference / pointer / primitive → no by-value-copy site
    src = ("#include <vector>\n#include <cstddef>\n"
           "long a(const std::vector<int>& v){ long s=0; for(int x:v) s+=x; return s; }\n"
           "long b(std::vector<int>* v){ return v->size(); }\n"
           "long c(std::size_t n){ return (long)n; }\n")
    assert detect_byval_params(src) == []


@pytest.mark.toolchain
def test_accepts_readonly_byval_end_to_end():
    vs = Engine(_cfg()).optimize(str(EX / "byval_sum.cpp"), apply=False)
    acc = [v for v in vs if v.accepted]
    assert acc and acc[-1].candidate.transform.name == "pass_by_const_ref"
    assert acc[-1].correctness.rung >= 3


@pytest.mark.toolchain
def test_rejects_mutated_byval_end_to_end():
    """A mutated by-value param: const& won't compile → the gate rejects it."""
    d = Path(tempfile.mkdtemp(prefix="boostopt-byval-"))
    try:
        f = d / "mut.cpp"
        f.write_text("#include <vector>\n#include <algorithm>\n#include <cstddef>\n"
                     "int median_of(std::vector<int> v){ std::sort(v.begin(), v.end());"
                     " return v.empty()?0:v[v.size()/2]; }\n")
        vs = Engine(_cfg()).optimize(str(f), apply=False)
        assert not any(v.accepted for v in vs), "mutated by-value param must not be accepted as const&"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
