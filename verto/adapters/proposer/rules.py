"""Rule proposer — deterministic, no LLM (the --offline path).

Mirrors VERTO_Architecture §12 (ModelProvider) and the `--offline` flag. Offers
the first registered transform whose structural pattern matches and hasn't
already been applied. Good for CI and for patterns that don't need an LLM.
"""
from __future__ import annotations

import fnmatch

from ...engine.config import Config
from ...engine.models import Candidate, Evidence, Priors
from ..language.cpp.transforms import ALL


class RuleProposer:
    def __init__(self, config: Config, budget: object | None = None) -> None:
        self._config = config
        self._budget = budget            # rules are free — the cost cap (#12) is a no-op here

    def _enabled(self, name: str) -> bool:
        globs = getattr(self._config, "transforms", ("*",)) or ("*",)
        return any(fnmatch.fnmatch(name, g) for g in globs)   # --transforms filter

    def propose(self, ev: Evidence, priors: Priors) -> Candidate | None:
        func = ev.target.symbol          # the profile-selected hotspot (Sensor set this)
        for t in ALL:
            if not self._enabled(t.name):
                continue
            # NOTE: do NOT skip transforms in priors.accepted_transforms — that list is
            # global across files/runs, so it would suppress a transform everywhere once
            # accepted anywhere. Within-run dedup is `tried_here`; an already-applied
            # file simply won't match(). (Bug surfaced when --apply began persisting.)
            bound = t.bind(func)         # scope the edit to the chosen function
            if bound.matches(ev.source):
                return Candidate(
                    transform=bound,
                    contract=bound.contract(),
                    rationale=getattr(t, "rationale", t.name),
                )
        return None
