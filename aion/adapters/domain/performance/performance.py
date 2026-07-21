"""Performance Oracle (Performance domain) — the Performance Vector. TRUSTED.

Mirrors AION.md §9.3 and AION_Architecture §16.5. REAL implementation: build the
original and variant timing programs at -O2 -march=native, benchmark both (pinned
core, warmup, N reps), capture the vector, and apply the Pareto rule — accept
only if >=1 objective improves significantly and none regresses past its budget.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from ....engine.config import Config
from ....engine.models import PerfVerdict, Target, Variant
from ....runtime import bench_runner
from ...language.cpp.build import compile_program
from .harness import make_program

_OPT = ["-std=c++20", "-O2", "-march=native"]
_BENCH_N = 2_000_000


class PerformanceOracleImpl:
    def __init__(self, config: Config) -> None:
        self._config = config

    def compare(self, orig: Target, var: Variant) -> PerfVerdict:
        func = orig.symbol
        orig_src = Path(orig.file).read_text(encoding="utf-8")
        reps = getattr(self._config, "reps", 30)

        with tempfile.TemporaryDirectory(prefix="aion-perf-") as wd:
            a = compile_program(make_program(orig_src, func, "timing"),
                                f"{wd}/orig", flags=_OPT, workdir=wd)
            b = compile_program(make_program(var.source_after, func, "timing"),
                                f"{wd}/var", flags=_OPT, workdir=wd)
            if not (a.build_ok and b.build_ok):
                return PerfVerdict(vector={}, pareto_pass=False, samples=0)

            before = bench_runner.measure(a.binary_path, n=_BENCH_N, reps=reps)
            after = bench_runner.measure(b.binary_path, n=_BENCH_N, reps=reps)

        bv = {"p50": before.p50, "p99": before.p99,
              "peak_memory": before.peak_memory, "binary_size": before.binary_size}
        av = {"p50": after.p50, "p99": after.p99,
              "peak_memory": after.peak_memory, "binary_size": after.binary_size}
        vector = dict(av)
        vector["p50_before"] = before.p50
        vector["p50_delta_pct"] = _pct(before.p50, after.p50)
        return PerfVerdict(vector=vector, pareto_pass=self._pareto(bv, av),
                           samples=len(after.raw))

    def _pareto(self, before: dict, after: dict) -> bool:
        if _pct(before["p50"], after["p50"]) < self._config.min_speedup_pct:
            return False                                   # not meaningfully faster
        for obj in self._config.objectives:
            if obj == "p50" or obj not in before:
                continue
            if before[obj] == 0 and after[obj] == 0:
                continue
            budget = self._config.allow_regression.get(obj, 0.0)
            if after[obj] > before[obj] * (1.0 + budget):
                return False                               # regressed past budget -> Pareto-loser
        return True


def _pct(before: float, after: float) -> float:
    return 100.0 * (before - after) / before if before else 0.0
