"""2A-1 — CMake/ctest test-target discovery + 2A-3 test-timing fallback.

Point BOOSTOPT at a CMake build dir; it enumerates ctest, derives the test + bench commands,
and verifies an unharnessable-signature function via the project's OWN suite — no manually
typed commands. Requires cmake/ctest/clang++ (skips otherwise). The fixture is copied to a
tmp dir so the committed source is never mutated by the variant swap.
"""
import os
import shutil
import subprocess
import tempfile

import pytest

from boostopt.adapters.language.cpp.cmake_ctest import discover_ctest
from boostopt.engine.api import Engine
from boostopt.engine.config import Config

_HAVE = all(shutil.which(t) for t in ("cmake", "ctest")) and (
    shutil.which("clang++") or shutil.which("g++"))
pytestmark = pytest.mark.skipif(not _HAVE, reason="needs cmake/ctest + a C++ compiler")

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cmake_project")


@pytest.fixture
def built_project():
    tmp = tempfile.mkdtemp()
    proj = os.path.join(tmp, "proj")
    shutil.copytree(FIXTURE, proj)
    build = os.path.join(proj, "build")
    subprocess.run(["cmake", "-S", proj, "-B", build, "-DCMAKE_BUILD_TYPE=Release"],
                   check=True, capture_output=True)
    subprocess.run(["cmake", "--build", build], check=True, capture_output=True)
    yield proj, build
    shutil.rmtree(tmp, ignore_errors=True)


def test_discovers_test_and_bench(built_project):
    _proj, build = built_project
    d = discover_ctest(build)                                        # no target → whole suite
    assert set(d.tests) == {"stats_correctness", "stats_bench", "other_correctness"}
    assert d.test_command and "cmake --build" in d.test_command      # rebuilds → variant is tested
    assert "stats_correctness" in d.test_command                     # correctness tests run via -R
    assert "stats_bench" not in d.test_command                       # the bench is not a correctness test
    assert d.build_command and "cmake --build" in d.build_command    # build once, then time run-only
    assert d.bench_argv and d.bench_argv[0].endswith("stats_bench")  # direct bench exe (clean p50/p99/peak)


def test_tu_targeting_excludes_unrelated_tests(built_project):
    """2A-1: targeting stats.cpp runs only the tests that reference its symbols (via nm),
    excluding an unrelated test that never touches the TU."""
    proj, build = built_project
    d = discover_ctest(build, target_file=os.path.join(proj, "stats.cpp"))
    assert d.targeted
    assert "stats_correctness" in d.targeted_tests
    assert "other_correctness" not in d.targeted_tests               # doesn't reference stats.cpp → excluded
    assert "stats_correctness" in d.test_command
    assert "other_correctness" not in d.test_command


def test_discovery_on_non_ctest_dir_is_empty(tmp_path):
    d = discover_ctest(str(tmp_path))                  # not a ctest build → empty, no crash
    assert d.test_command is None and d.tests == ()


def test_end_to_end_via_discovered_commands(built_project):
    proj, build = built_project
    d = discover_ctest(build)
    c = Config(); c.model = "rules"; c.bench_runs = 2
    c.test_command = d.test_command
    c.bench_argv = tuple(d.bench_argv); c.build_command = d.build_command
    vs = Engine(c).optimize(os.path.join(proj, "stats.cpp"), apply=False)
    acc = [v for v in vs if v.accepted]
    assert acc and acc[-1].via == "tests" and acc[-1].tests_confirmed
    assert acc[-1].candidate.transform.name == "reserve_before_pushback"
    # full Pareto vector from the direct bench executable (2A-3 gap closed)
    assert {"p50", "p99", "peak_memory"} <= set(acc[-1].performance.vector)


def test_no_bench_is_perf_unproven(built_project):
    """With no bench signal (no discovered *bench* test, no --bench-command), BOOSTOPT does NOT
    fall back to timing a trivial test (noise → false accepts): it honestly says perf_unproven."""
    proj, build = built_project
    c = Config(); c.model = "rules"
    c.test_command = discover_ctest(build).test_command    # correctness only, no bench_command
    vs = Engine(c).optimize(os.path.join(proj, "stats.cpp"), apply=False)
    assert vs and not vs[-1].accepted and vs[-1].reason == "perf_unproven"
