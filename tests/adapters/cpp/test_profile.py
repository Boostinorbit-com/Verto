"""Real-profile-guided hotspot selection (Phase-1 item #5).

`--profile` must make BOOSTOPT optimize the function that's actually hot in the
user's workload — even when that DISAGREES with the synthetic micro-benchmark.
The falsifiable check: a profile that says the micro-bench's cold function is hot
must flip the selection.
"""
import tempfile
from pathlib import Path

from boostopt.adapters.language.cpp.profile import _leaf, load_profile
from boostopt.adapters.language.cpp.sensor import CppSensor
from boostopt.engine.config import Config
from boostopt.engine.models import Target

from tests import EXAMPLES
MULTI = EXAMPLES / "multi_candidate.cpp"


def _cfg(profile=None):
    c = Config()
    c.model = "rules"
    c.profile = profile
    return c


def _chosen(profile_path):
    load_profile.cache_clear()
    ev = CppSensor(_cfg(profile_path)).collect(
        Target(file=str(MULTI), symbol="", line=0, language="cpp"))
    return ev.target.symbol, (ev.profile.extra.get("profiler") if ev.profile else None)


def test_leaf_reduces_symbol_to_identifier():
    assert _leaf("ns::Foo::bar(int, double)") == "bar"
    assert _leaf("hot_path(unsigned long)") == "hot_path"
    assert _leaf("route_costs") == "route_costs"


def test_formats_parse_to_leaf_costs():
    from boostopt.adapters.language.cpp.profile import _parse
    assert _parse("  42.1%  b  b  [.] hot_path\n  3.2%  b  b  [.] cold_path(unsigned long)") \
        == {"hot_path": 42.1, "cold_path": 3.2}
    assert _parse('{"hot_path": 5.0, "ns::cold_path(int)": 91.0}') \
        == {"hot_path": 5.0, "cold_path": 91.0}


def test_real_profile_overrides_microbench():
    # baseline: no profile → the micro-benchmark picks the true-hot hot_path
    sym, who = _chosen(None)
    assert sym == "hot_path" and who == "microbench-v0"

    # a real profile that says cold_path dominates must flip the choice
    d = Path(tempfile.mkdtemp(prefix="boostopt-prof-"))
    try:
        p = d / "perf.txt"
        p.write_text("  88.00%  bench  bench  [.] cold_path(unsigned long)\n"
                     "   4.10%  bench  bench  [.] hot_path(unsigned long)\n")
        sym, who = _chosen(str(p))
        assert sym == "cold_path", "real profile must drive selection"
        assert who == "external", "should record that the choice came from an external profile"
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("all profile tests passed")
