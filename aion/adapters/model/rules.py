"""Rule proposer — deterministic, no LLM (the --offline path).

Mirrors AION_Architecture §12 (ModelProvider) and the `--offline` flag. Offers
the first registered transform whose structural pattern matches and hasn't
already been applied. Good for CI and for patterns that don't need an LLM.
"""
from __future__ import annotations

from ...engine.config import Config
from ...engine.models import Candidate, Evidence, Priors
from ..transforms import ALL


class RuleProposer:
    def __init__(self, config: Config) -> None:
        self._config = config

    def propose(self, ev: Evidence, priors: Priors) -> Candidate | None:
        for t in ALL:
            if t.name in priors.accepted_transforms:
                continue
            if t.matches(ev.source):
                return Candidate(
                    transform=t,
                    contract=t.contract(),
                    rationale=getattr(t, "rationale", t.name),
                )
        return None
