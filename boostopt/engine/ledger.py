"""Ledger — append-only record of every episode; serves priors.

Mirrors BOOSTOPT_Architecture §8. v0: JSONL on disk. Later: sync to the Network
service (Axis E). Every accept AND reject is recorded — both teach.
"""
from __future__ import annotations

import dataclasses
import json
import threading
from pathlib import Path

from .models import Episode, Evidence, Priors


class JsonlLedger:
    def __init__(self, path: str | Path = "ledger.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()      # codebase mode may write from parallel workers (item #8)

    def record(self, ep: Episode) -> None:
        w = getattr(ep.verdict.correctness, "witness", None)
        row = {
            "language": ep.evidence.target.language,
            "symbol": ep.evidence.target.symbol,
            "transform": _transform_name(ep.candidate),
            # NOTE: no "applied" field — the orchestrator sets verdict.applied AFTER this
            # record() call, so it would be False on every row. `accepted` is the gate's
            # answer; whether it was WRITTEN depends on --apply and is not known here.
            "accepted": ep.verdict.accepted,
            "reason": ep.verdict.reason,
            "rung": ep.verdict.correctness.rung if ep.verdict.correctness else None,
        }
        if w is not None and not w.build_ok and getattr(w, "build_error", ""):
            row["build_error"] = w.build_error     # WHY the compiler refused it — the useful part
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def recall(self, ev: Evidence) -> Priors:
        acc: list[str] = []
        rej: list[str] = []
        with self._lock:
            text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        for line in text.splitlines():
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
