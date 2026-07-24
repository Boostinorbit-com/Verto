"""The Invariant Gate — the single ACCEPT decision. TRUSTED.

Mirrors VERTO_Architecture §7 (Invariant Gate) and the invariant (VERTO.md §7):

    accept  <=>  correctness.rung >= policy.min_rung  AND  performance.pareto_pass

This is the ONLY place in the codebase that returns accepted=True. It consults
NO model. It owns a per-decision workdir + build cache (VerifyCtx) so the
original/variant are compiled once and shared by both oracles.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from .config import Config
from .models import (Candidate, CorrectnessVerdict, PerfVerdict, Target, Variant,
                     Verdict, VerifyCtx, Witness)
from .ports import CorrectnessOracle, PerformanceOracle


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


class InvariantGate:
    def __init__(
        self,
        correctness: CorrectnessOracle,
        performance: PerformanceOracle,
        config: Config,
        reuse: object | None = None,      # test-reuse oracle (item #3), injected by the registry
        metamorphic: object | None = None,  # metamorphic property oracle (2D), injected by the registry
    ) -> None:
        self._correctness = correctness
        self._performance = performance
        self._policy = config
        self._reuse = reuse
        self._meta = metamorphic

    def decide(self, orig: Target, var: Variant, candidate: Candidate, inputs: object) -> Verdict:
        # 2A — test-primary path: the function is one the synthetic harness can't build
        # an oracle for, so correctness comes from the project's OWN tests and perf from
        # its OWN bench, not the micro-harness. Kept as a distinct, self-contained branch
        # so the trusted harness invariant below is untouched.
        if getattr(orig, "verify_mode", "harness") == "tests":
            return self._decide_via_tests(orig, var, candidate)

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

            # --- 2D: metamorphic property rung (Rung 2, opt-in) ---
            # A change that BROKE a property the original had is rejected, even though the
            # fixed-input differential test passed. Only ever rejects (sound); stands down
            # when the property doesn't apply.
            meta_prop = ""
            if self._meta is not None:
                mv = self._meta.check(_read(orig.file), var.source_after, orig.symbol)
                if mv.applicable and not mv.passed:
                    return Verdict(False, candidate, cv, pv, reason="metamorphic_failed")
                meta_prop = mv.prop if mv.applicable else ""

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
                v.metamorphic = meta_prop
                return v

            v = Verdict(True, candidate, cv, pv, reason="accepted")
            v.metamorphic = meta_prop
            return v

    def _decide_via_tests(self, orig: Target, var: Variant, candidate: Candidate) -> Verdict:
        """2A: accept iff the project's OWN tests still pass on the variant AND the
        project bench is faster. Correctness basis is the test suite (via='tests'), not
        the sanitizer ladder — the verdict says so honestly. Verify-or-skip: no usable
        test baseline or no bench signal → skip, never a false accept."""
        reuse = self._reuse
        if reuse is None or not reuse.enabled():
            return Verdict(False, candidate, None, None, reason="skipped_unverifiable")
        # correctness — the project's tests (original must pass, variant must pass)
        rv = reuse.confirm(orig, var)
        if not rv.available:
            return Verdict(False, candidate, None, None, reason="skipped_unverifiable")
        cv = CorrectnessVerdict(rung=1, passed=rv.passed,
                                witness=Witness(build_ok=True, sanitizer="project-tests"))
        if not rv.passed:
            return Verdict(False, candidate, cv, None, reason="tests_failed")
        # performance — the project's own bench (can't prove faster without it → skip)
        if not reuse.bench_enabled():
            return Verdict(False, candidate, cv, None, reason="perf_unproven")
        bv = reuse.bench(orig, var)
        pv = PerfVerdict(vector=(bv.vector or {"p50": bv.after, "p50_before": bv.before,
                                               "p50_delta_pct": bv.delta_pct}),
                         pareto_pass=bv.faster, samples=bv.runs,
                         reason=("" if bv.faster else bv.detail))
        if not bv.available:
            return Verdict(False, candidate, cv, pv, reason="perf_unproven")
        if not bv.faster:
            return Verdict(False, candidate, cv, pv, reason="slower")
        v = Verdict(True, candidate, cv, pv, reason="accepted")
        v.via = "tests"
        v.tests_confirmed = True
        return v
