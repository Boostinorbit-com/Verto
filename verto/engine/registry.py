"""Registry — maps a Target to a (Language x Domain x Model) adapter set.

Mirrors VERTO_Architecture §8 (Registry). This is where multi-language support
is wired: file extension -> Language adapter. Engine core stays untouched when
a new language is added; you register it here.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .gate import InvariantGate
from .orchestrator import AdapterSet

_EXT_LANGUAGE = {
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".h": "cpp",
    # ".py": "python",  # future — a new LanguageAdapter, engine unchanged
}


def language_of(file: str) -> str:
    lang = _EXT_LANGUAGE.get(Path(file).suffix.lower())
    if lang is None:
        raise ValueError(f"no language adapter registered for {Path(file).suffix!r}")
    return lang


def resolve(file: str, config: Config) -> AdapterSet:
    """Build the adapter set for a file. v0: C++ x Performance x (rules|frontier)."""
    lang = language_of(file)
    if lang != "cpp":
        raise NotImplementedError(f"language {lang!r} not yet implemented (Axis A)")

    # --- language: C++ ---
    from ..adapters.language.cpp.sensor import CppSensor
    from ..adapters.language.cpp.mutator import CppMutator

    # --- domain: Performance ---
    from ..adapters.domain.performance.correctness import PerfCorrectnessOracle
    from ..adapters.domain.performance.performance import PerformanceOracleImpl
    from ..adapters.domain.performance.inputs import HeldOutInputs

    # --- model ---
    if config.model in ("rules", "offline"):
        from ..adapters.model.rules import RuleProposer as ProposerCls
    else:
        from ..adapters.model.frontier import FrontierProposer as ProposerCls

    from ..adapters.domain.performance.reuse import TestReuseOracle
    gate = InvariantGate(PerfCorrectnessOracle(config), PerformanceOracleImpl(config), config,
                         reuse=TestReuseOracle(config))
    return AdapterSet(
        sensor=CppSensor(config),
        proposer=ProposerCls(config),
        mutator=CppMutator(config),
        gate=gate,
        inputs=HeldOutInputs(config),
    )
