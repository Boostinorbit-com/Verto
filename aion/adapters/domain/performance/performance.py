"""Performance Oracle (Performance domain) — the Performance Vector. TRUSTED.

Mirrors AION.md §9.3 and AION_Architecture §16.5. Benchmarks the original and
variant (bench mode, pinned core, warmup, N reps), captures the vector
{p50, p99, peak_memory, binary_size}, and applies the Pareto rule — accept only
if >=1 objective improves significantly and none regresses past its budget.

When given a VerifyCtx it reuses the binaries the Correctness oracle already
built (compiled once, not twice).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from ....engine.config import Config
from ....engine.models import PerfVerdict, Target, Variant
from ....runtime import bench_runner
from ._verify import get_or_build_pair
from .harness import make_program

_BENCH_N = 2_000_000


class PerformanceOracleImpl:
    def __init__(self, config: Config) -> None:
        self._config = config

    def compare(self, orig: Target, var: Variant, ctx: object | None = None) -> PerfVerdict:
        func = orig.symbol
        orig_src = Path(orig.file).read_text(encoding="utf-8")
        reps = getattr(self._config, "reps", 12)

        own_wd = tempfile.mkdtemp(prefix="aion-perf-") if ctx is None else None
        wd = own_wd if ctx is None else ctx.workdir
        try:
            a, b = get_or_build_pair(ctx, wd, make_program(orig_src, func), "orig",
                                     make_program(var.source_after, func), "var")
            if not (a.build_ok and b.build_ok):
                return PerfVerdict(vector={}, pareto_pass=False, samples=0)
            before = bench_runner.measure(a.binary_path, n=_BENCH_N, reps=reps)
            after = bench_runner.measure(b.binary_path, n=_BENCH_N, reps=reps)
        finally:
            if own_wd:
                shutil.rmtree(own_wd, ignore_errors=True)

        bv = {"p50": before.p50, "p99": before.p99,
              "peak_memory": before.peak_memory, "binary_size": before.binary_size}
        av = {"p50": after.p50, "p99": after.p99,
              "peak_memory": after.peak_memory, "binary_size": after.binary_size}
        vector = dict(av)
        vector["p50_before"] = before.p50
        vector["p50_delta_pct"] = _pct(before.p50, after.p50)
        ok, reason = self._pareto(bv, av)
        return PerfVerdict(vector=vector, pareto_pass=ok, samples=len(after.raw), reason=reason)

    def _pareto(self, before: dict, after: dict) -> tuple[bool, str]:
        gain = _pct(before["p50"], after["p50"])
        if gain < self._config.min_speedup_pct:
            return False, f"not faster (p50 {gain:+.1f}% < {self._config.min_speedup_pct:g}%)"
        for obj in self._config.objectives:
            if obj == "p50" or obj not in before or before[obj] <= 0:
                continue
            budget = self._config.allow_regression.get(obj, 0.0)
            if after[obj] > before[obj] * (1.0 + budget):
                reg = -_pct(before[obj], after[obj])
                return False, f"{obj} regressed {reg:.1f}% > {budget * 100:g}% budget"
        return True, ""


def _pct(before: float, after: float) -> float:
    return 100.0 * (before - after) / before if before else 0.0
