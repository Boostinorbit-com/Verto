"""Correctness Oracle (Performance domain) — the graded correctness ladder. TRUSTED.

Mirrors AION.md §9.2 and AION_Architecture §16.4:

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
from pathlib import Path

from ....engine.config import Config
from ....engine.models import CorrectnessVerdict, Target, Variant, Witness
from ....runtime import sandbox
from ...language.cpp.build import compile_program, sanitizer_toolchain
from ._verify import get_or_build_pair
from .harness import make_program

_SAN_MARKERS = re.compile(r"runtime error:|AddressSanitizer|UndefinedBehaviorSanitizer|SUMMARY: ")


class PerfCorrectnessOracle:
    def __init__(self, config: Config) -> None:
        self._config = config

    def equivalent(self, orig: Target, var: Variant, inputs: object,
                   ctx: object | None = None) -> CorrectnessVerdict:
        func = orig.symbol
        orig_src = Path(orig.file).read_text(encoding="utf-8")
        var_src = var.source_after
        stdin = inputs.as_stdin() if hasattr(inputs, "as_stdin") else ""

        own_wd = tempfile.mkdtemp(prefix="aion-corr-") if ctx is None else None
        wd = own_wd if ctx is None else ctx.workdir
        try:
            # --- Rung 1: differential test (shared build; check mode) ---
            a, b = get_or_build_pair(ctx, wd, make_program(orig_src, func), "orig",
                                     make_program(var_src, func), "var")
            if not (a.build_ok and b.build_ok):
                err = (a.stderr + b.stderr).strip().splitlines()[-1:] or ["build failed"]
                return CorrectnessVerdict(0, False, Witness(build_ok=False, sanitizer=err[0]))

            out_a = sandbox.run([a.binary_path, "check"], input_text=stdin)
            out_b = sandbox.run([b.binary_path, "check"], input_text=stdin)
            if out_a.stdout != out_b.stdout:
                return CorrectnessVerdict(0, False,
                                          Witness(build_ok=True, first_divergence=_first_diff(out_a.stdout, out_b.stdout)))

            # --- Rung 3: sanitizers on the variant (auto-detected toolchain) ---
            tc = sanitizer_toolchain()
            rung, sanitizer = 1, "unavailable"
            if tc is not None:
                san_cxx, san_std = tc
                san = compile_program(
                    make_program(var_src, func), f"{wd}/var_san",
                    flags=[san_std, "-O1", "-fsanitize=address,undefined",
                           "-fno-omit-frame-pointer"], workdir=wd, cxx=san_cxx)
                if not san.build_ok:
                    sanitizer = "san-build-failed"
                else:
                    r = sandbox.run([san.binary_path, "check"], input_text=stdin)
                    blob = r.stdout + r.stderr
                    if _SAN_MARKERS.search(blob):
                        sanitizer = _san_summary(blob)      # tripped -> stays Rung 1 -> "unsafe"
                    else:
                        rung, sanitizer = 3, "clean"

            n_inputs = len(inputs.values()) if hasattr(inputs, "values") else 0
            return CorrectnessVerdict(rung, True,
                                      Witness(build_ok=True, inputs_run=n_inputs, sanitizer=sanitizer))
        finally:
            if own_wd:
                shutil.rmtree(own_wd, ignore_errors=True)


def _first_diff(a: str, b: str) -> str:
    for i, (x, y) in enumerate(zip(a.splitlines(), b.splitlines())):
        if x != y:
            return f"line {i + 1}: {x!r} != {y!r}"
    return "outputs differ in length"


def _san_summary(blob: str) -> str:
    m = re.search(r"runtime error: .*", blob) or re.search(r"ERROR: \w+Sanitizer.*", blob)
    return (m.group(0)[:120] if m else "sanitizer tripped")
