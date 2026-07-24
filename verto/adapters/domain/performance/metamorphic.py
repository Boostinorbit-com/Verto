"""Metamorphic property oracle (2D — Rung 2). TRUSTED.

Some functions have no exact-output reference the fixed-input differential test can use
with full confidence — but they DO satisfy a metamorphic PROPERTY: a relation that must
hold whatever the exact output is. Checking the property is a real-but-weaker correctness
signal (Rung 2), between the differential test (Rung 1) and the sanitizers (Rung 3).

v0 supports ONE property — **permutation invariance**: for a function taking
`std::vector<int>` (by value or const&) and returning an integer, `f(v) == f(shuffle(v))`.
That's the property that makes reserve / container-swap transforms sound for order-
independent reductions; a transform that secretly introduces order-dependence breaks it.

Sound by construction: it only ever REJECTS (a property the ORIGINAL had that the VARIANT
broke). If the property doesn't apply — wrong signature, or the original isn't invariant —
it stands down (not applicable), never a false accept. Opt-in (`--metamorphic`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

_DRIVER = """
#include <vector>
#include <cstddef>
#include <cstdio>
int main() {{
    std::vector<int> v; v.reserve(2000);
    for (int i = 0; i < 2000; ++i) v.push_back((int)((unsigned)(i * 2654435761u) % 1000));
    std::vector<int> w = v;                              // a deterministic permutation of v
    for (std::size_t i = w.size(); i > 1; --i) {{
        std::size_t j = (std::size_t)((i * 2654435761u) % i);
        int t = w[i - 1]; w[i - 1] = w[j]; w[j] = t;
    }}
    long long a = (long long)({func}(v));
    long long b = (long long)({func}(w));
    std::printf("%lld %lld\\n", a, b);
    return 0;
}}
"""


@dataclass
class MetaVerdict:
    applicable: bool                 # did the property apply (right signature + holds on original)?
    passed: bool = False             # did the variant preserve it?
    prop: str = ""                   # which property
    detail: str = ""


def _compiler() -> str | None:
    return shutil.which("clang++") or shutil.which("g++")


class MetamorphicOracle:
    def __init__(self, config=None) -> None:
        self._cxx = _compiler()

    def enabled(self) -> bool:
        return bool(getattr(self, "_cxx", None))

    def check(self, orig_src: str, var_src: str, func: str) -> MetaVerdict:
        if not self._cxx or not func:
            return MetaVerdict(False, detail="no compiler / no symbol")
        with tempfile.TemporaryDirectory(prefix="verto-meta-") as wd:
            o = self._build_run(orig_src, func, wd, "mo")
            if o is None:                                   # wrong signature (won't build) → N/A
                return MetaVerdict(False, detail="function is not vector<int>→int, property N/A")
            if o[0] != o[1]:                                # original isn't invariant → property N/A
                return MetaVerdict(False, detail="original is not permutation-invariant")
            v = self._build_run(var_src, func, wd, "mv")
            if v is None:
                return MetaVerdict(True, False, "permutation-invariance", "variant failed to build")
            ok = v[0] == v[1]
            return MetaVerdict(True, ok, "permutation-invariance",
                               "preserved" if ok else "variant broke permutation-invariance")

    def _build_run(self, source: str, func: str, wd: str, tag: str):
        src = os.path.join(wd, tag + ".cpp")
        exe = os.path.join(wd, tag)
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(source + _DRIVER.format(func=func))
        try:
            b = subprocess.run([self._cxx, "-O2", "-std=c++20", src, "-o", exe],
                               capture_output=True, text=True, timeout=60)
            if b.returncode != 0:
                return None
            r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
        except Exception:
            return None
        if r.returncode != 0:
            return None
        parts = r.stdout.split()
        try:
            return (int(parts[0]), int(parts[1])) if len(parts) >= 2 else None
        except ValueError:
            return None
