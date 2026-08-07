"""CMake/ctest test discovery (2A-1) — auto-wire the project's tests as the oracle.

Point BOOSTOPT at a CMake BUILD directory (`--ctest-dir`) and it enumerates that project's
ctest tests (`ctest --show-only=json-v1`) and derives:

  - a **test_command** (correctness): `cmake --build <dir> && ctest …` — the rebuild is what
    makes the swapped-in variant actually get tested;
  - a **bench_command** (2A-3 perf signal): if a test looks like a benchmark (name contains
    "bench"/"perf"), `cmake --build <dir> && ctest -R <bench>`, timed.

So the user no longer hand-writes `--test-command`/`--bench-command`. v0 runs the WHOLE
suite for correctness (sound — any breakage rejects); the precise, coverage-guided "which
test exercises THIS TU" mapping is a follow-on.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Discovered:
    test_command: str | None = None
    bench_command: str | None = None
    bench_argv: tuple = field(default_factory=tuple)    # 2A-3: the bench's DIRECT executable (clean p50/p99/peak)
    build_command: str | None = None                    # 2A-3: rebuild once before timing
    tests: tuple = field(default_factory=tuple)         # all ctest test names
    targeted: bool = False                              # 2A-1: were the tests narrowed to the target TU?
    targeted_tests: tuple = field(default_factory=tuple)  # the tests that exercise the target TU


def _is_bench(name: str) -> bool:
    n = name.lower()
    return "bench" in n or "perf" in n


def _nm_symbols(path: str, mode: str = "all") -> set:
    """Symbols of an object/executable via `nm -P` (POSIX format: `name type …`).
    mode='strong_text' → only strong defined functions (type T); mode='all' → every symbol
    the file defines or references (so a test that CALLS the target is counted)."""
    if not (path and shutil.which("nm")):
        return set()
    try:
        r = subprocess.run(["nm", "-P", path], capture_output=True, text=True, timeout=30)
    except Exception:
        return set()
    out = set()
    for ln in r.stdout.splitlines():
        parts = ln.split()
        if len(parts) < 2:
            continue
        name, typ = parts[0], parts[1]
        if mode == "strong_text":
            if typ == "T":
                out.add(name)
        else:
            out.add(name)
    return out


def _tu_symbols(build_dir: str, target_file: str) -> set:
    """The strong function symbols the target TU (source file) defines — found via its
    compiled object (`<CMakeFiles>/…/<base>.cpp.o`)."""
    base = Path(target_file).name
    for cand in (base + ".o", Path(base).stem + ".o"):
        objs = list(Path(build_dir).rglob(cand))
        if objs:
            return _nm_symbols(str(objs[0]), mode="strong_text")
    return set()


def _exercises(exe: str, tu_syms: set) -> bool:
    """Does this test executable reference any of the target TU's symbols?"""
    return bool(tu_syms & _nm_symbols(exe, mode="all"))


def discover_ctest(build_dir: str, target_file: str | None = None) -> Discovered:
    """Best-effort: returns an empty Discovered if cmake/ctest are absent, the dir isn't a
    ctest build, or anything errors — the caller then falls back to manual flags.

    2A-1 TU-targeting: when `target_file` is given, the tests are narrowed to those whose
    executable references the target TU's symbols (via nm) — "which test exercises this TU."
    Sound fallback: if nothing can be resolved, the WHOLE suite is used (any breakage still
    rejects). Narrowing to a test that references the TU can only DROP tests that cannot
    touch the change, never one that could catch it."""
    if not (shutil.which("ctest") and shutil.which("cmake")):
        return Discovered()
    try:
        r = subprocess.run(["ctest", "--test-dir", build_dir, "--show-only=json-v1"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return Discovered()
        tests = [t for t in json.loads(r.stdout).get("tests", []) if t.get("name")]
    except Exception:
        return Discovered()
    if not tests:
        return Discovered()

    names = tuple(t["name"] for t in tests)
    q = shlex.quote(build_dir)
    rebuild = f"cmake --build {q}"                       # rebuild so the variant is what runs

    # 2A-1: narrow to the tests that exercise the target TU (else keep the whole suite).
    pool, targeted = tests, False
    if target_file:
        tu = _tu_symbols(build_dir, target_file)
        if tu:
            sel = [t for t in tests if _exercises((t.get("command") or [""])[0], tu)]
            if sel and len(sel) < len(tests):
                pool, targeted = sel, True

    bench = next((t for t in pool if _is_bench(t["name"])), None)
    corr = [t for t in pool if not _is_bench(t["name"])]
    if corr:                                             # run exactly the targeted correctness tests
        rx = "^(" + "|".join(re.escape(t["name"]) for t in corr) + ")$"
        test_cmd = f"{rebuild} && ctest --test-dir {q} -R {shlex.quote(rx)} --output-on-failure"
    elif bench:                                          # only a bench references it → exclude it, run the rest
        test_cmd = f"{rebuild} && ctest --test-dir {q} -E {shlex.quote(bench['name'])} --output-on-failure"
    else:
        test_cmd = f"{rebuild} && ctest --test-dir {q} --output-on-failure"

    return Discovered(
        test_command=test_cmd, bench_command=None,
        bench_argv=tuple(bench.get("command", []) or ()) if bench else (),
        build_command=rebuild if bench else None,
        tests=names, targeted=targeted, targeted_tests=tuple(t["name"] for t in pool))
