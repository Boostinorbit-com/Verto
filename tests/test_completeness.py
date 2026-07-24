"""Correctness & coverage completeness (Phase-1 items #1a–#1d).

These close gaps in the "never changes behavior / never ships UB" guarantee:
  1c — refuse functions with un-modeled side effects (global writes / I/O),
       instead of falsely "verifying" them on stdout alone.
  1d — name optimizable function templates as skips (can't harness without a
       concrete instantiation).
"""
import pytest

from verto.adapters.language.cpp.regex_detect import (
    detect_side_effect_reason, detect_template_candidates)

CLEAN = ("#include <vector>\n#include <cstddef>\n"
         "std::vector<int> f(std::size_t n){ std::vector<int> o;"
         " for(std::size_t i=0;i<n;++i) o.push_back((int)i); return o; }")


def test_1c_refuses_global_write():
    src = ("#include <vector>\n#include <cstddef>\nlong g=0;\n"
           "std::vector<int> f(std::size_t n){ g++; std::vector<int> o;"
           " for(std::size_t i=0;i<n;++i) o.push_back((int)i); return o; }")
    r = detect_side_effect_reason(src, "f")
    assert r and "global" in r, r


def test_1c_refuses_io():
    src = ("#include <vector>\n#include <cstddef>\n#include <cstdio>\n"
           "std::vector<int> f(std::size_t n){ std::printf(\"x\"); std::vector<int> o;"
           " for(std::size_t i=0;i<n;++i) o.push_back((int)i); return o; }")
    r = detect_side_effect_reason(src, "f")
    assert r and "I/O" in r, r


def test_1c_allows_clean_and_local_static():
    assert detect_side_effect_reason(CLEAN, "f") is None
    # a function-LOCAL static is not a 1c side effect (it's the race/memory axis)
    ls = ("#include <vector>\n#include <cstddef>\n"
          "std::vector<int> f(std::size_t n){ static long c=0; c++; std::vector<int> o;"
          " for(std::size_t i=0;i<n;++i) o.push_back((int)i); return o; }")
    assert detect_side_effect_reason(ls, "f") is None


def test_1c_const_global_is_fine():
    src = ("#include <vector>\n#include <cstddef>\nconst int K=3;\n"
           "std::vector<int> f(std::size_t n){ std::vector<int> o;"
           " for(std::size_t i=0;i<n;++i) o.push_back((int)i*K); return o; }")
    assert detect_side_effect_reason(src, "f") is None       # const global = deterministic input


def test_1d_names_optimizable_templates():
    tmpl = ("#include <vector>\n#include <cstddef>\n"
            "template<class T> std::vector<T> mk(std::size_t n){ std::vector<T> o;"
            " for(std::size_t i=0;i<n;++i) o.push_back((T)i); return o; }")
    assert "mk" in detect_template_candidates(tmpl)
    assert detect_template_candidates(CLEAN) == []           # concrete fn is not a template


def test_1b_tolerant_compare():
    from verto.adapters.domain.performance.correctness import _outputs_match
    assert _outputs_match("1.0 2.0", "1.0 2.0", 0.0)              # exact, identical
    assert not _outputs_match("1.0", "1.0000001", 0.0)           # exact, differ
    assert _outputs_match("3 1.0 2.0 3.0", "3 1.0 2.0 3.0000001", 1e-5)   # within tol
    assert not _outputs_match("1.0", "1.001", 1e-9)              # outside tol
    assert not _outputs_match("1 2", "1 2 3", 1e-3)             # shape mismatch


def test_1b_enables_fp_vector():
    from verto.adapters.domain.performance.harness import supported, unsupported_reason
    fp = ("#include <vector>\n#include <cstddef>\n"
          "std::vector<double> f(std::size_t n){ std::vector<double> o;"
          " for(std::size_t i=0;i<n;++i) o.push_back((double)i*0.5); return o; }")
    assert supported(fp, "f") and unsupported_reason(fp, "f") is None


def test_1a_tsan_catches_race_when_available():
    """A shared-static data race is output-identical (Rung 1 passes) but must fail
    the TSan rung. Skips where this toolchain has no working ThreadSanitizer."""
    from verto.adapters.language.cpp.build import tsan_toolchain
    if tsan_toolchain() is None:
        pytest.skip("ThreadSanitizer not available on this toolchain")
    from verto.engine.config import Config
    from verto.engine.models import Target, Variant
    from verto.adapters.domain.performance.correctness import PerfCorrectnessOracle
    from verto.adapters.domain.performance.inputs import HeldOutInputs
    cfg = Config(); cfg.fuzz_inputs = 0
    orig = Target(file="examples/squares_of.cpp", symbol="squares_of", line=0, language="cpp")
    racy = ("#include <vector>\n#include <cstddef>\n"
            "std::vector<long> squares_of(const std::vector<int>& v){\n"
            "  static long hits = 0;\n"                          # shared mutable state → race
            "  std::vector<long> o; o.reserve(v.size());\n"
            "  for(int x: v){ hits += x; o.push_back((long)x*x); }\n"
            "  return o; }")
    res = PerfCorrectnessOracle(cfg).equivalent(orig, Variant(orig, "", racy), HeldOutInputs(cfg))
    assert res.rung < 3 and "tsan" in res.witness.sanitizer, res.witness.sanitizer


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
