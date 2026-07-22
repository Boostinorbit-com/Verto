"""C++ build — compile a program via clang++ (with a sanitizer-toolchain fallback).

Mirrors VERTO_Architecture §16.3. Uses the flags from compile_commands.json when
present (real projects REQUIRE it). Correctness runs add -fsanitize; performance
runs use real -O and are NEVER sanitized (distorts timing). All builds run in the
sandbox.

Sanitizer runtimes are not always shipped with a given clang build, so Rung 3
auto-detects a toolchain whose -fsanitize actually links (clang++, else g++).
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ....runtime import sandbox

CXX = "clang++"
STD = "-std=c++20"


@lru_cache(maxsize=1)
def _ccache() -> list[str]:
    """Prefix compiler invocations with ccache when it's on PATH — transparent
    object-file caching. Huge win on repeat runs (the STL template instantiation
    of an unchanged original is served from cache). No-op if ccache is absent."""
    return ["ccache"] if shutil.which("ccache") else []


@dataclass
class Artifact:
    binary_path: str
    build_ok: bool
    stderr: str = ""


def compile_program(source_code: str, out_path: str, *, flags: list[str],
                    workdir: str, cxx: str = CXX) -> Artifact:
    cc = _ccache()
    if cc:
        # ccache only caches compile-to-object (-c), never a combined compile+link,
        # so split the two. The -c step (STL template instantiation + codegen — the
        # expensive part) is compiled from a CONTENT-ADDRESSED stable path so the
        # source's location doesn't leak into the preprocessed output and bust the
        # cache; identical source => same path => ccache hit on every repeat run.
        # The link step is cheap and left uncached.
        h = hashlib.sha1(source_code.encode("utf-8")).hexdigest()[:16]
        srcdir = Path(tempfile.gettempdir()) / "verto-ccsrc"
        srcdir.mkdir(exist_ok=True)
        src = srcdir / f"{h}.cpp"
        if not src.exists():
            src.write_text(source_code, encoding="utf-8")
        obj = f"{out_path}.o"
        r = sandbox.run([*cc, cxx, *flags, "-c", str(src), "-o", obj], timeout_sec=120)
        if r.ok:
            r = sandbox.run([cxx, *flags, obj, "-o", out_path], timeout_sec=120)
        return Artifact(binary_path=out_path, build_ok=r.ok, stderr=r.stderr)

    # no ccache: one compile+link step (splitting would only add overhead here)
    src = Path(workdir) / (Path(out_path).name + ".cpp")
    src.write_text(source_code, encoding="utf-8")
    res = sandbox.run([cxx, *flags, str(src), "-o", out_path], timeout_sec=120)
    return Artifact(binary_path=out_path, build_ok=res.ok, stderr=res.stderr)


def compile_pair(a: dict, b: dict) -> tuple[Artifact, Artifact]:
    """Compile two programs concurrently (each blocks on its own subprocess).
    Each dict is kwargs for compile_program (source_code, out_path, flags, workdir)."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(compile_program, a.pop("source_code"), a.pop("out_path"), **a)
        fb = ex.submit(compile_program, b.pop("source_code"), b.pop("out_path"), **b)
        return fa.result(), fb.result()


@lru_cache(maxsize=1)
def sanitizer_toolchain() -> tuple[str, str] | None:
    """Return (cxx, std_flag) whose -fsanitize=address,undefined links, else None."""
    probe = "int main(){return 0;}"
    for cxx, std in ((CXX, "-std=c++20"), ("g++", "-std=c++2a"), ("g++", "-std=c++17")):
        with tempfile.TemporaryDirectory(prefix="verto-san-probe-") as wd:
            src = Path(wd) / "p.cpp"
            src.write_text(probe, encoding="utf-8")
            r = sandbox.run([cxx, std, "-fsanitize=address,undefined",
                             str(src), "-o", str(Path(wd) / "p")], timeout_sec=60)
            if r.ok:
                return (cxx, std)
    return None
