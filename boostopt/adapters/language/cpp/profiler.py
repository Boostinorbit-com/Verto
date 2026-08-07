"""Micro-profiler — rank candidate functions by cost (v0 stand-in for perf).

When a file has several optimization candidates, BOOSTOPT must optimize the one that
is actually HOT. This compiles a driver that calls each candidate with a
representative input and times it, returning {func: ms}. It is a v0 heuristic;
the real path is an external runtime profile (`--profile perf.data`) — see
BOOSTOPT_Surfaces / BOOSTOPT_Architecture §11 (Evidence).
"""
from __future__ import annotations

import tempfile

from ....runtime import sandbox
from .build import compile_program


def _driver(source: str, funcs: list[str], n: int) -> str:
    body = ""
    for f in funcs:
        body += (
            f"  {{ auto t0 = std::chrono::steady_clock::now(); volatile long s = 0;\n"
            f"     auto v = {f}({n}UL); s += (long)v.size();\n"
            f"     auto t1 = std::chrono::steady_clock::now(); (void)s;\n"
            f'     std::printf("{f} %.6f\\n", '
            f"std::chrono::duration<double, std::milli>(t1 - t0).count()); }}\n"
        )
    return ("#include <cstdio>\n#include <chrono>\n" + source
            + "\nint main(){\n" + body + "  return 0;\n}\n")


def profile_functions(source: str, funcs: list[str], *, n: int = 200_000) -> dict[str, float]:
    with tempfile.TemporaryDirectory(prefix="boostopt-prof-") as wd:
        art = compile_program(_driver(source, funcs, n), f"{wd}/prof",
                              flags=["-std=c++20", "-O2"], workdir=wd)
        if not art.build_ok:
            return {}
        res = sandbox.run([art.binary_path], timeout_sec=60, isolate=True)
    times: dict[str, float] = {}
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                times[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return times
