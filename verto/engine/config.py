"""Configuration & policy — loaded from .verto.toml, applied across all surfaces.

Mirrors VERTO_Architecture §8 (Config). Holds the gate policy the Invariant
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
    # Regression budgets (§9.3). peak_memory=0.12: a data-structure swap that trades
    # a little memory for a large speedup (map→unordered_map, ~7% RSS on a tiny
    # baseline) is a core Category-A win and must clear the budget, while an
    # egregious resident table (memoization, ~16%+) still fails it. 5% was too tight
    # to distinguish the two — it cut through the swap's measurement band.
    allow_regression: dict[str, float] = field(
        default_factory=lambda: {"binary_size": 0.10, "peak_memory": 0.12})
    min_speedup_pct: float = 2.0          # reject gains below this (kills noise)
    reps: int = 12                        # benchmark repetitions (upper bound when adaptive)
    reps_min: int = 5                     # adaptive floor — escalate to `reps` only if borderline
    adaptive: bool = True                 # stop early when the gain is unambiguous vs threshold
    fast: bool = False                    # --fast: skip Rung-3 sanitizer (UNSOUND — opt-in only)
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
        p = Path(path) if path else Path(".verto.toml")
        if p.exists() and tomllib is not None:
            with p.open("rb") as f:
                data = tomllib.load(f)
            for k, v in data.get("verto", {}).items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        return cfg
