"""Sanitizer builds + evaluation for the correctness ladder.

Rung 3 = ASan+UBSan clean; TSan (item #1a) can only DOWNGRADE a clean result when
it catches a data race the ASan build can't see. The builds are launched
concurrently under the shadow of the diff-test's orig+var compile, so they're
~free on both accept and reject paths.
"""
from __future__ import annotations

import re

from ....runtime import sandbox
from ...language.cpp.build import compile_program, sanitizer_toolchain, tsan_toolchain
from .harness import make_program

_SAN_MARKERS = re.compile(r"runtime error:|AddressSanitizer|UndefinedBehaviorSanitizer|SUMMARY: ")
_RACE_MARKERS = re.compile(r"ThreadSanitizer|data race")


def submit_builds(ex, wd: str, var_src: str, func: str, ctx, want_san: bool):
    """Submit the ASan/UBSan build (and, when the variant has a `static` local, a
    TSan build) to executor `ex`. Returns (san_future|None, tsan_future|None)."""
    # Keep the codebase -I/-D (needed to find headers) but DROP any db -std: the
    # sanitizer toolchain supplies its own compatible std, and a fallback g++ may not
    # recognize the db's dialect (clang's -std=c++20 vs older g++'s -std=c++2a).
    extra = [f for f in (getattr(ctx, "extra_cflags", ()) or []) if not f.startswith("-std=")]
    link = tuple(getattr(ctx, "link_inputs", ()) or ())   # codebase archive
    san_future = tsan_future = None

    tc = sanitizer_toolchain() if want_san else None
    if tc is not None:
        cxx, std = tc
        san_future = ex.submit(
            compile_program, make_program(var_src, func), f"{wd}/var_san",
            flags=[std, "-O1", "-fsanitize=address,undefined",
                   "-fno-omit-frame-pointer", "-pthread", *extra], workdir=wd, cxx=cxx,
            link_inputs=link)

    # item #1a: a data race only surfaces under concurrency, and only a transform
    # that adds shared mutable state can introduce one — gate TSan on a `static`
    # local in the variant so pure functions pay nothing.
    ttc = tsan_toolchain() if (want_san and "static" in var_src) else None
    if ttc is not None:
        cxx, std = ttc
        tsan_future = ex.submit(
            compile_program, make_program(var_src, func), f"{wd}/var_tsan",
            flags=[std, "-O1", "-fsanitize=thread", "-pthread", *extra],
            workdir=wd, cxx=cxx, link_inputs=link)
    return san_future, tsan_future


def evaluate(san_future, tsan_future, stdin: str, want_san: bool) -> tuple[int, str]:
    """Run the submitted sanitizer binaries and return (rung, sanitizer_str).
    Rung 3 iff ASan/UBSan clean AND (no TSan, or TSan clean)."""
    rung, sanitizer = 1, ("skipped(fast)" if not want_san else "unavailable")
    if san_future is not None:
        san = san_future.result()
        if not san.build_ok:
            sanitizer = "san-build-failed"
        else:
            r = sandbox.run([san.binary_path, "check"], input_text=stdin)
            blob = r.stdout + r.stderr
            if _SAN_MARKERS.search(blob):
                sanitizer = _san_summary(blob)  # tripped -> stays Rung 1 -> "unsafe"
            else:
                rung, sanitizer = 3, "clean"
    # ThreadSanitizer can only DOWNGRADE a clean result.
    if rung == 3 and tsan_future is not None:
        t = tsan_future.result()
        if t.build_ok:
            r = sandbox.run([t.binary_path, "race", "4096"], input_text="")
            if _RACE_MARKERS.search(r.stdout + r.stderr):
                rung, sanitizer = 1, "tsan:data race"
    return rung, sanitizer


def _san_summary(blob: str) -> str:
    m = re.search(r"runtime error: .*", blob) or re.search(r"ERROR: \w+Sanitizer.*", blob)
    return (m.group(0)[:120] if m else "sanitizer tripped")
