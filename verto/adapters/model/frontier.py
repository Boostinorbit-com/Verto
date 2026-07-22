"""Frontier LLM proposer (v0 default) — the Proposer backend.

Mirrors VERTO_Architecture §12 "Proposer / model requirements". UNTRUSTED: the
gate re-verifies everything, so the model is a quality knob, not a correctness
dependency. Feeds *source + compact facts* (not a raw AST dump) to a frontier
code model and parses a Transform + Contract from a structured reply.
"""
from __future__ import annotations

from ...engine.config import Config
from ...engine.models import Candidate, Evidence, Priors


class FrontierProposer:
    def __init__(self, config: Config) -> None:
        self._config = config

    def propose(self, ev: Evidence, priors: Priors) -> Candidate | None:
        raise NotImplementedError(
            "FrontierProposer needs an LLM client + API key. "
            "Use --offline for the deterministic rule proposer, or wire a model here."
        )

    # --- to implement in v0 step 6 ---
    def _render_context(self, ev: Evidence) -> str:
        """source + compact facts (NOT a raw AST/IR dump)."""
        ...

    def _parse_candidate(self, reply: str) -> Candidate | None:
        """LLM reply -> Transform + Contract (JSON / tool-call)."""
        ...
