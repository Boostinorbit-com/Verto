"""Baselines — the persisted **regression floor**.

The ledger answers *"what did BOOSTOPT try, and what did it decide?"* — one row per
episode, never compared across runs. That leaves one question it structurally cannot
answer: **did code we already optimized get slow again?**

A baseline is the best result BOOSTOPT has ever proven *and written* for a symbol.
Once `--apply` puts a win into the source, the achieved number becomes a floor. If a
later run measures that same symbol slower than its floor, the optimization was
undone — someone edited the hot path, a refactor reverted it, a merge dropped it.
That is a regression the gate would otherwise never mention, because on its own terms
each run is a fresh, correct verdict.

Storage mirrors the ledger's spirit — plain, inspectable, per-project — but is a map
rather than a log: one JSON file per language under `.boostopt/baselines/`, keyed
`file::symbol`. A map, because a floor is a *current best*, not a history; the history
is what the ledger is for.

Floors only ever improve (`record` keeps the faster of old and new), so the file can
never drift upward and quietly stop catching regressions.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# A measurement must beat the floor by more than this to count as a regression.
# Same 2% reasoning as `--min-speedup`: below it, real machines can't tell a change
# from noise, and a floor that fires on noise is a floor nobody trusts.
NOISE_FLOOR = 0.02


def _key(file: str, symbol: str) -> str:
    return f"{file}::{symbol}"


class Baselines:
    """The regression floor for one workspace. `path=None` disables it entirely
    (no `boostopt init` → no persistence), exactly like the rewrite cache."""

    def __init__(self, path: str | Path | None) -> None:
        self.dir = Path(path) if path else None
        self._lock = threading.Lock()      # codebase mode writes from parallel workers

    # --- storage -----------------------------------------------------------
    def _file(self, language: str) -> Path | None:
        if self.dir is None:
            return None
        return self.dir / f"{language or 'unknown'}.json"

    def _load(self, language: str) -> dict[str, Any]:
        p = self._file(language)
        if p is None or not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}                      # a corrupt floor must never break a run

    def _save(self, language: str, data: dict[str, Any]) -> None:
        p = self._file(language)
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # --- reads -------------------------------------------------------------
    def lookup(self, target) -> dict[str, Any] | None:
        """The floor for this symbol, or None."""
        if self.dir is None:
            return None
        return self._load(getattr(target, "language", "")).get(
            _key(getattr(target, "file", ""), getattr(target, "symbol", "")))

    def all(self, language: str = "cpp") -> dict[str, Any]:
        """Every floor for a language — what `boostopt report` would show."""
        return self._load(language)

    # --- the check ---------------------------------------------------------
    def check(self, target, vector: dict[str, float] | None) -> str:
        """Is the code slower than a floor we previously wrote? Returns a human note, or "".

        Compares `p50_before` — the CURRENT original's measurement, taken by the gate
        this run — against the stored floor. Only entries with `applied` set are
        considered: if a win was never written to source, the original being slower
        than it is simply the win still being available, not a regression.
        """
        entry = self.lookup(target)
        if not entry or not entry.get("applied") or not vector:
            return ""
        floor = entry.get("p50")
        now = vector.get("p50_before")
        if not isinstance(floor, (int, float)) or not isinstance(now, (int, float)):
            return ""
        if floor <= 0 or now <= floor * (1 + NOISE_FLOOR):
            return ""
        slower = (now - floor) / floor * 100.0
        when = str(entry.get("recorded", ""))[:10]
        return (f"regressed vs baseline: proven at {floor:.6g} ms"
                f"{f' on {when}' if when else ''}, now {now:.6g} ms ({slower:.1f}% slower)")

    # --- the write ---------------------------------------------------------
    def record(self, target, verdict, *, applied: bool) -> bool:
        """Store the accepted measurement as this symbol's floor. Monotonic — keeps
        whichever p50 is faster. Returns True if the file changed.

        `applied` is threaded in rather than read off the verdict because the
        orchestrator sets `verdict.applied` only after the transaction writes, and a
        floor that records un-applied runs would fire a false regression on the very
        next dry run."""
        if self.dir is None or not getattr(verdict, "accepted", False):
            return False
        perf = getattr(verdict, "performance", None)
        vec = dict(getattr(perf, "vector", {}) or {})
        p50 = vec.get("p50")
        if not isinstance(p50, (int, float)) or p50 <= 0:
            return False

        language = getattr(target, "language", "") or "unknown"
        k = _key(getattr(target, "file", ""), getattr(target, "symbol", ""))
        cand = getattr(verdict, "candidate", None)
        transform = getattr(getattr(cand, "transform", None), "name", "") if cand else ""
        corr = getattr(verdict, "correctness", None)

        with self._lock:
            data = self._load(language)
            prev = data.get(k)
            # An un-applied accept still teaches us the number, but must not arm the
            # check — so it may set the floor, and only a real write sets `applied`.
            was_applied = bool(prev and prev.get("applied"))
            if prev and isinstance(prev.get("p50"), (int, float)) and prev["p50"] <= p50:
                if applied and not was_applied:
                    prev["applied"] = True   # same floor, now actually in the source
                    self._save(language, data)
                    return True
                return False
            data[k] = {
                "file": getattr(target, "file", ""),
                "symbol": getattr(target, "symbol", ""),
                "language": language,
                "transform": transform,
                "rung": getattr(corr, "rung", None),
                "p50": float(p50),
                "origin_p50": vec.get("p50_before"),
                "applied": bool(applied) or was_applied,
                "recorded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._save(language, data)
            return True
