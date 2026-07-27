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

    # #13: apply the sandbox policy (--no-sandbox / --sandbox-mem) before any binary runs.
    from ..runtime import sandbox
    sandbox.set_policy(enabled=getattr(config, "sandbox", True),
                       mem_mb=getattr(config, "sandbox_mem_mb", None))

    # --- language: C++ ---
    from ..adapters.language.cpp.sensor import CppSensor
    from ..adapters.language.cpp.mutator import CppMutator

    # --- domain: Performance ---
    from ..adapters.domain.performance.correctness import PerfCorrectnessOracle
    from ..adapters.domain.performance.performance import PerformanceOracleImpl
    from ..adapters.domain.performance.inputs import HeldOutInputs

    # --- model ---
    from ..adapters.proposer.rules import RuleProposer
    if config.model in ("rules", "offline"):
        ProposerCls = RuleProposer
    else:
        from ..adapters.proposer.frontier import FrontierProposer as ProposerCls

    # #12: the cost cap — a trusted meter the (untrusted) proposer can't exceed. Inert offline.
    from ..runtime.budget import Budget
    budget = Budget(getattr(config, "budget", None), getattr(config, "budget_per_hotspot", None),
                    getattr(config, "llm_price_input", 0.0), getattr(config, "llm_price_output", 0.0))

    from ..adapters.domain.performance.reuse import TestReuseOracle
    meta = None
    if getattr(config, "metamorphic", False):
        from ..adapters.domain.performance.metamorphic import MetamorphicOracle
        meta = MetamorphicOracle(config)
    gate = InvariantGate(PerfCorrectnessOracle(config), PerformanceOracleImpl(config), config,
                         reuse=TestReuseOracle(config), metamorphic=meta)
    # Under an LLM model, keep the deterministic rule proposer as a FLOOR: its guaranteed
    # win is gated alongside the LLM draws, so `--model local|frontier` is never WORSE than
    # `--model rules` (the gate keeps the fastest ACCEPTED candidate). Free — rules cost $0.
    floor = RuleProposer(config, budget=budget) if config.model not in ("rules", "offline") else None

    return AdapterSet(
        sensor=CppSensor(config),
        proposer=ProposerCls(config, budget=budget),
        mutator=CppMutator(config),
        gate=gate,
        inputs=HeldOutInputs(config),
        budget=budget,
        floor_proposer=floor,
    )
