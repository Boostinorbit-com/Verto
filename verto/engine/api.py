"""The Engine API — the single contract every surface calls.

Mirrors VERTO_Architecture §5. analyze / optimize / report. Returns structured
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

    def analyze(self, file: str, *, build: dict | None = None) -> list[Verdict]:
        """Non-destructive: run the loop, write nothing, don't pollute the Ledger."""
        return self._run(file, apply=False, persist=False, build=build)

    def optimize(self, file: str, *, apply: bool, build: dict | None = None) -> list[Verdict]:
        return self._run(file, apply=apply, persist=apply, build=build)

    def optimize_codebase(self, cc_path: str, *, apply: bool = False
                          ) -> list[tuple[str, list[Verdict], str | None]]:
        """Codebase mode: iterate every C++ translation unit in a
        compile_commands.json, in ONE process (startup + libclang amortized),
        parsing/compiling each with its real flags. Returns (file, verdicts, error)
        per TU; a TU that blows up is recorded (error set), never aborts the run."""
        from ..adapters.language.cpp import compile_db
        tus = compile_db.load(cc_path)
        ledger = self.ledger if apply else JsonlLedger(os.devnull)
        results: list[tuple[str, list[Verdict], str | None]] = []
        for tu in tus:
            lang = registry.language_of(tu.file)
            if lang != "cpp":
                continue
            try:
                adapters = registry.resolve(tu.file, self.config)
                target = Target(file=tu.file, symbol=Path(tu.file).stem, line=0,
                                language=lang,
                                build={"parse_flags": tu.flags, "compile_flags": tu.flags})
                verdicts = Orchestrator(adapters, ledger).run(target, apply=apply)
                results.append((tu.file, verdicts, None))
            except Exception as e:                       # one bad TU must not sink the batch
                results.append((tu.file, [], f"{type(e).__name__}: {e}"))
        return results

    def report(self) -> dict:
        priors = self.ledger.recall(_dummy_evidence())
        return {
            "accepted": len(priors.accepted_transforms),
            "rejected": len(priors.rejected_transforms),
            "accepted_transforms": priors.accepted_transforms,
        }

    # --- internal ---
    def _run(self, file: str, *, apply: bool, persist: bool,
             build: dict | None = None) -> list[Verdict]:
        adapters = registry.resolve(file, self.config)
        target = Target(file=file, symbol=Path(file).stem, line=0,
                        language=registry.language_of(file), build=build or {})
        ledger = self.ledger if persist else JsonlLedger(os.devnull)
        return Orchestrator(adapters, ledger).run(target, apply=apply)


def _dummy_evidence() -> Evidence:
    return Evidence(target=Target(file="_", symbol="_", line=0, language="cpp"), source="")
