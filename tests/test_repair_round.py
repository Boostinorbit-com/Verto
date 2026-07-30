"""Repair round — a draw the COMPILER rejected gets one second chance, with the error.

A small local model routinely proposes C++ that doesn't build (`std::list` has no
`operator[]`; a changed signature no longer matches the header). The compiler already said
exactly what was wrong, so the orchestrator hands that back to the proposer instead of
burning the draw. Tested deterministically with stub adapters (no model). The repaired
candidate goes through the SAME gate, so this is a yield knob, never a trust concession.
"""
from types import SimpleNamespace

from verto.engine.ledger import JsonlLedger
from verto.engine.models import (Candidate, Contract, CorrectnessVerdict, Evidence,
                                 PerfVerdict, Target, Variant, Verdict, Witness)
from verto.engine.orchestrator import AdapterSet, Orchestrator

_ERR = "error: type 'std::list<int>' does not provide a subscript operator"


def _transform(code):
    return SimpleNamespace(name="llm_rewrite", new_code=code,
                           rewrite=lambda src, c=code: (src + c, ""))


class _StubProposer:
    """First draw doesn't compile; repair() returns code that does. Records what it was told."""
    def __init__(self, *, repairs=True):
        self._repairs = repairs
        self.seen: list[tuple[str, str]] = []      # (code, error) passed to repair()

    def propose(self, ev, priors):
        return Candidate(transform=_transform("BROKEN"), contract=Contract(), rationale="stub")

    def repair(self, ev, priors, code, error):
        self.seen.append((code, error))
        if not self._repairs:
            return None
        return Candidate(transform=_transform("FIXED"), contract=Contract(), rationale="stub repair")


class _StubbornProposer(_StubProposer):
    """Answers every repair, but never with code that builds — a DISTINCT broken rewrite
    each time (identical ones would be deduped by the gate loop, not retried)."""
    def repair(self, ev, priors, code, error):
        self.seen.append((code, error))
        return Candidate(transform=_transform(f"BROKEN{len(self.seen)}"),
                         contract=Contract(), rationale="stub repair")


class _NoRepairProposer(_StubProposer):
    """A proposer with no repair() at all (e.g. the rules backend) — must be a no-op."""
    repair = None


class _StubMutator:
    def apply(self, target, transform):
        return Variant(target=target, patch="", source_after=f"src({transform.new_code})")


class _StubGate:
    """Rejects BROKEN as a variant build failure; accepts FIXED."""
    def decide(self, orig, var, cand, inputs):
        if cand.transform.new_code == "FIXED":
            return Verdict(True, cand, CorrectnessVerdict(3, True),
                           PerfVerdict(vector={"p50_delta_pct": 20.0}, pareto_pass=True),
                           reason="accepted")
        cv = CorrectnessVerdict(0, False, Witness(build_ok=False, sanitizer="var_build_failed",
                                                  build_error=_ERR))
        return Verdict(False, cand, cv, None, reason="build_failed")


def _run(proposer, **cfg_kw):
    cfg = SimpleNamespace(model="local", candidates=1, **{"repair_rounds": 1, **cfg_kw})
    adapters = AdapterSet(sensor=None, proposer=proposer, mutator=_StubMutator(),
                          gate=_StubGate(), inputs=None, budget=None)
    o = Orchestrator(adapters, JsonlLedger("/dev/null"), config=cfg)
    ev = Evidence(target=Target("x.cpp", "f", 0, "cpp"), source="int f(){return 0;}")
    return o._best_of_n(ev, priors=None, current=ev.target, n=1, tried_here=set())


def test_compile_error_is_repaired_into_an_accept():
    p = _StubProposer()
    best, attempts = _run(p)
    assert len(attempts) == 2                       # the broken draw, then the repair
    assert attempts[0].reason == "build_failed" and not attempts[0].accepted
    assert best is not None and best[0].accepted    # the repaired rewrite passed the gate
    assert best[0].performance.vector["p50_delta_pct"] == 20.0


