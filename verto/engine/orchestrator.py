"""Orchestrator — drives the four-stage loop. Language/domain-agnostic.

Mirrors VERTO_Architecture §9 (control flow). Owns iteration, transform ordering,
and stop conditions. Talks only to ports + the gate.
"""
from __future__ import annotations

import difflib
import os
from dataclasses import dataclass

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
    budget: object | None = None         # #12: LLM cost meter (offline: inert)


class Orchestrator:
    def __init__(self, adapters: AdapterSet, ledger: JsonlLedger, max_rounds: int = 8,
                 config=None) -> None:
        self._a = adapters
        self._ledger = ledger
        self._max_rounds = max_rounds
        self._config = config
        self.last_skips: list = []           # sites seen but not optimized (item #4)

    def _n_candidates(self) -> int:
        # #11: only the LLM benefits from N draws (rules are deterministic → 1).
        if getattr(self._config, "model", "") in ("local", "frontier"):
            return max(1, int(getattr(self._config, "candidates", 1) or 1))
        return 1

    def _best_of_n(self, ev, priors, current, n: int, tried_here: set):
        """#11: draw up to `n` candidates for this hotspot, gate each, and return
        ((best_verdict, best_variant) | None, all_attempt_verdicts). "Best" = the accepted
        rewrite with the largest p50 speedup. Deterministic proposers (rules) stop after one
        draw; identical variants are deduped so we never re-verify the same rewrite."""
        if self._a.budget is not None:
            self._a.budget.start_hotspot()    # #12: one per-hotspot budget across all n draws
        best = None
        best_delta = float("-inf")
        attempts: list[Verdict] = []
        seen: set[str] = set()
        for _ in range(max(1, n)):
            cand = self._a.proposer.propose(ev, priors)
            if cand is None:
                break
            tname = getattr(cand.transform, "name", "?")
            varies = (tname == "llm_rewrite")   # LLM draws differ; rule transforms repeat
            if not varies:
                if tname in tried_here:         # a rule transform already tried this run
                    break
                tried_here.add(tname)
            if not _precondition_holds(cand, ev):
                v = Verdict(False, cand, None, None, reason="precondition_failed")
                self._ledger.record(Episode(ev, cand, v))
                attempts.append(v)
                if not varies:
                    break
                continue
            try:
                var = self._a.mutator.apply(current, cand.transform)
            except ValueError:
                # Untrusted proposer: a candidate that can't be applied — an LLM rewrite
                # that changed nothing or couldn't be located, a transform whose
                # precondition slipped — is a REJECTED proposal, never a crash. Record it
                # and move on (LLM: try the next draw; rules: stop).
                v = Verdict(False, cand, None, None, reason="mutation_failed")
                self._ledger.record(Episode(ev, cand, v))
                attempts.append(v)
                if not varies:
                    break
                continue
            if var.source_after in seen:        # identical rewrite → don't re-verify it
                if not varies:
                    break
                continue
            seen.add(var.source_after)
            v = self._a.gate.decide(current, var, cand, self._a.inputs)
            v.diff = var.patch
            v.udiff = _unified_diff(current.file, ev.source, var.source_after)
            self._ledger.record(Episode(ev, cand, v))
            attempts.append(v)
            if v.accepted:
                delta = v.performance.vector.get("p50_delta_pct", 0.0) if v.performance else 0.0
                if delta > best_delta:
                    best_delta, best = delta, (v, var)
            if not varies:                      # rules: one draw is enough
                break
        return best, attempts

    def run(self, target: Target, *, apply: bool,
            backup: bool = False, force: bool = False, txn=None) -> list[Verdict]:
        verdicts: list[Verdict] = []
        self.last_skips = []                  # sites seen but not optimized (item #4)
        current = target
        no_accept = 0
        tried_here: set[str] = set()          # in-run dedup — one transform per hotspot
        n = self._n_candidates()

        for round_i in range(self._max_rounds):
            # 1. EVIDENCE (profile feeds reasoning)
            ev = self._a.sensor.collect(current)
            if round_i == 0:                  # skips describe the ORIGINAL source
                self.last_skips = list(getattr(ev, "skips", []))
            # 2. priors
            priors = self._ledger.recall(ev)
            # 3-6. PROPOSAL + VERIFICATION — best-of-n (untrusted proposer, trusted gate)
            best, attempts = self._best_of_n(ev, priors, current, n, tried_here)
            if not attempts:                  # proposer offered nothing
                break
            if best is not None:
                v, var = best                 # the accepted winner (largest speedup)
            else:
                v, var = attempts[-1], None   # none accepted → report the last attempt
            verdicts.append(v)

            if best is not None:
                no_accept = 0
                # write only a SOUND change (sanitizer-clean) unless --force overrides;
                # this refuses to auto-apply a --fast (unverified-safe) result. A 2A
                # test-verified change (via='tests') is sound on the project's OWN
                # acceptance criteria, so it's applyable without the sanitizer rung.
                sound = bool(v.correctness and v.correctness.rung >= _SOUND_RUNG) \
                    or (getattr(v, "via", "harness") == "tests" and v.tests_confirmed)
                if apply and (sound or force) and txn is not None:
                    # item #9: write through the transaction — atomic, snapshotted for
                    # rollback, and refused if the file drifted from what was verified
                    # (ev.source is exactly the text the gate compiled and ran).
                    txn.write(current.file, var.source_after, expected_before=ev.source)
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


def _unified_diff(path: str, before: str, after: str) -> str:
    """A standard `git apply -p1` / `patch -p1`-able unified diff between the source the
    gate verified (before) and the change it accepted (after). Incremental per accepted
    change, so a codebase run yields a reviewable patch SERIES (2C)."""
    if before == after:
        return ""
    rel = os.path.relpath(path)
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}"))


def _precondition_holds(candidate, evidence) -> bool:
    """Check the contract precondition on the AST/CFG facts.

    TODO(v0): real predicate checking against evidence.facts. For the skeleton,
    a transform may expose `check_precondition(evidence) -> bool`.
    """
    check = getattr(candidate.transform, "check_precondition", None)
    return bool(check(evidence)) if callable(check) else True
