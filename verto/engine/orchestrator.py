"""Orchestrator — drives the four-stage loop. Language/domain-agnostic.

Mirrors VERTO_Architecture §9 (control flow). Owns iteration, transform ordering,
and stop conditions. Talks only to ports + the gate.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .gate import InvariantGate
from .ledger import JsonlLedger
from .models import Episode, Target, Verdict
from .ports import Mutator, Proposer, Sensor

_SOUND_RUNG = 3            # sanitizer-clean; below this a change is not auto-written


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
        self.last_skips: list = []           # sites seen but not optimized (item #4)

    def run(self, target: Target, *, apply: bool,
            backup: bool = False, force: bool = False, txn=None) -> list[Verdict]:
        verdicts: list[Verdict] = []
        self.last_skips = []                  # sites seen but not optimized (item #4)
        current = target
        no_accept = 0
        tried_here: set[str] = set()          # in-run dedup — one transform per hotspot

        for round_i in range(self._max_rounds):
            # 1. EVIDENCE (profile feeds reasoning)
            ev = self._a.sensor.collect(current)
            if round_i == 0:                  # skips describe the ORIGINAL source
                self.last_skips = list(getattr(ev, "skips", []))
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
            v.diff = var.patch                # the real unified diff (preview + apply)
            # 7. LEARNING (accept OR reject)
            self._ledger.record(Episode(ev, cand, v))
            verdicts.append(v)

            if v.accepted:
                no_accept = 0
                # write only a SOUND change (sanitizer-clean) unless --force overrides;
                # this refuses to auto-apply a --fast (unverified-safe) result.
                sound = bool(v.correctness and v.correctness.rung >= _SOUND_RUNG)
                if apply and (sound or force):
                    # item #9: write through the transaction — atomic, snapshotted for
                    # rollback, and refused if the file drifted from what was verified
                    # (ev.source is exactly the text the gate compiled and ran).
                    if txn is not None:
                        txn.write(current.file, var.source_after, expected_before=ev.source)
                    else:
                        _write_patch(var, backup=backup)
                    v.applied = True
                    current = var.target      # 8. re-profile the mutated source
            else:
                no_accept += 1
                if no_accept >= 2:
                    break

            # Re-profiling only surfaces something new after the source changes.
            # With apply=False the file is untouched, so a second round just
            # re-parses and re-proposes the same transform — skip it.
            if not apply:
                break
        return verdicts


def _precondition_holds(candidate, evidence) -> bool:
    """Check the contract precondition on the AST/CFG facts.

    TODO(v0): real predicate checking against evidence.facts. For the skeleton,
    a transform may expose `check_precondition(evidence) -> bool`.
    """
    check = getattr(candidate.transform, "check_precondition", None)
    return bool(check(evidence)) if callable(check) else True


def _write_patch(variant, *, backup: bool = False) -> None:
    """Apply the VERIFIED change: write the variant's source to its file (optionally
    saving a .bak first). The variant already passed the trusted gate, so this is a
    plain, deterministic file write."""
    path = Path(variant.target.file)
    if backup:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(variant.source_after, encoding="utf-8")
