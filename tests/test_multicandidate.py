"""#11 multi-candidate — the orchestrator draws N proposals per hotspot, gates each, and
keeps the accepted one with the largest speedup. Tested deterministically with stub
adapters (no model): three llm_rewrite candidates with different measured deltas → the
best one wins; identical rewrites are deduped."""
from types import SimpleNamespace

from verto.engine.ledger import JsonlLedger
from verto.engine.models import (Candidate, Contract, CorrectnessVerdict, Evidence,
                                 PerfVerdict, Target, Variant, Verdict)
from verto.engine.orchestrator import AdapterSet, Orchestrator


class _StubProposer:
    """Yields one llm_rewrite candidate per call, cycling through `deltas` (a fresh
    source_after each) — like an LLM returning a different rewrite each draw."""
    def __init__(self, deltas):
        self._deltas = list(deltas)
        self.i = 0

    def propose(self, ev, priors):
        if self.i >= len(self._deltas):
            return None
        d = self._deltas[self.i]
        self.i += 1
        t = SimpleNamespace(name="llm_rewrite", delta=d,
                            rewrite=lambda src, d=d: (src + f"//{d}", ""))
        return Candidate(transform=t, contract=Contract(), rationale="stub")


class _StubMutator:
    def apply(self, target, transform):
        return Variant(target=target, patch="", source_after=f"rewritten({transform.delta})")


class _StubGate:
    """Accepts every variant; its p50 delta is encoded in the source_after (unique per draw)."""
    def decide(self, orig, var, cand, inputs):
        d = cand.transform.delta
        return Verdict(True, cand, CorrectnessVerdict(3, True),
                       PerfVerdict(vector={"p50_delta_pct": d}, pareto_pass=True), reason="accepted")


def _orch(deltas, candidates):
    cfg = SimpleNamespace(model="local", candidates=candidates)
    adapters = AdapterSet(sensor=None, proposer=_StubProposer(deltas), mutator=_StubMutator(),
                          gate=_StubGate(), inputs=None, budget=None)
    o = Orchestrator(adapters, JsonlLedger("/dev/null"), config=cfg)
    ev = Evidence(target=Target("x.cpp", "f", 0, "cpp"), source="int f(){return 0;}")
    best, attempts = o._best_of_n(ev, priors=None, current=ev.target, n=candidates, tried_here=set())
    return best, attempts


def test_best_of_n_keeps_largest_speedup():
    best, attempts = _orch([10.0, 40.0, 25.0], candidates=3)
    assert len(attempts) == 3                       # all three drawn + gated
    assert best is not None
    assert best[0].performance.vector["p50_delta_pct"] == 40.0   # the winner


def test_best_of_n_dedups_identical_rewrites():
    best, attempts = _orch([15.0, 15.0, 15.0], candidates=3)   # identical variants
    assert len(attempts) == 1                       # deduped → gated once
    assert best[0].performance.vector["p50_delta_pct"] == 15.0


class _RaisingMutator:
    """Mimics the real mutator when a transform's rewrite() returns None (e.g. an LLM
    rewrite that changed nothing or couldn't be located)."""
    def apply(self, target, transform):
        raise ValueError(f"mutator: {transform.name} could not rewrite {target.file}")


def test_unappliable_candidate_is_rejected_not_fatal():
    """An LLM proposal the mutator can't apply must be a REJECTED proposal, never a crash
    that aborts the run (the untrusted-proposer contract)."""
    cfg = SimpleNamespace(model="local", candidates=1)
    adapters = AdapterSet(sensor=None, proposer=_StubProposer([10.0]), mutator=_RaisingMutator(),
                          gate=_StubGate(), inputs=None, budget=None)
    o = Orchestrator(adapters, JsonlLedger("/dev/null"), config=cfg)
    ev = Evidence(target=Target("x.cpp", "f", 0, "cpp"), source="int f(){return 0;}")
    best, attempts = o._best_of_n(ev, None, ev.target, n=1, tried_here=set())
    assert best is None                             # nothing applied → no win
    assert len(attempts) == 1 and not attempts[0].accepted
    assert attempts[0].reason == "mutation_failed"  # graceful reject, no exception raised


def test_n_candidates_is_one_for_rules():
    cfg = SimpleNamespace(model="rules", candidates=5)
    o = Orchestrator(AdapterSet(None, None, None, None, None), JsonlLedger("/dev/null"), config=cfg)
    assert o._n_candidates() == 1                   # rules are deterministic → never N draws


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
