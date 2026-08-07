"""Skip logging with reasons (Phase-1 item #4).

A candidate site BOOSTOPT can see but can't verify must be reported as a SKIP with a
reason — not silently dropped, and not mislabeled as 'nothing found'. Pins the
sensor-level skip (opportunity present, signature unharnessable) end to end via
codebase mode. Real compilation, a few seconds. Run with `python -m tests.test_skips`.
"""
import shutil
import tempfile
from pathlib import Path

from boostopt.adapters.domain.performance.harness import supported, unsupported_reason
from boostopt.engine.api import Engine
from boostopt.engine.config import Config

LINKED = Path(__file__).resolve().parent.parent / "examples" / "linked"


def _cfg():
    c = Config()
    c.model = "rules"
    return c


def _copy_project():
    d = Path(tempfile.mkdtemp(prefix="boostopt-skip-test-"))
    for f in LINKED.iterdir():
        if f.is_file():
            shutil.copy2(f, d / f.name)
    return d


def test_unharnessable_candidate_is_skipped_with_reason():
    d = _copy_project()
    try:
        results = Engine(_cfg()).optimize_codebase(str(d / "compile_commands.json"), apply=False)
        skips = next(sk for f, _v, err, sk in results if f.endswith("report.cpp") and not err)
        # mix() takes a NON-const int* (writable BY TYPE) → still
        # unsynthesizable → an honest skip. (gather(), a const-ptr+length pair, is now
        # harness-able via B2-a, so it must NOT appear as a skip.)
        s = next(x for x in skips if x.func == "mix")
        assert s.stage == "harness"
        assert "pointer" in s.reason or "*" in s.reason, f"reason should name the offending type; got {s.reason!r}"
        assert not any(x.func == "gather" for x in skips), "gather is synthesizable via B2-a → not a skip"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_supported_function_produces_no_skip():
    d = _copy_project()
    try:
        results = Engine(_cfg()).optimize_codebase(str(d / "compile_commands.json"), apply=False)
        route = next((v, sk) for f, v, err, sk in results if f.endswith("route.cpp") and not err)
        verdicts, skips = route
        assert any(v.accepted for v in verdicts), "route_costs is harnessable → verified, not skipped"
        assert skips == [], "a verifiable function must not generate a skip"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_unsupported_reason_is_specific():
    """The reason string names WHY, so a real-repo scan is actionable."""
    src = Path(LINKED / "report.cpp").read_text()
    assert not supported(src, "mix")                          # non-const pointer (writable by type)
    reason = unsupported_reason(src, "mix")
    assert reason and ("pointer" in reason or "*" in reason)
    assert supported(src, "gather")                           # const-ptr + length → B2-a synthesizes it
    # a plain harnessable function has no reason
    good = "#include <vector>\n#include <cstddef>\n"\
           "std::vector<int> f(std::size_t n){ std::vector<int> o; for(std::size_t i=0;i<n;++i) o.push_back((int)i); return o; }"
    assert supported(good, "f") and unsupported_reason(good, "f") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("all skip tests passed")
