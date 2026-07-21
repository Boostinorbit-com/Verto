"""Benchmark runner — statistically honest timing.

Mirrors AION_Architecture §8/§16.5. Pins to a core (taskset when available),
runs the timing binary (which prints per-rep elapsed ms), computes median + p99,
and reads binary size. The measurement *protocol* is the C++ default; other
languages override (Java JIT warmup, etc. — see AION_Architecture §3).
"""
from __future__ import annotations

import os
import shutil
import statistics
from dataclasses import dataclass, field

from . import sandbox


@dataclass
class Samples:
    p50: float
    p99: float
    peak_memory: float = 0.0
    binary_size: float = 0.0
    raw: list[float] = field(default_factory=list)


def summarize(times_ms: list[float], *, binary_size: float = 0.0) -> Samples:
    s = sorted(times_ms)
    if not s:
        return Samples(0.0, 0.0, binary_size=binary_size)
    p50 = statistics.median(s)
    p99 = s[max(0, int(len(s) * 0.99) - 1)]
    return Samples(p50=p50, p99=p99, binary_size=binary_size, raw=times_ms)


def measure(binary: str, *, n: int = 2_000_000, reps: int = 30, pin_core: int = 2) -> Samples:
    cmd = [binary, str(n), str(reps)]
    if shutil.which("taskset"):
        cmd = ["taskset", "-c", str(pin_core), *cmd]
    res = sandbox.run(cmd, timeout_sec=180)
    times = [float(x) for x in res.stdout.split() if x.strip()]
    size_mb = os.path.getsize(binary) / 1e6 if os.path.exists(binary) else 0.0
    return summarize(times, binary_size=size_mb)
