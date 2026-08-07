"""2A — oracle reach via the test-reuse PRIMARY oracle.

A function taking a std::map parameter can't be synth-harnessed, so without 2A it's an
honest SKIP. With --test-command (correctness) + --bench-command (perf), BOOSTOPT verifies a
BODY-ONLY change (reserve) against the project's OWN test + bench — reaching a real win the
synthetic harness alone cannot. Requires clang++ (like the other build-backed tests).
"""
import shutil

import pytest

from boostopt.adapters.language.cpp.sensor import CppSensor
from boostopt.engine.api import Engine
from boostopt.engine.config import Config
from boostopt.engine.models import Target

pytestmark = pytest.mark.skipif(shutil.which("clang++") is None, reason="needs clang++")

EX = "examples/reach/stats.cpp"
TEST = "clang++ -O2 -std=c++20 stats.cpp stats_test.cpp -o _t && ./_t"
BENCH = "clang++ -O2 -std=c++20 stats.cpp stats_bench.cpp -o _b && ./_b >/dev/null"


def _cfg(**kw):
    c = Config()
    c.model = "rules"
    c.bench_runs = 2
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_sensor_skips_without_tests():
    """No test-command → the map-param function is an honest skip, not routed anywhere."""
    ev = CppSensor(_cfg()).collect(Target(EX, "", 0, "cpp"))
    assert ev.target.verify_mode == "harness"
    assert ev.target.symbol == ""
    assert any(s.func == "scaled" for s in ev.skips)


def test_sensor_routes_to_test_mode():
    """With a test-command, the same function is routed to the test-primary oracle."""
    ev = CppSensor(_cfg(test_command="true")).collect(Target(EX, "", 0, "cpp"))
    assert ev.target.verify_mode == "tests"
    assert ev.target.symbol == "scaled"


def test_no_verdict_without_tests():
    assert Engine(_cfg()).optimize(EX, apply=False) == []


def test_perf_unproven_without_bench():
    """Tests pass but no bench signal → can't prove faster → not accepted (honest)."""
    vs = Engine(_cfg(test_command=TEST)).optimize(EX, apply=False)
    assert vs and not vs[0].accepted and vs[0].reason == "perf_unproven"


def test_pareto_gate_rejects_tail_and_memory_regressions():
    """2A-3: the project-bench gate is a full Pareto gate, not a p50 threshold — a p50 win
    that regresses p99 (tail) or peak_memory past budget is rejected."""
    from boostopt.adapters.domain.performance.reuse import TestReuseOracle
    o = TestReuseOracle(Config())
    assert o._pareto({"p50": 1.0, "p99": 1.0, "peak_memory": 100},
                     {"p50": 0.5, "p99": 0.5, "peak_memory": 100})[0]          # clean win
    assert not o._pareto({"p50": 1.0}, {"p50": 0.999})[0]                       # p50 gain too small
    assert not o._pareto({"p50": 1.0, "p99": 1.0},
                         {"p50": 0.5, "p99": 1.3})[0]                           # p99 tail +30% > budget
    assert not o._pareto({"p50": 1.0, "peak_memory": 100},
                         {"p50": 0.5, "peak_memory": 130})[0]                   # peak +30% > 12% budget


def test_accepts_via_project_tests():
    vs = Engine(_cfg(test_command=TEST, bench_command=BENCH)).optimize(EX, apply=False)
    assert len(vs) == 1
    v = vs[0]
    assert v.accepted and v.reason == "accepted"
    assert v.via == "tests" and v.tests_confirmed
    assert v.candidate.transform.name == "reserve_before_pushback"
    assert v.performance.vector["p50_delta_pct"] > 2.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
