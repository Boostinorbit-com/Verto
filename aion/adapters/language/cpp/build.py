"""C++ build — compile a program via clang++ (with a sanitizer-toolchain fallback).

Mirrors AION_Architecture §16.3. Uses the flags from compile_commands.json when
present (real projects REQUIRE it). Correctness runs add -fsanitize; performance
runs use real -O and are NEVER sanitized (distorts timing). All builds run in the
sandbox.

Sanitizer runtimes are not always shipped with a given clang build, so Rung 3
auto-detects a toolchain whose -fsanitize actually links (clang++, else g++).
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ....runtime import sandbox

CXX = "clang++"
STD = "-std=c++20"


@dataclass
class Artifact:
    binary_path: str
    build_ok: bool
    stderr: str = ""


def compile_program(source_code: str, out_path: str, *, flags: list[str],
                    workdir: str, cxx: str = CXX) -> Artifact:
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
        with tempfile.TemporaryDirectory(prefix="aion-san-probe-") as wd:
            src = Path(wd) / "p.cpp"
            src.write_text(probe, encoding="utf-8")
            r = sandbox.run([cxx, std, "-fsanitize=address,undefined",
                             str(src), "-o", str(Path(wd) / "p")], timeout_sec=60)
            if r.ok:
                return (cxx, std)
    return None
