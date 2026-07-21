"""The Invariant Gate — the single ACCEPT decision. TRUSTED.

Mirrors AION_Architecture §7 (Invariant Gate) and the invariant (AION.md §7):

    accept  <=>  correctness.rung >= policy.min_rung  AND  performance.pareto_pass

This is the ONLY place in the codebase that returns accepted=True. It consults
NO model. Swap or break the Proposer and this still holds.
"""
from __future__ import annotations

from .config import Config
from .models import Candidate, Target, Variant, Verdict
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
        # --- correctness (may not be lowered silently) ---
        cv = self._correctness.equivalent(orig, var, inputs)
        if not cv.passed:
            # distinguish a real build failure from a genuine behavior change
            reason = "build_failed" if not cv.witness.build_ok else "changed_output"
            return Verdict(False, candidate, cv, None, reason=reason)
        if cv.rung < self._policy.min_rung:
            # includes the Category-C win: passed diff-testing but sanitizer tripped
            return Verdict(False, candidate, cv, None, reason="unsafe")

        # --- performance (Pareto, not just median) ---
        pv = self._performance.compare(orig, var)
        if not pv.pareto_pass:
            return Verdict(False, candidate, cv, pv, reason="slower")

        # correct AND faster
        return Verdict(True, candidate, cv, pv, reason="accepted")
