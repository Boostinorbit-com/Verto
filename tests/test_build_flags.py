"""Build like the real project (Phase-1 item #6).

The timed build must reuse the project's real codegen flags (-O/-march/…), not a
fixed -O2, so the measured speedup reflects the shipping build. Unit-tests the
flag extraction (the risky part) and checks a project that ships -O3 still
verifies end to end with those flags applied.
"""
import json
import shutil
import tempfile
from pathlib import Path

from verto.adapters.language.cpp import compile_db
from verto.engine.api import Engine
from verto.engine.config import Config

LINKED = Path(__file__).resolve().parent.parent / "examples" / "linked"


def _cfg():
    c = Config()
    c.model = "rules"
    return c


def test_extract_opt_flags_keeps_codegen_drops_plumbing():
    f = compile_db._extract_opt_flags
    assert f(["clang++", "-O3", "-march=skylake", "-Wall", "-g", "-c", "x.cpp", "-o", "x.o"]) \
        == ["-O3", "-march=skylake"]
    assert f(["clang++", "-Os", "-mavx2", "-flto", "-fsanitize=address", "-c", "x.cpp"]) \
        == ["-Os", "-mavx2"]                                  # LTO + sanitizer denied
    assert f(["clang++", "-O0", "-Og", "-fno-exceptions", "-c", "x.cpp"]) \
        == ["-fno-exceptions"]                               # debug -O levels dropped
    assert f(["g++", "-O2", "-MMD", "-MF", "x.d", "-pthread", "-c", "x.cpp"]) \
        == ["-O2", "-pthread"]                               # dep-gen dropped


def test_repeated_isystem_survive_dedup():
    """Regression: a real CMake command repeats `-isystem` many times. Emitting the
    flag name as its own token let dedup collapse all but the first, orphaning every
    path after it → real projects wouldn't parse. Joined form must keep every path."""
    toks = ["c++", "-isystem", "/qt/QtCore", "-isystem", "/qt/QtGui",
            "-isystem", "/qt/QtQml", "-Dcc", "-c", "x.cpp"]
    flags = compile_db._dedup(compile_db._extract_flags(toks, "/proj"))
    for p in ("/qt/QtCore", "/qt/QtGui", "/qt/QtQml"):
        assert f"-isystem{p}" in flags, f"lost include path {p}: {flags}"


def test_load_populates_opt_flags():
    d = Path(tempfile.mkdtemp(prefix="verto-optflag-"))
    try:
        (d / "a.cpp").write_text("int a(){return 0;}")
        (d / "compile_commands.json").write_text(json.dumps([
            {"directory": ".", "file": "a.cpp",
             "arguments": ["clang++", "-std=c++20", "-O3", "-march=native", "-c", "a.cpp"]}]))
        tus = compile_db.load(str(d / "compile_commands.json"))
        assert tus[0].opt_flags == ["-O3", "-march=native"]
        assert "-O3" not in tus[0].flags                     # kept out of the parse bucket
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_project_o3_still_verifies():
    """A project shipping -O3 must still verify+accept (flags applied, build intact)."""
    d = Path(tempfile.mkdtemp(prefix="verto-o3-"))
    try:
        for name in ("geo.h", "geo.cpp", "route.cpp"):
            shutil.copy2(LINKED / name, d / name)
        (d / "compile_commands.json").write_text(json.dumps([
            {"directory": ".", "file": "geo.cpp",
             "arguments": ["clang++", "-std=c++20", "-O3", "-march=native", "-I.", "-c", "geo.cpp"]},
            {"directory": ".", "file": "route.cpp",
             "arguments": ["clang++", "-std=c++20", "-O3", "-march=native", "-I.", "-c", "route.cpp"]}]))
        results = Engine(_cfg()).optimize_codebase(str(d / "compile_commands.json"), apply=False)
        route = next(v for f, v, err, _ in results if f.endswith("route.cpp") and not err)
        assert any(x.accepted for x in route), "route_costs should still verify under the project's -O3"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("all build-flag tests passed")
