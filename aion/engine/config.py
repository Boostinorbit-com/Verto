"""Configuration & policy — loaded from .aion.toml, applied across all surfaces.

Mirrors AION_Architecture §8 (Config). Holds the gate policy the Invariant
Gate enforces: min_rung, objectives, allow_regression, enabled transforms.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:                                     # system Python is 3.8 (see §16.6) — soft fallback
    tomllib = None  # type: ignore


@dataclass
class Config:
    # gate policy
    min_rung: int = 3                     # auto-apply only at correctness Rung >= 3 (UBSan)
    objectives: tuple[str, ...] = ("p50", "p99", "peak_memory", "binary_size")
    # small default budgets so trivial size/mem noise doesn't fail Pareto (§9.3)
    allow_regression: dict[str, float] = field(
        default_factory=lambda: {"binary_size": 0.10, "peak_memory": 0.05})
    min_speedup_pct: float = 2.0          # reject gains below this (kills noise)
    reps: int = 12                        # benchmark repetitions (deltas are large; 12 is plenty)
    # proposal
    model: str = "frontier"               # frontier | local | rules(--offline)
    candidates: int = 1
    transforms: tuple[str, ...] = ("*",)  # glob(s) of enabled transforms
    # runtime
    sandbox: bool = True
    timeout_sec: int = 30
    fuzz_inputs: int = 1000
    seed: int = 0

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        cfg = cls()
        p = Path(path) if path else Path(".aion.toml")
        if p.exists() and tomllib is not None:
            with p.open("rb") as f:
                data = tomllib.load(f)
            for k, v in data.get("aion", {}).items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        return cfg
