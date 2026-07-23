"""Correctness Oracle (Performance domain) — the graded correctness ladder. TRUSTED.

Mirrors VERTO.md §9.2 and VERTO_Architecture §16.4:

  Rung 1  differential test — run original + variant on held-out inputs (check
          mode), assert byte-identical (order-sensitive) output.
  Rung 3  sanitizers — rebuild the variant with -fsanitize=address,undefined and
          run; ANY diagnostic => reject. The trap-catcher for "equivalent under
          -O2 but relies on UB".
  Rung 2/4 (coverage fuzzing / Alive2) — TODO.

Compiles the unified program (see harness.py). When a VerifyCtx is provided, the
original/variant binaries are shared with the Performance oracle (compiled once).
"""
from __future__ import annotations

import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ....engine.config import Config
from ....engine.models import CorrectnessVerdict, Target, Variant, Witness
from ....runtime import sandbox
from ...language.cpp.build import compile_program, sanitizer_toolchain, tsan_toolchain
from ._verify import get_or_build_pair
from .harness import make_program

_SAN_MARKERS = re.compile(r"runtime error:|AddressSanitizer|UndefinedBehaviorSanitizer|SUMMARY: ")
_RACE_MARKERS = re.compile(r"ThreadSanitizer|data race")


class PerfCorrectnessOracle:
    def __init__(self, config: Config) -> None:
        self._config = config

    def equivalent(self, orig: Target, var: Variant, inputs: object,
                   ctx: object | None = None) -> CorrectnessVerdict:
        func = orig.symbol
        orig_src = Path(orig.file).read_text(encoding="utf-8")
        var_src = var.source_after
        stdin = inputs.as_stdin() if hasattr(inputs, "as_stdin") else ""

        own_wd = tempfile.mkdtemp(prefix="verto-corr-") if ctx is None else None
        wd = own_wd if ctx is None else ctx.workdir
        try:
            # The sanitizer build (Rung 3) is INDEPENDENT of the diff-test build
            # and shorter than the orig+var wave, so we launch it concurrently and
            # let it finish under the pair-build's shadow — free on both accept and
            # reject paths. shutdown(wait=True) at the `with` exit guarantees no
            # compile is left writing into a workdir we're about to delete.
            with ThreadPoolExecutor(max_workers=2) as ex:
                # fast mode (policy min_rung < 3) never consults Rung 3, so don't
                # pay to build/run the sanitizer at all — the source of its speedup.
                want_san = getattr(self._config, "min_rung", 3) >= 3
                # Keep the codebase -I/-D (needed to find headers) but DROP any
                # db -std: the sanitizer toolchain supplies its own compatible
                # san_std, and a fallback g++ may not recognize the db's dialect
                # (e.g. clang's -std=c++20 vs older g++'s -std=c++2a).
                extra = [f for f in (getattr(ctx, "extra_cflags", ()) or [])
                         if not f.startswith("-std=")]
                link = tuple(getattr(ctx, "link_inputs", ()) or ())   # codebase archive

                tc = sanitizer_toolchain() if want_san else None
                san_future = None
                if tc is not None:
                    san_cxx, san_std = tc
                    san_future = ex.submit(
                        compile_program, make_program(var_src, func), f"{wd}/var_san",
                        flags=[san_std, "-O1", "-fsanitize=address,undefined",
                               "-fno-omit-frame-pointer", "-pthread", *extra], workdir=wd, cxx=san_cxx,
                        link_inputs=link)

                # item #1a: a data race only surfaces under concurrency, and only a
                # transform that adds shared mutable state can introduce one — gate
                # TSan on a `static` local in the variant so pure functions pay nothing.
                ttc = tsan_toolchain() if (want_san and "static" in var_src) else None
                tsan_future = None
                if ttc is not None:
                    tsan_cxx, tsan_std = ttc
                    tsan_future = ex.submit(
                        compile_program, make_program(var_src, func), f"{wd}/var_tsan",
                        flags=[tsan_std, "-O1", "-fsanitize=thread", "-pthread", *extra],
                        workdir=wd, cxx=tsan_cxx, link_inputs=link)

                # --- Rung 1: differential test (shared build; check mode) ---
                a, b = get_or_build_pair(ctx, wd, make_program(orig_src, func), "orig",
                                         make_program(var_src, func), "var")
                if not (a.build_ok and b.build_ok):
                    # If the ORIGINAL harness won't build/link, VERTO can't verify
                    # this function at all (e.g. a dependency outside the archive) —
                    # that's an honest SKIP, not a rejection of the variant. Mark it
                    # so the gate can tell the two apart (verify-or-skip contract).
                    marker = "orig_build_failed" if not a.build_ok else "var_build_failed"
                    err = (a.stderr + b.stderr).strip().splitlines()[-1:] or [marker]
                    return CorrectnessVerdict(0, False, Witness(build_ok=False, sanitizer=marker,
                                                                first_divergence=err[0]))

                out_a = sandbox.run([a.binary_path, "check"], input_text=stdin)
                out_b = sandbox.run([b.binary_path, "check"], input_text=stdin)
                # item #1b: with fp_tolerance>0, compare numerically within a relative
                # tolerance so a legit FP-reordering transform (reassociation/SIMD) is
                # accepted; default 0 keeps the strict byte-for-byte diff-test.
                tol = getattr(self._config, "fp_tolerance", 0.0) or 0.0
                if not _outputs_match(out_a.stdout, out_b.stdout, tol):
                    return CorrectnessVerdict(0, False,
                                              Witness(build_ok=True, first_divergence=_first_diff(out_a.stdout, out_b.stdout)))

                # --- Rung 3: sanitizers on the variant (already compiling above) ---
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
                # item #1a: ThreadSanitizer can only DOWNGRADE a clean result — a data
                # race the ASan/UBSan build can't see makes the change unsafe.
                if rung == 3 and tsan_future is not None:
                    t = tsan_future.result()
                    if t.build_ok:
                        r = sandbox.run([t.binary_path, "race", "4096"], input_text="")
                        if _RACE_MARKERS.search(r.stdout + r.stderr):
                            rung, sanitizer = 1, "tsan:data race"

            n_inputs = len(inputs.values()) if hasattr(inputs, "values") else 0
            return CorrectnessVerdict(rung, True,
                                      Witness(build_ok=True, inputs_run=n_inputs, sanitizer=sanitizer))
        finally:
            if own_wd:
                shutil.rmtree(own_wd, ignore_errors=True)


def _outputs_match(a: str, b: str, tol: float) -> bool:
    """Exact when tol<=0; otherwise token-wise, with numeric tokens compared within
    relative tolerance `tol` and everything else required equal (item #1b)."""
    if tol <= 0:
        return a == b
    ta, tb = a.split(), b.split()
    if len(ta) != len(tb):
        return False
    for x, y in zip(ta, tb):
        if x == y:
            continue
        try:
            fx, fy = float(x), float(y)
        except ValueError:
            return False
        scale = max(abs(fx), abs(fy), 1e-12)
        if abs(fx - fy) / scale > tol:
            return False
    return True


def _first_diff(a: str, b: str) -> str:
    for i, (x, y) in enumerate(zip(a.splitlines(), b.splitlines())):
        if x != y:
            return f"line {i + 1}: {x!r} != {y!r}"
    return "outputs differ in length"


def _san_summary(blob: str) -> str:
    m = re.search(r"runtime error: .*", blob) or re.search(r"ERROR: \w+Sanitizer.*", blob)
    return (m.group(0)[:120] if m else "sanitizer tripped")
