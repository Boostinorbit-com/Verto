"""Orchestrator — drives the four-stage loop. Language/domain-agnostic.

Mirrors AION_Architecture §9 (control flow). Owns iteration, transform ordering,
and stop conditions. Talks only to ports + the gate.
"""
from __future__ import annotations

from dataclasses import dataclass

from .gate import InvariantGate
from .ledger import JsonlLedger
from .models import Episode, Target, Verdict
from .ports import Mutator, Proposer, Sensor


@dataclass
class AdapterSet:
    sensor: Sensor
    proposer: Proposer
    mutator: Mutator
    gate: InvariantGate
    inputs: object                       # held-out input generator (domain-supplied)


class Orchestrator:
    def __init__(self, adapters: AdapterSet, ledger: JsonlLedger, max_rounds: int = 8) -> None:
        self._a = adapters
        self._ledger = ledger
        self._max_rounds = max_rounds

    def run(self, target: Target, *, apply: bool) -> list[Verdict]:
        verdicts: list[Verdict] = []
        current = target
        no_accept = 0
        tried_here: set[str] = set()          # in-run dedup — one transform per hotspot

        for _ in range(self._max_rounds):
            # 1. EVIDENCE (profile feeds reasoning)
            ev = self._a.sensor.collect(current)
            # 2. priors
            priors = self._ledger.recall(ev)
            # 3. PROPOSAL (untrusted, one transform)
            cand = self._a.proposer.propose(ev, priors)
            if cand is None:
                break
            tname = getattr(cand.transform, "name", "?")
            if tname in tried_here:           # re-profiling surfaced the same thing → stop
                break
            tried_here.add(tname)

            # 4. contract precondition (legality before the fact)
            if not _precondition_holds(cand, ev):
                v = Verdict(False, cand, None, None, reason="precondition_failed")
                self._ledger.record(Episode(ev, cand, v))
                verdicts.append(v)
                break

            # 5. mutate
            var = self._a.mutator.apply(current, cand.transform)
            # 6. VERIFICATION — the trusted gate
            v = self._a.gate.decide(current, var, cand, self._a.inputs)
            # 7. LEARNING (accept OR reject)
            self._ledger.record(Episode(ev, cand, v))
            verdicts.append(v)

            if v.accepted:
                no_accept = 0
                if apply:
                    _write_patch(var)
                    current = var.target      # 8. re-profile the new target
            else:
                no_accept += 1
                if no_accept >= 2:
                    break
        return verdicts


def _precondition_holds(candidate, evidence) -> bool:
    """Check the contract precondition on the AST/CFG facts.

    TODO(v0): real predicate checking against evidence.facts. For the skeleton,
    a transform may expose `check_precondition(evidence) -> bool`.
    """
    check = getattr(candidate.transform, "check_precondition", None)
    return bool(check(evidence)) if callable(check) else True


def _write_patch(variant) -> None:
    """Apply the accepted diff to the source file. TODO(v0): real patch write."""
    # For the skeleton we do not touch source; a real Mutator writes here.
    return None
