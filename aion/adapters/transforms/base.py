"""Transform + Contract base — a transform detects its own site and rewrites source.

Mirrors AION.md §9.1 (contracts) and AION_Architecture §16.2. Each transform is
self-contained: `matches` (structural pattern present?), `rewrite` (source->source),
and `contract` (legality precondition + equivalence postcondition). The Mutator is
generic — it just calls `rewrite`.

Note: for v0 the *deeper* preconditions (e.g. "map iteration order not observed")
are enforced by the trusted gate's differential test, not statically — a change
that violates them changes observable output and is REJECTED. That is the contract
enforced by measurement.
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod

from ...engine.models import Contract, Evidence


class Transform(ABC):
    name: str = "transform"
    target_func: str | None = None      # scope edits to this function (profile-selected site)

    def bind(self, func: str | None) -> "Transform":
        """Return a copy of this transform scoped to a specific function."""
        c = copy.copy(self)
        c.target_func = func
        return c

    @abstractmethod
    def contract(self) -> Contract: ...

    @abstractmethod
    def matches(self, source: str) -> bool:
        """Is this transform's structural pattern present in the source?"""

    @abstractmethod
    def rewrite(self, source: str) -> tuple[str, str] | None:
        """Return (new_source, patch) — or None if the site can't be rewritten."""

    def check_precondition(self, evidence: Evidence) -> bool:
        """Structural legality check the orchestrator runs before applying."""
        return self.matches(evidence.source)
