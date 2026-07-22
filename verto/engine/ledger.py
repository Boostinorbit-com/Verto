"""Ledger — append-only record of every episode; serves priors.

Mirrors VERTO_Architecture §8. v0: JSONL on disk. Later: sync to the Network
service (Axis E). Every accept AND reject is recorded — both teach.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .models import Episode, Evidence, Priors


class JsonlLedger:
    def __init__(self, path: str | Path = "ledger.jsonl") -> None:
        self.path = Path(path)

    def record(self, ep: Episode) -> None:
        row = {
            "language": ep.evidence.target.language,
            "symbol": ep.evidence.target.symbol,
            "transform": _transform_name(ep.candidate),
            "accepted": ep.verdict.accepted,
            "reason": ep.verdict.reason,
            "rung": ep.verdict.correctness.rung if ep.verdict.correctness else None,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def recall(self, ev: Evidence) -> Priors:
        acc: list[str] = []
        rej: list[str] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                (acc if row.get("accepted") else rej).append(row.get("transform", ""))
        return Priors(accepted_transforms=acc, rejected_transforms=rej)


def _transform_name(candidate) -> str:
    if candidate is None:
        return ""
    t = candidate.transform
    return getattr(t, "name", type(t).__name__)
