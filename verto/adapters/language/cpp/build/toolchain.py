"""Sanitizer toolchain probes.

Sanitizer runtimes aren't always shipped with a given clang build, so each rung
auto-detects a toolchain whose `-fsanitize` actually links (clang++, else g++).
ASan+UBSan (Rung 3), TSan (item #1a), and MSan (item #1a; clang-only + needs an
instrumented libc++, so usually unavailable → probed and skipped cleanly).
"""
from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from .....runtime import sandbox
from .compile import CXX


@lru_cache(maxsize=1)
def sanitizer_toolchain() -> tuple[str, str] | None:
    """Return (cxx, std_flag) whose -fsanitize=address,undefined links, else None."""
    return _probe_sanitizer("-fsanitize=address,undefined")


@lru_cache(maxsize=1)
def tsan_toolchain() -> tuple[str, str] | None:
    """(cxx, std) whose -fsanitize=thread links (item #1a), else None. Threads need
    -pthread; the probe includes it so we only return a toolchain that fully links."""
    return _probe_sanitizer("-fsanitize=thread", "-pthread")


@lru_cache(maxsize=1)
def msan_toolchain() -> tuple[str, str] | None:
    """(cxx, std) whose -fsanitize=memory links (item #1a), else None. MSan is
    clang-only AND needs an instrumented libc++, so it is unavailable on most
    stock toolchains — we probe and skip cleanly when it won't link."""
    return _probe_sanitizer("-fsanitize=memory")


def _probe_sanitizer(*san_flags: str) -> tuple[str, str] | None:
    probe = "#include <thread>\nint main(){ std::thread t([]{}); t.join(); return 0; }"
    for cxx, std in ((CXX, "-std=c++20"), ("g++", "-std=c++2a"), ("g++", "-std=c++17")):
        with tempfile.TemporaryDirectory(prefix="verto-san-probe-") as wd:
            src = Path(wd) / "p.cpp"
            src.write_text(probe, encoding="utf-8")
            r = sandbox.run([cxx, std, *san_flags, "-pthread",
                             str(src), "-o", str(Path(wd) / "p")], timeout_sec=60)
            if r.ok:
                return (cxx, std)
    return None
