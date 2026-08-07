"""LLM cost cap (Phase-3 #12). TRUSTED.

The budget is to COST what the gate is to CORRECTNESS: a trusted meter the untrusted
proposer cannot exceed. Two ceilings — a per-RUN total and a per-HOTSPOT sub-limit — each a
spec in **tokens** (`500k` / `1M` / `500000`), **money** (`$2.50`), or **time** (`90s` /
`2min` / `1h`). Before each LLM call the proposer asks `can_spend()`; after it, `charge()`.
When exhausted the proposer stops proposing (graceful skip), never a crash.

Inert offline: the rule proposer spends nothing, so the budget never bites until the LLM
(#10) lands. Thread-safe for `--jobs` / the daemon.
"""
from __future__ import annotations

import threading
import time


def parse_spec(spec: str | None) -> tuple[int | None, float | None, float | None]:
    """`spec` -> (max_tokens, max_usd, max_seconds), exactly one set. Tokens is the default
    unit; `$` = money; `s`/`min`/`h` = time. Returns all-None for an empty/blank spec."""
    if not spec:
        return (None, None, None)
    s = str(spec).strip().lower()
    if s.startswith("$"):
        return (None, float(s[1:]), None)
    for suf, mul in (("min", 60.0), ("h", 3600.0), ("s", 1.0)):
        if s.endswith(suf):
            try:
                return (None, None, float(s[: -len(suf)]) * mul)
            except ValueError:
                break
    mult = 1
    if s.endswith("k"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    return (int(float(s) * mult), None, None)


class _Meter:
    """One ceiling across three dimensions; `exhausted()` is true if ANY set limit is hit."""

    def __init__(self, max_tok: int | None, max_usd: float | None, max_sec: float | None):
        self.max_tok, self.max_usd, self.max_sec = max_tok, max_usd, max_sec
        self.tok = 0
        self.usd = 0.0
        self._start = time.monotonic()

    def charge(self, tokens: int, usd: float) -> None:
        self.tok += tokens
        self.usd += usd

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def exhausted(self) -> bool:
        return ((self.max_tok is not None and self.tok >= self.max_tok)
                or (self.max_usd is not None and self.usd >= self.max_usd)
                or (self.max_sec is not None and self.elapsed() >= self.max_sec))


class Budget:
    def __init__(self, run_spec: str | None = None, hotspot_spec: str | None = None,
                 price_in: float = 0.0, price_out: float = 0.0):
        self._lock = threading.Lock()
        self._run = _Meter(*parse_spec(run_spec))          # always present (unlimited = pure tracker)
        self._hotspot_spec = parse_spec(hotspot_spec) if hotspot_spec else None
        self._hot: _Meter | None = None
        self._price_in, self._price_out = price_in, price_out
        self.calls = 0

    def start_hotspot(self) -> None:
        """Reset the per-hotspot sub-limit — call once before proposing for a new function."""
        with self._lock:
            self._hot = _Meter(*self._hotspot_spec) if self._hotspot_spec else None

    def can_spend(self) -> bool:
        """Is there budget left for another LLM call (run total AND current hotspot)?"""
        with self._lock:
            if self._run.exhausted():
                return False
            return not (self._hot is not None and self._hot.exhausted())

    def charge(self, in_tokens: int, out_tokens: int) -> None:
        """Debit the actual usage of one completed LLM call from both meters."""
        usd = in_tokens / 1e6 * self._price_in + out_tokens / 1e6 * self._price_out
        with self._lock:
            self.calls += 1
            self._run.charge(in_tokens + out_tokens, usd)
            if self._hot is not None:
                self._hot.charge(in_tokens + out_tokens, usd)

    def spent(self) -> dict:
        with self._lock:
            return {"calls": self.calls, "tokens": self._run.tok, "usd": round(self._run.usd, 4)}
