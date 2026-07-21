"""The Engine API — the single contract every surface calls.

Mirrors AION_Architecture §5. analyze / optimize / report. Returns structured
data, never prints. The CLI/CI/IDE/SDK are thin clients over this.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import registry
from .config import Config
from .ledger import JsonlLedger
from .models import Evidence, Target, Verdict
from .orchestrator import Orchestrator


class Engine:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.ledger = JsonlLedger()

    def analyze(self, file: str) -> list[Verdict]:
        """Non-destructive: run the loop, write nothing, don't pollute the Ledger."""
        return self._run(file, apply=False, persist=False)

    def optimize(self, file: str, *, apply: bool) -> list[Verdict]:
        return self._run(file, apply=apply, persist=apply)

    def report(self) -> dict:
        priors = self.ledger.recall(_dummy_evidence())
        return {
            "accepted": len(priors.accepted_transforms),
            "rejected": len(priors.rejected_transforms),
            "accepted_transforms": priors.accepted_transforms,
        }

    # --- internal ---
    def _run(self, file: str, *, apply: bool, persist: bool) -> list[Verdict]:
        adapters = registry.resolve(file, self.config)
        target = Target(file=file, symbol=Path(file).stem, line=0,
                        language=registry.language_of(file))
        ledger = self.ledger if persist else JsonlLedger(os.devnull)
        return Orchestrator(adapters, ledger).run(target, apply=apply)


def _dummy_evidence() -> Evidence:
    return Evidence(target=Target(file="_", symbol="_", line=0, language="cpp"), source="")