def test_repair_is_given_the_broken_code_and_the_real_error():
    """The whole point: the model must see WHAT it wrote and WHY the compiler refused it."""
    p = _StubProposer()
    _run(p)
    assert p.seen == [("BROKEN", _ERR)]


def test_repair_rounds_zero_disables_it():
    p = _StubProposer()
    best, attempts = _run(p, repair_rounds=0)
    assert p.seen == [] and best is None and len(attempts) == 1


def test_empty_reply_ends_the_repair_immediately():
    """The proposer returned nothing (transport error, empty reply). Re-sending the same
    prompt would just fail again, so don't spend the remaining rounds on it."""
    p = _StubProposer(repairs=False)
    best, attempts = _run(p, repair_rounds=3)
    assert len(p.seen) == 1 and best is None and len(attempts) == 1


def test_three_rounds_retries_three_times_then_stops():
    """The shipped default. A model that never lands a fix costs exactly `repair_rounds`
    calls — no unbounded grinding — and each retry is told the CURRENT broken code, not
    the original one, so the conversation actually advances."""
    p = _StubbornProposer()
    best, attempts = _run(p, repair_rounds=3)
    assert best is None
    assert [code for code, _ in p.seen] == ["BROKEN", "BROKEN1", "BROKEN2"]
    assert len(attempts) == 4                   # the draw + three gated repair attempts


def test_repair_stops_as_soon_as_it_lands():
    """A fix on the first retry must not burn the remaining rounds."""
    p = _StubProposer()
    best, attempts = _run(p, repair_rounds=3)
    assert len(p.seen) == 1 and best is not None and best[0].accepted


def test_proposer_without_repair_is_untouched():
    best, attempts = _run(_NoRepairProposer())
    assert best is None and len(attempts) == 1      # rules backend: no second call, no crash


def test_semantic_reject_is_not_repaired():
    """Only a COMPILER error is actionable. 'output differs' carries no diagnostic to send,
    and an ORIGINAL that won't build is our setup problem, not the model's."""
    class _DiffGate:
        def decide(self, orig, var, cand, inputs):
            cv = CorrectnessVerdict(0, False, Witness(build_ok=True, first_divergence="7 != 9"))
            return Verdict(False, cand, cv, None, reason="changed_output")

    p = _StubProposer()
    cfg = SimpleNamespace(model="local", candidates=1, repair_rounds=1)
    adapters = AdapterSet(sensor=None, proposer=p, mutator=_StubMutator(),
                          gate=_DiffGate(), inputs=None, budget=None)
    o = Orchestrator(adapters, JsonlLedger("/dev/null"), config=cfg)
    ev = Evidence(target=Target("x.cpp", "f", 0, "cpp"), source="int f(){return 0;}")
    best, attempts = o._best_of_n(ev, None, ev.target, n=1, tried_here=set())
    assert p.seen == [] and best is None and len(attempts) == 1


def test_original_build_failure_is_not_repaired():
    """orig_build_failed = VERTO couldn't compile the user's own file (missing include path).
    Asking the model to 'fix' that would blame it for our setup error."""
    class _OrigFailGate:
        def decide(self, orig, var, cand, inputs):
            cv = CorrectnessVerdict(0, False, Witness(build_ok=False, sanitizer="orig_build_failed",
                                                      build_error="fatal error: 'clist.h' file not found"))
            return Verdict(False, cand, cv, None, reason="skipped_unverifiable")

    p = _StubProposer()
    adapters = AdapterSet(sensor=None, proposer=p, mutator=_StubMutator(),
                          gate=_OrigFailGate(), inputs=None, budget=None)
    o = Orchestrator(adapters, JsonlLedger("/dev/null"),
                     config=SimpleNamespace(model="local", candidates=1, repair_rounds=1))
    ev = Evidence(target=Target("x.cpp", "f", 0, "cpp"), source="int f(){return 0;}")
    best, attempts = o._best_of_n(ev, None, ev.target, n=1, tried_here=set())
    assert p.seen == [] and best is None and len(attempts) == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
