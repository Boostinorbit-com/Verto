"""Correctness Oracle (Performance domain) — the graded correctness ladder. TRUSTED.

Mirrors VERTO.md §9.2 and VERTO_Architecture §16.4:

  Rung 1  differential test — run original + variant on held-out inputs (check
          mode), assert identical output (exact, or within fp_tolerance — item #1b).
  Rung 3  sanitizers — rebuild the variant with -fsanitize and run; ANY diagnostic
          => reject (the trap for "equivalent under -O2 but relies on UB"). TSan
          (item #1a) downgrades a clean result if it catches a data race.

This module owns only the ORCHESTRATION; the diff-test compare lives in
`compare.py` and the sanitizer builds/evaluation in `sanitizers.py`. When a
VerifyCtx is provided, the original/variant binaries are shared with the
Performance oracle (compiled once).
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
from . import sanitizers
from ._verify import get_or_build_pair
from .compare import _first_diff, _outputs_match  # noqa: F401 (_outputs_match re-exported)
from .harness import make_program


_ERR_LOC = re.compile(r"^\S+?:\d+(:\d+)?:\s*")     # "file:line:col: " — always OUR harness, so noise
_ERR_HIT = ("error:", "undefined reference", "undefined symbol")


def _build_error(*stderrs: str) -> str:
    """The one line that says WHY the build failed.

    A compiler ends its output with a summary — "1 error generated." — so taking
    the LAST stderr line (what we used to do) reliably surfaced the least
    informative line and threw away the diagnostic right above it. Prefer the first
    real error; fall back to the last non-empty line only if none looks like one.
    """
    lines = [ln.strip() for text in stderrs for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        if any(h in ln for h in _ERR_HIT):
            return _ERR_LOC.sub("", ln)                # the location is our temp harness: drop it
    return lines[-1] if lines else ""


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
            # The sanitizer builds are INDEPENDENT of the diff-test build, so launch
            # them concurrently and let them finish under the pair-build's shadow —
            # free on both accept and reject paths. shutdown(wait=True) at `with`
            # exit guarantees no compile is left writing into a workdir we'll delete.
            with ThreadPoolExecutor(max_workers=2) as ex:
                # fast mode (policy min_rung < 3) never consults Rung 3, so don't pay
                # to build/run the sanitizers at all — the source of its speedup.
                want_san = getattr(self._config, "min_rung", 3) >= 3
                san_future, tsan_future = sanitizers.submit_builds(
                    ex, wd, var_src, func, ctx, want_san)

                # --- Rung 1: differential test (shared build; check mode) ---
                a, b = get_or_build_pair(ctx, wd, make_program(orig_src, func), "orig",
                                         make_program(var_src, func), "var")
                if not (a.build_ok and b.build_ok):
                    # A broken ORIGINAL harness = can't verify at all (e.g. a dependency
                    # outside the archive) → honest SKIP, not a rejection of the variant.
                    marker = "orig_build_failed" if not a.build_ok else "var_build_failed"
                    return CorrectnessVerdict(0, False, Witness(
                        build_ok=False, sanitizer=marker,
                        build_error=_build_error(a.stderr, b.stderr) or marker))

                out_a = sandbox.run([a.binary_path, "check"], input_text=stdin, isolate=True)
                out_b = sandbox.run([b.binary_path, "check"], input_text=stdin, isolate=True)
                tol = getattr(self._config, "fp_tolerance", 0.0) or 0.0
                if not _outputs_match(out_a.stdout, out_b.stdout, tol):
                    return CorrectnessVerdict(0, False, Witness(
                        build_ok=True, first_divergence=_first_diff(out_a.stdout, out_b.stdout)))

                # --- Rung 3: sanitizers (already compiling above) ---
                rung, sanitizer = sanitizers.evaluate(san_future, tsan_future, stdin, want_san)

            n_inputs = len(inputs.values()) if hasattr(inputs, "values") else 0
            return CorrectnessVerdict(rung, True,
                                      Witness(build_ok=True, inputs_run=n_inputs, sanitizer=sanitizer))
        finally:
            if own_wd:
                shutil.rmtree(own_wd, ignore_errors=True)
