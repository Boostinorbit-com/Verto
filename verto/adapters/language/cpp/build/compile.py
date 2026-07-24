"""C++ compile + executable cache.

Mirrors VERTO_Architecture §16.3. Uses the flags from compile_commands.json when
present (real projects REQUIRE it). Correctness runs add -fsanitize; performance
runs use real -O and are NEVER sanitized (distorts timing). All builds run in the
sandbox. An executable cache short-circuits identical (source, flags, compiler,
link_inputs) builds to ~a hardlink; ccache serves the object; a fast linker links.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .....runtime import sandbox
from .....runtime.fs import unique_tmp

CXX = "clang++"
STD = "-std=c++20"


@lru_cache(maxsize=1)
def _ccache() -> list[str]:
    """Prefix compiler invocations with ccache when it's on PATH — transparent
    object-file caching. Huge win on repeat runs (the STL template instantiation
    of an unchanged original is served from cache). No-op if ccache is absent."""
    return ["ccache"] if shutil.which("ccache") else []


@lru_cache(maxsize=8)
def _fast_linker(cxx: str) -> tuple[str, ...]:
    """Fastest linker the compiler can drive (mold > lld > gold > default).

    Linking is the UNCACHED part of a warm build — ccache serves the object file
    in ~10ms but the link still runs every time (~60ms with GNU ld). A fast linker
    cuts that directly. gold ships with binutils (~2x); mold (`apt install mold`)
    is ~6-8x and auto-activates here once present."""
    probe = "int main(){return 0;}"
    for ld in ("mold", "lld", "gold"):
        with tempfile.TemporaryDirectory(prefix="verto-ld-") as wd:
            src = Path(wd) / "p.cpp"
            src.write_text(probe, encoding="utf-8")
            r = sandbox.run([cxx, f"-fuse-ld={ld}", str(src), "-o", str(Path(wd) / "p")],
                            timeout_sec=30)
            if r.ok:
                return (f"-fuse-ld={ld}",)
    return ()


@dataclass
class Artifact:
    binary_path: str
    build_ok: bool
    stderr: str = ""


def _exe_place(cached: str, out_path: str) -> None:
    """Put a cached binary at out_path — hardlink (instant) or copy across FS."""
    try:
        if os.path.lexists(out_path):
            os.unlink(out_path)
        os.link(cached, out_path)
    except OSError:
        shutil.copy2(cached, out_path)


def _exe_store(binary_path: str, cached: str) -> None:
    """Atomically add a freshly built binary to the exe cache (best-effort)."""
    tmp = unique_tmp(cached)   # process/thread-unique (item #8)
    try:
        shutil.copy2(binary_path, tmp)
        os.replace(tmp, cached)                      # atomic; safe under concurrency
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _build_program(source_code: str, out_path: str, flags: list[str],
                   workdir: str, cxx: str, link_inputs: list[str]) -> Artifact:
    cc = _ccache()
    if cc:
        # ccache only caches compile-to-object (-c), never a combined compile+link,
        # so split the two. The -c step is compiled from a CONTENT-ADDRESSED stable
        # path so the source's location doesn't leak into the preprocessed output and
        # bust the cache. The link step (fast linker) is cheap and left uncached.
        h = hashlib.sha1(source_code.encode("utf-8")).hexdigest()[:16]
        srcdir = Path(tempfile.gettempdir()) / "verto-ccsrc"
        srcdir.mkdir(exist_ok=True)
        src = srcdir / f"{h}.cpp"
        if not src.exists():
            src.write_text(source_code, encoding="utf-8")
        obj = f"{out_path}.o"
        r = sandbox.run([*cc, cxx, *flags, "-c", str(src), "-o", obj], timeout_sec=120)
        if r.ok:   # fast linker only on the (uncached) link step; ignored on -c.
            # link_inputs (the project archive) come AFTER our object so the linker
            # pulls only the members that resolve its undefined symbols.
            r = sandbox.run([cxx, *flags, *_fast_linker(cxx), obj, *link_inputs, "-o", out_path],
                            timeout_sec=120)
        return Artifact(binary_path=out_path, build_ok=r.ok, stderr=r.stderr)

    # no ccache: one compile+link step (splitting would only add overhead here)
    src = Path(workdir) / (Path(out_path).name + ".cpp")
    src.write_text(source_code, encoding="utf-8")
    res = sandbox.run([cxx, *flags, *_fast_linker(cxx), str(src), *link_inputs, "-o", out_path],
                      timeout_sec=120)
    return Artifact(binary_path=out_path, build_ok=res.ok, stderr=res.stderr)


def compile_program(source_code: str, out_path: str, *, flags: list[str],
                    workdir: str, cxx: str = CXX, link_inputs: tuple = ()) -> Artifact:
    """Compile+link `source_code` to out_path.

    `link_inputs` are extra link-step inputs (codebase mode: the project archive,
    so the function can call into its real dependencies — Phase-1 item #1). Empty
    in single-file mode, where the harness is fully self-contained.

    An EXECUTABLE cache short-circuits the whole build: identical
    (source, flags, compiler, link_inputs) => reuse the prior binary, skipping
    compile AND link (a repeat run becomes ~a hardlink). On a miss, ccache still
    serves the object and the fast linker links; then the finished binary is cached
    for next time. Deterministic builds make this safe — same inputs, byte-
    equivalent behaviour. (link_inputs paths are content-addressed archive names,
    so including them in the key tracks their content.)"""
    li = list(link_inputs)
    key = hashlib.sha1(("\0".join((cxx, *flags, *li)) + "\0" + source_code).encode("utf-8")).hexdigest()
    cache_dir = Path(tempfile.gettempdir()) / "verto-exe"
    cache_dir.mkdir(exist_ok=True)
    cached = cache_dir / key
    if cached.exists():
        _exe_place(str(cached), out_path)
        return Artifact(binary_path=out_path, build_ok=True)

    art = _build_program(source_code, out_path, flags, workdir, cxx, li)
    if art.build_ok and os.path.exists(out_path):
        _exe_store(out_path, str(cached))
    return art


def compile_pair(a: dict, b: dict) -> tuple[Artifact, Artifact]:
    """Compile two programs concurrently (each blocks on its own subprocess).
    Each dict is kwargs for compile_program (source_code, out_path, flags, workdir)."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(compile_program, a.pop("source_code"), a.pop("out_path"), **a)
        fb = ex.submit(compile_program, b.pop("source_code"), b.pop("out_path"), **b)
        return fa.result(), fb.result()
