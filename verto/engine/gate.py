"""The Invariant Gate — the single ACCEPT decision. TRUSTED.

Mirrors VERTO_Architecture §7 (Invariant Gate) and the invariant (VERTO.md §7):

    accept  <=>  correctness.rung >= policy.min_rung  AND  performance.pareto_pass

This is the ONLY place in the codebase that returns accepted=True. It consults
NO model. It owns a per-decision workdir + build cache (VerifyCtx) so the
original/variant are compiled once and shared by both oracles.
"""
from __future__ import annotations

import tempfile

from .config import Config
from .models import Candidate, Target, Variant, Verdict, VerifyCtx
from .ports import CorrectnessOracle, PerformanceOracle


class InvariantGate:
    def __init__(
        self,
        correctness: CorrectnessOracle,
        performance: PerformanceOracle,
        config: Config,
    ) -> None:
        self._correctness = correctness
        self._performance = performance
        self._policy = config

    def decide(self, orig: Target, var: Variant, candidate: Candidate, inputs: object) -> Verdict:
        with tempfile.TemporaryDirectory(prefix="verto-verify-") as wd:
            # codebase mode threads the TU's -I/-D/-std to the harness compiles
            ctx = VerifyCtx(workdir=wd, extra_cflags=tuple(orig.build.get("compile_flags", ())))

            # --- correctness (may not be lowered silently) ---
            cv = self._correctness.equivalent(orig, var, inputs, ctx=ctx)
            if not cv.passed:
                reason = "build_failed" if not cv.witness.build_ok else "changed_output"
                return Verdict(False, candidate, cv, None, reason=reason)
            if cv.rung < self._policy.min_rung:
                # includes the Category-C win: passed diff-testing but sanitizer tripped
                return Verdict(False, candidate, cv, None, reason="unsafe")

            # --- performance (Pareto; reuses the binaries correctness built) ---
            pv = self._performance.compare(orig, var, ctx=ctx)
            if not pv.pareto_pass:
                return Verdict(False, candidate, cv, pv, reason=pv.reason or "slower")

            return Verdict(True, candidate, cv, pv, reason="accepted")
