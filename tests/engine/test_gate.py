"""Gate tests — the trusted core. The invariant: accept ⟺ correct ∧ faster.

These pin the ONE behavior that must never regress (BOOSTOPT.md §7). As the real
oracles land (v0 step 3), extend these to prove the gate REJECTS a UB rewrite.
"""
from boostopt.engine.config import Config
from boostopt.engine.gate import InvariantGate
from boostopt.engine.models import (
    Candidate, Contract, CorrectnessVerdict, PerfVerdict, Target, Variant, Witness,
)


class _OK:
    def equivalent(self, o, v, i, ctx=None):
        return CorrectnessVerdict(rung=3, passed=True, witness=Witness())


class _Unsafe:
    def equivalent(self, o, v, i, ctx=None):
        return CorrectnessVerdict(rung=1, passed=True,
                                  witness=Witness(sanitizer="ubsan:signed-overflow"))


class _Faster:
    def compare(self, o, v, ctx=None):
        return PerfVerdict(vector={"p50": 2.35}, pareto_pass=True, samples=30)


class _Slower:
    def compare(self, o, v, ctx=None):
        return PerfVerdict(vector={"p50": 9.0}, pareto_pass=False, samples=30)


def _fixtures():
    t = Target(file="x.cpp", symbol="f", line=1, language="cpp")
    var = Variant(target=t, patch="", source_after="")
    cand = Candidate(transform=type("T", (), {"name": "t"})(), contract=Contract())
    return t, var, cand


def test_accepts_correct_and_faster():
    t, var, cand = _fixtures()
    g = InvariantGate(_OK(), _Faster(), Config())
    assert g.decide(t, var, cand, None).accepted is True


def test_rejects_unsafe_even_if_faster():
    t, var, cand = _fixtures()
    g = InvariantGate(_Unsafe(), _Faster(), Config())          # UB trips Rung 3
    v = g.decide(t, var, cand, None)
    assert v.accepted is False and v.reason == "unsafe"


def test_rejects_slower_even_if_correct():
    t, var, cand = _fixtures()
    g = InvariantGate(_OK(), _Slower(), Config())
    v = g.decide(t, var, cand, None)
    assert v.accepted is False and v.reason == "slower"


def test_confirm_rejects_unreproduced_win():
    """Noise-hardening (perf gate): a would-be ACCEPT whose independent re-measurement does NOT
    reproduce is REJECTED — this is the false-accept where benchmark noise reads a no-op change
    as a big speedup. On agreement, the CONSERVATIVE (smaller) gain is reported so a lucky spike
    can never inflate the stated number."""
    from boostopt.adapters.domain.performance.performance import PerformanceOracleImpl as P

    def accept(g):
        return (True, "", {"p50_delta_pct": g})
    reject = (False, "not faster (p50 +0.3% < 2%)", {"p50_delta_pct": 0.3})

    ok, reason, _ = P._confirm(accept(16.0), reject)            # noise spike didn't reproduce
    assert ok is False and "did not reproduce" in reason

    ok, _, vec = P._confirm(accept(50.0), accept(30.0))         # reproduced, 2nd smaller
    assert ok is True and vec["p50_delta_pct"] == 30.0          # report the conservative gain

    ok, _, vec = P._confirm(accept(30.0), accept(50.0))         # reproduced, 2nd larger
    assert ok is True and vec["p50_delta_pct"] == 30.0          # keep the smaller (first)
