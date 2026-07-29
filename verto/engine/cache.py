"""Best-so-far rewrite cache — VERTO's "high score" per function.

A re-run skips the slow proposer (above all the LLM) by remembering the best VERIFIED rewrite for
each function, keyed by (function source + model + min_rung) so a code edit OR a model change
invalidates it automatically. It is a FLOOR, never a ceiling: `--refine` re-runs the proposer and
keeps whichever result is faster, so the stored win only ever goes UP — you can always try to beat
your last answer, you just choose when to pay for it. Never a correctness risk: the entry was gated
when stored, `--apply` re-verifies before writing, and a code/model change misses the cache.
"""
from __future__ import annotations

import hashlib
import json
import os


class RewriteCache:
    def __init__(self, path: str | None) -> None:
        self._path = path
        self._mem: dict[str, dict] = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            e = json.loads(line)
                            self._mem[e["key"]] = e          # append-only; last write wins (refine)
                        except json.JSONDecodeError:
                            pass
            except OSError:
                pass

    @staticmethod
    def _key(func_src: str, model: str, min_rung: int) -> str:
        return hashlib.sha256(f"{model}|{min_rung}|{func_src}".encode()).hexdigest()[:20]

    def get(self, func_src: str, model: str, min_rung: int) -> dict | None:
        return self._mem.get(self._key(func_src, model, min_rung))

    def put(self, func_src: str, model: str, min_rung: int, entry: dict) -> None:
        """Store `entry` (carries new_code / delta_pct / rung / accepted). Keeps the BETTER of any
        existing entry and this one (larger p50 delta) — the high score only ever rises."""
        k = self._key(func_src, model, min_rung)
        prev = self._mem.get(k)
        if prev and prev.get("delta_pct", 0.0) >= entry.get("delta_pct", 0.0):
            return                                           # existing best already ≥ this one
        rec = {"key": k, "model": model, **entry}
        self._mem[k] = rec
        if self._path:
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
            except OSError:
                pass
