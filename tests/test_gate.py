"""Gate tests — the trusted core. The invariant: accept ⟺ correct ∧ faster.

These pin the ONE behavior that must never regress (VERTO.md §7). As the real
oracles land (v0 step 3), extend these to prove the gate REJECTS a UB rewrite.
"""
from verto.engine.config import Config
from verto.engine.gate import InvariantGate
from verto.engine.models import (
    Candidate, Contract, CorrectnessVerdict, PerfVerdict, Target, Variant, Witness,
)


class _OK:
    def equivalent(self, o, v, i):
        return CorrectnessVerdict(rung=3, passed=True, witness=Witness())


class _Unsafe:
    def equivalent(self, o, v, i):
        return CorrectnessVerdict(rung=1, passed=True,
                                  witness=Witness(sanitizer="ubsan:signed-overflow"))


class _Faster:
    def compare(self, o, v):
        return PerfVerdict(vector={"p50": 2.35}, pareto_pass=True, samples=30)


class _Slower:
    def compare(self, o, v):
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
