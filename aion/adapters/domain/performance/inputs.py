"""Held-out inputs for the correctness gate.

Mirrors AION_Architecture §16 / WEDGE_TEST §3. Includes the boundary/edge cases
that catch subtle bugs: empty, size 1, and larger sizes. (For the flagship
`f(std::size_t)` signature these are `n` values; richer generators come later.)
"""
from __future__ import annotations

from ....engine.config import Config


class HeldOutInputs:
    def __init__(self, config: Config) -> None:
        self._config = config
        self.seed = config.seed

    def values(self) -> list[int]:
        # edge cases first, then a few sizes big enough to exercise reallocation.
        return [0, 1, 2, 3, 5, 8, 16, 64, 1000, 65_536]

    def as_stdin(self) -> str:
        return "\n".join(str(v) for v in self.values()) + "\n"
