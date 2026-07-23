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
        reuse: object | None = None,      # test-reuse oracle (item #3), injected by the registry
    ) -> None:
        self._correctness = correctness
        self._performance = performance
        self._policy = config
        self._reuse = reuse

    def decide(self, orig: Target, var: Variant, candidate: Candidate, inputs: object) -> Verdict:
        with tempfile.TemporaryDirectory(prefix="verto-verify-") as wd:
            # codebase mode threads the TU's -I/-D/-std AND the project archive
            # (Phase-1 item #1) to the harness compiles
            ctx = VerifyCtx(workdir=wd,
                            extra_cflags=tuple(orig.build.get("compile_flags", ())),
                            link_inputs=tuple(orig.build.get("link_inputs", ())),
                            opt_flags=tuple(orig.build.get("opt_flags", ())))

            # --- correctness (may not be lowered silently) ---
            cv = self._correctness.equivalent(orig, var, inputs, ctx=ctx)
            if not cv.passed:
                if not cv.witness.build_ok:
                    # a broken ORIGINAL harness = can't verify = skip, not reject
                    reason = ("skipped_unverifiable"
                              if cv.witness.sanitizer == "orig_build_failed" else "build_failed")
                else:
                    reason = "changed_output"
                return Verdict(False, candidate, cv, None, reason=reason)
            if cv.rung < self._policy.min_rung:
                # includes the Category-C win: passed diff-testing but sanitizer tripped
                return Verdict(False, candidate, cv, None, reason="unsafe")

            # --- performance (Pareto; reuses the binaries correctness built) ---
            pv = self._performance.compare(orig, var, ctx=ctx)
            if not pv.pareto_pass:
                return Verdict(False, candidate, cv, pv, reason=pv.reason or "slower")

            # --- test-reuse confirmation (item #3): the project's OWN tests, if any ---
            # A change the synthetic harness accepted must also survive the project's
            # real acceptance criteria. Only runs when a test_command is configured,
            # and only on otherwise-accepted changes (rebuilding the project is costly).
            if self._reuse is not None and self._reuse.enabled():
                rv = self._reuse.confirm(orig, var)
                if rv.available and not rv.passed:
                    return Verdict(False, candidate, cv, pv, reason="tests_failed")
                v = Verdict(True, candidate, cv, pv, reason="accepted")
                v.tests_confirmed = rv.available and rv.passed
                return v

            return Verdict(True, candidate, cv, pv, reason="accepted")
