"""Correctness Oracle (Performance domain) — the graded correctness ladder. TRUSTED.

Mirrors AION.md §9.2 and AION_Architecture §16.4. REAL implementation:

  Rung 1  differential test — build original + variant, run on held-out inputs,
          assert byte-identical output.
  Rung 3  sanitizers — rebuild the variant with -fsanitize=address,undefined and
          run; ANY diagnostic => reject (stays < min_rung). This is the
          trap-catcher: "equivalent under -O2 but relies on UB".
  Rung 2/4 (coverage fuzzing / Alive2) — TODO.

Returns {rung, witness}: the highest rung PASSED.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from ....engine.config import Config
from ....engine.models import CorrectnessVerdict, Target, Variant, Witness
from ....runtime import sandbox
from ...language.cpp.build import compile_program, sanitizer_toolchain
from .harness import make_program

_SAN_MARKERS = re.compile(r"runtime error:|AddressSanitizer|UndefinedBehaviorSanitizer|SUMMARY: ")


class PerfCorrectnessOracle:
    def __init__(self, config: Config) -> None:
        self._config = config

    def equivalent(self, orig: Target, var: Variant, inputs: object) -> CorrectnessVerdict:
        func = orig.symbol
        orig_src = Path(orig.file).read_text(encoding="utf-8")
        var_src = var.source_after
        stdin = inputs.as_stdin() if hasattr(inputs, "as_stdin") else ""

        with tempfile.TemporaryDirectory(prefix="aion-corr-") as wd:
            # --- Rung 1: differential test ---
            a = compile_program(make_program(orig_src, func, "correctness"),
                                f"{wd}/orig", flags=["-std=c++20", "-O2"], workdir=wd)
            b = compile_program(make_program(var_src, func, "correctness"),
                                f"{wd}/var", flags=["-std=c++20", "-O2"], workdir=wd)
            if not (a.build_ok and b.build_ok):
                err = (a.stderr + b.stderr).strip().splitlines()[-1:] or ["build failed"]
                return CorrectnessVerdict(0, False, Witness(build_ok=False, sanitizer=err[0]))

            out_a = sandbox.run([a.binary_path], input_text=stdin)
            out_b = sandbox.run([b.binary_path], input_text=stdin)
            if out_a.stdout != out_b.stdout:
                div = _first_diff(out_a.stdout, out_b.stdout)
                return CorrectnessVerdict(0, False,
                                          Witness(build_ok=True, first_divergence=div))

            # --- Rung 3: sanitizers on the variant (auto-detected toolchain) ---
            tc = sanitizer_toolchain()
            rung, sanitizer = 1, "unavailable"
            if tc is not None:
                san_cxx, san_std = tc
                san = compile_program(
                    make_program(var_src, func, "correctness"), f"{wd}/var_san",
                    flags=[san_std, "-O1", "-fsanitize=address,undefined",
                           "-fno-omit-frame-pointer"], workdir=wd, cxx=san_cxx)
                if not san.build_ok:
                    sanitizer = "san-build-failed"
                else:
                    r = sandbox.run([san.binary_path], input_text=stdin)
                    blob = r.stdout + r.stderr
                    if _SAN_MARKERS.search(blob):
                        sanitizer = _san_summary(blob)      # tripped -> stays Rung 1 -> "unsafe"
                    else:
                        rung, sanitizer = 3, "clean"

            return CorrectnessVerdict(
                rung, True,
                Witness(build_ok=True, inputs_run=len(inputs.values()), sanitizer=sanitizer),
            )


def _first_diff(a: str, b: str) -> str:
    for i, (x, y) in enumerate(zip(a.splitlines(), b.splitlines())):
        if x != y:
            return f"line {i + 1}: {x!r} != {y!r}"
    return "outputs differ in length"


def _san_summary(blob: str) -> str:
    m = re.search(r"runtime error: .*", blob) or re.search(r"ERROR: \w+Sanitizer.*", blob)
    return (m.group(0)[:120] if m else "sanitizer tripped")
