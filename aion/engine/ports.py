"""The six ports — the complete contract between the engine and every adapter.

Mirrors AION_Architecture §6. Structural typing (Protocol): an adapter just
needs matching methods. The engine imports ONLY this module + models.py —
never a concrete adapter.
"""
from __future__ import annotations

from typing import Protocol

from .models import (
    Candidate,
    CorrectnessVerdict,
    Episode,
    Evidence,
    PerfVerdict,
    Priors,
    Target,
    Variant,
)


class Sensor(Protocol):                       # language + domain
    def collect(self, target: Target) -> Evidence: ...


class Proposer(Protocol):                     # model — UNTRUSTED
    def propose(self, ev: Evidence, priors: Priors) -> Candidate | None: ...


class Mutator(Protocol):                      # language
    def apply(self, target: Target, transform: object) -> Variant: ...


class CorrectnessOracle(Protocol):            # domain — TRUSTED
    def equivalent(self, orig: Target, var: Variant, inputs: object) -> CorrectnessVerdict: ...


class PerformanceOracle(Protocol):            # domain × language — TRUSTED
    def compare(self, orig: Target, var: Variant) -> PerfVerdict: ...


class Ledger(Protocol):                       # engine-provided
    def record(self, ep: Episode) -> None: ...
    def recall(self, ev: Evidence) -> Priors: ...
