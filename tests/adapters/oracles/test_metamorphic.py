"""2D — metamorphic property rung (Rung 2, opt-in).

Permutation invariance: f(v) == f(shuffle(v)) for a vector<int>→int reduction. Sound —
only ever REJECTS a change that broke a property the original had; stands down when the
property doesn't apply. Requires a compiler (like the other build-backed tests).
"""
import shutil

import pytest

from boostopt.adapters.domain.performance.metamorphic import MetamorphicOracle
from boostopt.engine.api import Engine
from boostopt.engine.config import Config

pytestmark = pytest.mark.skipif(shutil.which("clang++") is None and shutil.which("g++") is None,
                                reason="needs a C++ compiler")

_SUM_VAL = "#include <vector>\nlong f(std::vector<int> v){ long s=0; for(int x:v) s+=x; return s; }"
_SUM_REF = "#include <vector>\nlong f(const std::vector<int>& v){ long s=0; for(int x:v) s+=x; return s; }"
_FIRST = "#include <vector>\nlong f(std::vector<int> v){ return v.empty()?0:v[0]; }"   # order-dependent
_SIZET = "#include <cstddef>\nlong f(std::size_t n){ return (long)n; }"                 # wrong signature


@pytest.mark.toolchain
def test_preserved_property_passes():
    v = MetamorphicOracle().check(_SUM_VAL, _SUM_REF, "f")
    assert v.applicable and v.passed and v.prop == "permutation-invariance"


@pytest.mark.toolchain
def test_broken_property_is_caught():
    """An invariant original + a variant that returns v[0] → property broken → caught."""
    v = MetamorphicOracle().check(_SUM_VAL, _FIRST, "f")
    assert v.applicable and not v.passed


def test_order_dependent_original_stands_down():
    v = MetamorphicOracle().check(_FIRST, _FIRST, "f")
    assert not v.applicable                         # original isn't invariant → property N/A


def test_wrong_signature_stands_down():
    v = MetamorphicOracle().check(_SIZET, _SIZET, "f")
    assert not v.applicable                         # not vector<int>→int → property N/A


@pytest.mark.toolchain
def test_end_to_end_annotates_verdict():
    """A real accepted change (pass-by-const-ref on a sum) carries the confirmed property."""
    c = Config(); c.model = "rules"; c.metamorphic = True
    vs = Engine(c).optimize("examples/byval_sum.cpp", apply=False)
    acc = [v for v in vs if v.accepted]
    assert acc and acc[-1].metamorphic == "permutation-invariance"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
