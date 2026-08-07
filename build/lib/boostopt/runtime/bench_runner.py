"""Benchmark runner — statistically honest timing.

Mirrors BOOSTOPT_Architecture §8/§16.5. Pins to a core (taskset when available),
runs the timing binary (which prints per-rep elapsed ms), computes median + p99,
and reads binary size. The measurement *protocol* is the C++ default; other
languages override (Java JIT warmup, etc. — see BOOSTOPT_Architecture §3).
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


def summarize(times_ms: list[float], *, binary_size: float = 0.0,
              peak_memory: float = 0.0) -> Samples:
    s = sorted(times_ms)
    if not s:
        return Samples(0.0, 0.0, binary_size=binary_size, peak_memory=peak_memory)
    p50 = statistics.median(s)
    p99 = s[max(0, int(len(s) * 0.99) - 1)]
    return Samples(p50=p50, p99=p99, binary_size=binary_size,
                   peak_memory=peak_memory, raw=times_ms)


def _peak_memory_mb(stderr: str) -> float:
    for line in stderr.splitlines():
        if line.startswith("MEM_KB"):
            try:
                return float(line.split()[1]) / 1024.0     # kB → MB
            except (IndexError, ValueError):
                pass
    return 0.0


def _pinnable_core(preferred: int) -> int | None:
    """A CPU the process may ACTUALLY run on — the requested core if allowed, else the highest
    available one. `taskset -c 2` fails on a 2-core box (e.g. a CI runner: cores 0,1 only), which
    would silently break every benchmark. None → affinity unknown (non-Linux); caller skips pinning."""
    try:
        avail = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return None
    if not avail:
        return None
    return preferred if preferred in avail else avail[-1]


def _run(binary: str, n: int, reps: int, core: int | None) -> tuple[list[float], str]:
    """One timing invocation → (per-rep times, stderr). The binary times internally, so taskset/
    spawn overhead never enters the numbers."""
    base = [binary, "bench", str(n), str(reps)]
    cmd = ["taskset", "-c", str(core), *base] if (core is not None and shutil.which("taskset")) else base
    res = sandbox.run(cmd, timeout_sec=180, isolate=True)
    times = [float(x) for x in res.stdout.split() if x.strip()]
    if not times and cmd is not base:            # taskset misfired (e.g. bad core) → retry unpinned
        res = sandbox.run(base, timeout_sec=180, isolate=True)
        times = [float(x) for x in res.stdout.split() if x.strip()]
    return times, res.stderr


def measure(binary: str, *, n: int = 2_000_000, reps: int = 12, pin_core: int = 2) -> Samples:
    times, stderr = _run(binary, n, reps, _pinnable_core(pin_core))
    size_mb = os.path.getsize(binary) / 1e6 if os.path.exists(binary) else 0.0
    return summarize(times, binary_size=size_mb, peak_memory=_peak_memory_mb(stderr))


def measure_ab(a_bin: str, b_bin: str, *, n: int = 2_000_000, reps: int = 12,
               pin_core: int = 2, batch: int = 4) -> tuple[Samples, Samples]:
    """**Interleaved** A/B timing — alternate short batches of each binary so both are sampled
    across the SAME time window. A sequential 'all-A-then-all-B' measurement biases the DELTA
    (the gate's key metric) when load drifts between the two windows — the exact failure mode on
    a shared/noisy runner, where a real ~50% win can read as 'not faster'. Sampling both in
    lockstep makes any drift hit them equally, so it cancels out of the delta. The lead side
    alternates each round so neither systematically gets the 'first, colder' slot."""
    core = _pinnable_core(pin_core)
    a_times: list[float] = []
    b_times: list[float] = []
    a_err = b_err = ""
    left, lead_a = reps, True
    while left > 0:
        k = min(batch, left)
        if lead_a:
            ta, a_err = _run(a_bin, n, k, core); tb, b_err = _run(b_bin, n, k, core)
        else:
            tb, b_err = _run(b_bin, n, k, core); ta, a_err = _run(a_bin, n, k, core)
        a_times += ta
        b_times += tb
        left -= k
        lead_a = not lead_a
    sa = os.path.getsize(a_bin) / 1e6 if os.path.exists(a_bin) else 0.0
    sb = os.path.getsize(b_bin) / 1e6 if os.path.exists(b_bin) else 0.0
    return (summarize(a_times, binary_size=sa, peak_memory=_peak_memory_mb(a_err)),
            summarize(b_times, binary_size=sb, peak_memory=_peak_memory_mb(b_err)))
