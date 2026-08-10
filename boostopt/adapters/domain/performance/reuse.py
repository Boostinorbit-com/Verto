"""Test-reuse correctness oracle (Phase-1 item #3). TRUSTED.

The strongest correctness signal a project has is its OWN test suite — its real
acceptance criteria, which the synthetic harness's fixed inputs can miss. When a
`test_command` is configured, BOOSTOPT builds the variant into the real project and
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
import os
import subprocess
import time
from dataclasses import dataclass, field
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
    faster: bool             # did the variant PASS THE FULL PARETO GATE (p50 win, no p99/mem regression)?
    before: float = 0.0      # p50 seconds, original
    after: float = 0.0       # p50 seconds, variant
    delta_pct: float = 0.0   # p50 delta, +ve = faster
    runs: int = 0
    detail: str = ""
    vector: dict = field(default_factory=dict)   # {p50,p99,peak_memory} after + *_before + p50_delta_pct


def _pct(before: float, after: float) -> float:
    return 100.0 * (before - after) / before if before else 0.0


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
        # 2A-3: a direct bench executable (from ctest, item 2A-1) → clean p50/p99/peak; a
        # `build_command` lets us build ONCE so the timed runs are run-only.
        self._bench_argv = tuple(getattr(config, "bench_argv", ()) or ())
        self._build_cmd = getattr(config, "build_command", None)
        _budgets = dict(getattr(config, "allow_regression", {}) or {})
        self._p99_budget = float(_budgets.get("p99", 0.10))       # tolerate project-bench tail noise
        self._mem_budget = float(_budgets.get("peak_memory", 0.12))

    def enabled(self) -> bool:
        return bool(self._cmd)

    def bench_enabled(self) -> bool:
        # 2A-3: a dedicated bench (a --bench-command, or a ctest *bench* test 2A-1 discovered)
        # is the perf signal. We deliberately do NOT fall back to timing the test command: a
        # trivial unit test is noise-dominated and could FALSELY accept on noise.
        return bool(self._bench_cmd or self._bench_argv)

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
        """Project-level perf signal (2A-3): measure the project bench on the original vs the
        variant source and apply the FULL PARETO GATE — a p50 win that clears min_speedup AND
        no regression past budget on p99 (tail latency) or peak_memory. This is the Pareto
        rule the micro-harness uses, fed by the project's own bench instead of a synthetic one.

        Two measurement modes:
          - direct executable (`bench_argv`, from ctest 2A-1) + a one-time `build_command` →
            RUN-ONLY timing, so p50/p99 are clean and peak RSS is the bench's (via os.wait4),
            not the compiler's. Full {p50, p99, peak_memory} vector.
          - a shell `bench_command` that builds+runs → wall time only (p50/p99); peak_memory is
            masked by the build, so it's omitted and the gate covers latency only.
        Verify-or-skip: any build/run failure → unavailable, never a false accept."""
        if not (self._bench_cmd or self._bench_argv):
            return BenchVerdict(False, False, detail="no bench configured")
        path = Path(orig.file)
        cwd = self._bench_dir or self._dir or str(path.parent)
        original_src = path.read_text(encoding="utf-8")
        try:
            before = self._measure(cwd)                 # source is the ORIGINAL here
            path.write_text(var.source_after, encoding="utf-8")
            after = self._measure(cwd)
        finally:
            path.write_text(original_src, encoding="utf-8")
        if before is None or after is None:
            return BenchVerdict(False, False, detail="project bench failed to build/run")

        ok, reason = self._pareto(before, after)
        delta = _pct(before["p50"], after["p50"])
        vector = dict(after)
        for k, v in before.items():
            vector[f"{k}_before"] = v
        vector["p50_delta_pct"] = delta
        return BenchVerdict(True, ok, before=before["p50"], after=after["p50"], delta_pct=delta,
                            runs=self._bench_runs, vector=vector,
                            detail=(reason or f"{delta:+.1f}% p50 (project bench, Pareto ✓)"))

    def _measure(self, cwd: str) -> dict | None:
        """Build once (so timing is run-only), then run the bench `bench_runs` times →
        {p50: median wall, p99: max wall, peak_memory: median RSS (when measurable)}."""
        if self._build_cmd:
            try:
                b = subprocess.run(self._build_cmd, shell=True, cwd=cwd,
                                   capture_output=True, text=True, timeout=self._timeout)
            except Exception:
                return None
            if b.returncode != 0:
                return None
        walls, rss = [], []
        for _ in range(self._bench_runs):
            w, m = self._run_once(cwd)
            if w is None:
                return None
            walls.append(w)
            if m is not None:
                rss.append(m)
        vec = {"p50": median(walls), "p99": max(walls)}
        if rss:
            vec["peak_memory"] = median(rss)
        return vec

    def _run_once(self, cwd: str) -> tuple:
        """One bench run → (wall_seconds, peak_rss_kb | None)."""
        if self._bench_argv:
            # direct executable: os.wait4 gives THIS child's peak RSS (no shell/ctest to mask it)
            t0 = time.perf_counter()
            try:
                p = subprocess.Popen(list(self._bench_argv), cwd=cwd,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _pid, status, ru = os.wait4(p.pid, 0)
            except Exception:
                return None, None
            wall = time.perf_counter() - t0
            if status != 0:
                return None, None
            return wall, float(getattr(ru, "ru_maxrss", 0.0)) or None
        # shell bench_command (builds+runs) → wall only; peak is masked by the build
        t0 = time.perf_counter()
        try:
            r = subprocess.run(self._bench_cmd, shell=True, cwd=cwd,
                               capture_output=True, text=True, timeout=self._timeout)
        except Exception:
            return None, None
        if r.returncode != 0:
            return None, None
        return time.perf_counter() - t0, None

    def _pareto(self, before: dict, after: dict) -> tuple:
        """The Pareto gate on the project-bench vector: a p50 win beyond min_speedup, and no
        regression past budget on p99 or peak_memory. Returns (ok, reason)."""
        gain = _pct(before["p50"], after["p50"])
        if gain < self._min_speedup:
            return False, f"not faster (p50 {gain:+.1f}% < {self._min_speedup:g}%)"
        if before.get("p99", 0) > 0 and after["p99"] > before["p99"] * (1.0 + self._p99_budget):
            return False, (f"p99 tail regressed {-_pct(before['p99'], after['p99']):.1f}% "
                           f"> {self._p99_budget * 100:g}% budget")
        if before.get("peak_memory", 0) > 0 and after["peak_memory"] > before["peak_memory"] * (1.0 + self._mem_budget):
            return False, (f"peak_memory regressed {-_pct(before['peak_memory'], after['peak_memory']):.1f}% "
                           f"> {self._mem_budget * 100:g}% budget")
        return True, ""

    def _run(self, cwd: str) -> bool:
        try:
            r = subprocess.run(self._cmd, shell=True, cwd=cwd, capture_output=True,
                               text=True, timeout=self._timeout)
            return r.returncode == 0
        except Exception:
            return False
