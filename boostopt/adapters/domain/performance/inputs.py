"""Held-out inputs for the correctness gate (Phase-1 item #7).

The differential test is only as strong as the inputs it runs. We keep the hand-
picked boundary/edge cases (empty, 1, 2, 3 — where off-by-one and empty-container
bugs live) and ADD `config.fuzz_inputs` seeded-random sizes, so the gate checks
far more than ten points. The PRNG is seeded from `config.seed`, so the input set
is DETERMINISTIC — same seed → same inputs → a reproducible verdict and a stable
learning log (Goodhart-resistant, not a moving target run to run).

Sizes are bounded: mostly small (dense coverage where subtle bugs hide) with some
medium ones (exercise reallocation) — the fixed edges already include the large
65536 case, so fuzzing adds diversity without blowing up the diff-test's runtime.
"""
from __future__ import annotations

import random

from ....engine.config import Config

_EDGES = [0, 1, 2, 3, 5, 8, 16, 64, 1000, 65_536]


class HeldOutInputs:
    def __init__(self, config: Config) -> None:
        self._config = config
        self.seed = int(getattr(config, "seed", 0) or 0)
        self._fuzz = max(0, int(getattr(config, "fuzz_inputs", 0) or 0))

    def values(self) -> list[int]:
        vals = list(_EDGES)
        if self._fuzz:
            rng = random.Random(self.seed)          # deterministic → reproducible verdict
            for _ in range(self._fuzz):
                if rng.random() < 0.85:
                    vals.append(rng.randint(0, 300))      # dense small — edge/off-by-one territory
                else:
                    vals.append(rng.randint(301, 8_192))  # medium — reallocation, bounded cost
        return vals

    def as_stdin(self) -> str:
        return "\n".join(str(v) for v in self.values()) + "\n"
