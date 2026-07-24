"""Test-reuse correctness oracle (Phase-1 item #3). TRUSTED.

The strongest correctness signal a project has is its OWN test suite — its real
acceptance criteria, which the synthetic harness's fixed inputs can miss. When a
`test_command` is configured, VERTO builds the variant into the real project and
runs those tests: if they passed on the original and still pass on the variant,
the change is behavior-preserving as far as the project is concerned.

v0: a CONFIRMATORY gate on changes the harness already accepted (defense in
depth). Honest verify-or-skip — if the tests fail on the ORIGINAL, the oracle
declares itself UNAVAILABLE rather than blaming the change.

Contract for `test_command`: a shell command that (re)builds and runs the tests
from source, exiting 0 on pass. Run from `test_dir` (default: the target file's
directory). It MUST rebuild from source so the swapped-in variant is what's tested.
"""
from __future__ import annotations

import hashlib
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass
class ReuseVerdict:
    available: bool          # could we use the project's tests at all?
    passed: bool             # did the variant pass them?
    detail: str = ""


@dataclass
class BenchVerdict:
    available: bool          # could we measure the project bench at all?
    faster: bool             # did the variant beat the original beyond the threshold?
    before: float = 0.0      # median seconds, original
    after: float = 0.0       # median seconds, variant
    delta_pct: float = 0.0   # +ve = faster
    runs: int = 0
    detail: str = ""


# baseline (does the ORIGINAL pass?) keyed by original-source content + command +
# cwd, so it's computed once per run and never stale across an --apply rewrite.
_BASELINE: dict[str, bool] = {}


class TestReuseOracle:
    __test__ = False                     # not a pytest test class (name starts with "Test")

    def __init__(self, config) -> None:
        self._cmd = getattr(config, "test_command", None)
        self._dir = getattr(config, "test_dir", None)
        self._timeout = int(getattr(config, "test_timeout_sec", 600) or 600)
        self._bench_cmd = getattr(config, "bench_command", None)
        self._bench_dir = getattr(config, "bench_dir", None)
        self._bench_runs = max(1, int(getattr(config, "bench_runs", 5) or 5))
        self._min_speedup = float(getattr(config, "min_speedup_pct", 2.0) or 2.0)

    def enabled(self) -> bool:
        return bool(self._cmd)

    def bench_enabled(self) -> bool:
        return bool(self._bench_cmd)

    def confirm(self, orig, var) -> ReuseVerdict:
        if not self._cmd:
            return ReuseVerdict(False, False, "no test_command configured")
        path = Path(orig.file)
        cwd = self._dir or str(path.parent)
        original_src = path.read_text(encoding="utf-8")

        # baseline: the ORIGINAL must pass, else a failure can't be blamed on us.
        key = hashlib.sha1(f"{cwd}\0{self._cmd}\0{original_src}".encode("utf-8")).hexdigest()
        base = _BASELINE.get(key)
        if base is None:
            base = self._run(cwd)
            _BASELINE[key] = base
        if not base:
            return ReuseVerdict(False, False,
                                "project tests fail on the ORIGINAL — can't use as an oracle")

        # swap the variant into the real source, run the tests, ALWAYS restore.
        try:
            path.write_text(var.source_after, encoding="utf-8")
            ok = self._run(cwd)
        finally:
            path.write_text(original_src, encoding="utf-8")
        return ReuseVerdict(True, ok,
                            "project tests pass" if ok else "project tests FAIL on the variant")

    def bench(self, orig, var) -> BenchVerdict:
        """Project-level perf signal (2A-3): time `bench_command` on the original vs the
        variant source, median-of-N, and decide faster iff the gain clears min_speedup.

        The bench_command MUST (re)build from source so the swapped-in variant is what
        runs; its wall time is what we compare. Verify-or-skip: unavailable → no verdict.
        v0 scope: the timing includes the bench binary's own build (compile is constant-
        ish; make the workload dominate), and the run is not core-pinned — coarse but
        sound as a Pareto signal, not a micro-benchmark."""
        if not self._bench_cmd:
            return BenchVerdict(False, False, detail="no bench_command configured")
        path = Path(orig.file)
        cwd = self._bench_dir or self._dir or str(path.parent)
        original_src = path.read_text(encoding="utf-8")
        try:
            before = self._time(cwd, self._bench_runs)
            path.write_text(var.source_after, encoding="utf-8")
            after = self._time(cwd, self._bench_runs)
        finally:
            path.write_text(original_src, encoding="utf-8")
        if before is None or after is None:
            return BenchVerdict(False, False, detail="bench_command failed to run")
        delta = 100.0 * (before - after) / before if before else 0.0
        faster = delta >= self._min_speedup
        return BenchVerdict(True, faster, before=before, after=after, delta_pct=delta,
                            runs=self._bench_runs,
                            detail=(f"{delta:+.1f}% (project bench)" if faster
                                    else f"not faster ({delta:+.1f}% < {self._min_speedup:g}%)"))

    def _time(self, cwd: str, runs: int) -> float | None:
        """Median wall time (seconds) of `bench_command` over `runs`; None if any run
        fails (a build/run error means we can't trust the measurement)."""
        samples = []
        for _ in range(runs):
            t0 = time.perf_counter()
            try:
                r = subprocess.run(self._bench_cmd, shell=True, cwd=cwd, capture_output=True,
                                   text=True, timeout=self._timeout)
            except Exception:
                return None
            if r.returncode != 0:
                return None
            samples.append(time.perf_counter() - t0)
        return median(samples) if samples else None

    def _run(self, cwd: str) -> bool:
        try:
            r = subprocess.run(self._cmd, shell=True, cwd=cwd, capture_output=True,
                               text=True, timeout=self._timeout)
            return r.returncode == 0
        except Exception:
            return False
