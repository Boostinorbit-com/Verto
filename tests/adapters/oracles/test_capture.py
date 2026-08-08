"""Aggregate/POD input synthesis — the first slice of capture & replay (item #2).

A function taking a custom aggregate struct (all public primitive fields) used to
be skipped ("can't build the input"). BOOSTOPT now synthesizes the struct field-by-
field, so the change is verified & accepted. Also pins the guard rails: a struct
with a private field / a user constructor / a raw-pointer param stays unsynthesizable.
"""
import pytest

import shutil
import tempfile
from pathlib import Path

from boostopt.adapters.language.cpp import analysis as _ast
from boostopt.adapters.domain.performance.harness import supported, unsupported_reason
from boostopt.engine.api import Engine
from boostopt.engine.config import Config

from tests import LINKED


def _cfg():
    c = Config()
    c.model = "rules"
    return c


def test_simple_aggregate_is_synthesizable():
    src = (LINKED / "report.cpp").read_text()
    assert _ast.aggregate_fields(src, "const Config &") == [("n", "unsigned long"), ("scale", "int")]
    assert supported(src, "scaled_series")
    assert unsupported_reason(src, "scaled_series") is None


def test_bool_return_is_checksummable():
    """Measure-first (2026-07-28 census): a bool-returning candidate used to be an honest
    skip ('return type bool can't be checksummed') — the single biggest cheap win. bool now
    classifies as an integer (serialized 0/1), so it's harnessable. Also covers a bool PARAM."""
    src = ("#include <vector>\n#include <cstddef>\n"
           "bool has_dup(std::size_t n){ std::vector<int> o; for(std::size_t i=0;i<n;++i) o.push_back((int)i); "
           "return o.size() > 1; }")
    assert supported(src, "has_dup"), "bool return must now be harnessable"
    assert unsupported_reason(src, "has_dup") is None
    param = ("#include <vector>\n#include <cstddef>\n"
             "std::vector<int> pick(bool flag, std::size_t n){ std::vector<int> o; "
             "for(std::size_t i=0;i<n;++i) o.push_back(flag?(int)i:0); return o; }")
    assert supported(param, "pick"), "bool parameter must synthesize"


def test_nested_vector_is_synthesizable():
    """Measure-first Pile-A (2026-07-28 census): `vector<vector<primitive>>` (2D grids/
    matrices — the top soundly-closeable skip type after bool) now synthesizes as a DIMxDIM
    matrix. Sound: the same matrix feeds orig + variant; ASan backstops a dimension the
    callee assumes differently. Covers both a nested-vector PARAM and RETURN."""
    from boostopt.adapters.domain.performance.harness.synth import _classify
    assert _classify("std::vector<std::vector<int, std::allocator<int>>>") == ("vector2d", "int")
    param = ("#include <vector>\n"
             "std::vector<int> flatten(const std::vector<std::vector<int>>& m){\n"
             "  std::vector<int> o; for(const auto& row:m) for(int x:row) o.push_back(x); return o; }\n")
    assert supported(param, "flatten") and unsupported_reason(param, "flatten") is None
    ret = ("#include <vector>\n#include <cstddef>\n"
           "std::vector<std::vector<int>> rows(std::size_t n){ std::vector<std::vector<int>> o; "
           "for(std::size_t i=0;i<n;++i) o.push_back({(int)i}); return o; }\n")
    assert supported(ret, "rows"), "nested-vector RETURN must be checksummable"


def test_return_serializers_aggregate_and_map():
    """Measure-first Pile-A return serializers: an aggregate/struct return (print each public
    primitive field — symmetric to B1 param synthesis) and an (unordered_)map return (a
    COMMUTATIVE checksum so unspecified iteration order can't cause a false reject) are now
    checksummable instead of skipped."""
    agg = ("#include <cstddef>\nstruct Pt { int x; long y; };\n"
           "Pt make(std::size_t n){ Pt p{(int)n,(long)n}; return p; }\n")
    assert supported(agg, "make") and unsupported_reason(agg, "make") is None
    mp = ("#include <unordered_map>\n#include <cstddef>\n"
          "std::unordered_map<int,int> h(std::size_t n){ std::unordered_map<int,int> m; "
          "for(std::size_t i=0;i<n;++i) m[(int)i]++; return m; }\n")
    assert supported(mp, "h"), "unordered_map return must be checksummable (commutative)"
    # classifier guard: primitive-keyed/valued map serializes; a non-primitive value does not
    from boostopt.adapters.domain.performance.harness.synth import _classify_ret
    assert _classify_ret("std::unordered_map<char, int>", "")[0] == "map"
    assert _classify_ret("std::map<int, std::string>", "") is None


def test_non_aggregate_is_rejected():
    # private data member → not a brace-initable aggregate
    priv = ("struct Box { public: int w; private: int secret; };\n"
            "#include <vector>\n#include <cstddef>\n"
            "std::vector<int> f(const Box& b){ std::vector<int> o; for(int i=0;i<b.w;++i) o.push_back(i); return o; }")
    assert _ast.aggregate_fields(priv, "Box") is None
    assert not supported(priv, "f")
    # user-declared constructor → also rejected
    ctor = ("struct P { int x; P(int v):x(v){} };\n"
            "#include <vector>\n"
            "std::vector<int> g(const P& p){ std::vector<int> o; for(int i=0;i<p.x;++i) o.push_back(i); return o; }")
    assert _ast.aggregate_fields(ctor, "P") is None


@pytest.mark.toolchain
def test_aggregate_param_function_is_accepted_end_to_end():
    d = Path(tempfile.mkdtemp(prefix="boostopt-agg-"))
    try:
        for f in LINKED.iterdir():
            if f.is_file():
                shutil.copy2(f, d / f.name)
        results = Engine(_cfg()).optimize_codebase(str(d / "compile_commands.json"), apply=False)
        verds = next(v for f, v, err, _ in results if f.endswith("report.cpp") and not err)
        # report.cpp now has TWO synthesis-param functions — scaled_series (aggregate,
        # this slice) and gather (const-ptr+length, B2-a). The sensor optimizes whichever
        # is the hotspot, so accept either as proof that synthesized-input capture works.
        acc = [v for v in verds if v.accepted
               and getattr(v.candidate.transform, "target_func", None) in ("scaled_series", "gather")]
        assert acc, "a synthesis-param function (aggregate scaled_series / pointer gather) should verify & accept"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("all capture/synthesis tests passed")
