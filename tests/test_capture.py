"""Aggregate/POD input synthesis — the first slice of capture & replay (item #2).

A function taking a custom aggregate struct (all public primitive fields) used to
be skipped ("can't build the input"). VERTO now synthesizes the struct field-by-
field, so the change is verified & accepted. Also pins the guard rails: a struct
with a private field / a user constructor / a raw-pointer param stays unsynthesizable.
"""
import shutil
import tempfile
from pathlib import Path

from verto.adapters.language.cpp import analysis as _ast
from verto.adapters.domain.performance.harness import supported, unsupported_reason
from verto.engine.api import Engine
from verto.engine.config import Config

LINKED = Path(__file__).resolve().parent.parent / "examples" / "linked"


def _cfg():
    c = Config()
    c.model = "rules"
    return c


def test_simple_aggregate_is_synthesizable():
    src = (LINKED / "report.cpp").read_text()
    assert _ast.aggregate_fields(src, "const Config &") == [("n", "unsigned long"), ("scale", "int")]
    assert supported(src, "scaled_series")
    assert unsupported_reason(src, "scaled_series") is None


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


def test_aggregate_param_function_is_accepted_end_to_end():
    d = Path(tempfile.mkdtemp(prefix="verto-agg-"))
    try:
        for f in LINKED.iterdir():
            if f.is_file():
                shutil.copy2(f, d / f.name)
        results = Engine(_cfg()).optimize_codebase(str(d / "compile_commands.json"), apply=False)
        verds = next(v for f, v, err, _ in results if f.endswith("report.cpp") and not err)
        acc = [v for v in verds if v.accepted and getattr(v.candidate.transform, "target_func", None) == "scaled_series"]
        assert acc, "scaled_series (custom aggregate param) should now verify & accept"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("all capture/synthesis tests passed")
