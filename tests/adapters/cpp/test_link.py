"""Link-against-the-build (Phase-1 item #1).

A function that calls into ANOTHER translation unit can only be verified if the
harness links against the rest of the project. These tests pin both halves of the
contract on a real 2-TU project (route.cpp calls point_weight() in geo.cpp):

  * with the sibling TU present  → the archive resolves the call → VERIFY + ACCEPT
  * with the sibling TU absent   → the link can't resolve → honest SKIP, not a
    false rejection and not a crash.

Real compilation, so a few seconds. Run with `python -m tests.test_link` or pytest.
"""
import pytest

import json
import shutil
import tempfile
from pathlib import Path

from boostopt.engine.api import Engine
from boostopt.engine.config import Config

from tests import LINKED


def _cfg():
    c = Config()
    c.model = "rules"          # deterministic proposer, no API key
    return c


def _copy_project():
    d = Path(tempfile.mkdtemp(prefix="boostopt-link-test-"))
    for name in ("geo.h", "geo.cpp", "route.cpp", "compile_commands.json"):
        shutil.copy2(LINKED / name, d / name)
    return d


def _route_verdicts(results):
    for f, verdicts, err, _skips in results:
        assert err is None, f"{f}: {err}"
        if f.endswith("route.cpp"):
            return verdicts
    raise AssertionError("route.cpp not in results")


@pytest.mark.toolchain
def test_cross_tu_function_is_verified_and_accepted():
    d = _copy_project()
    try:
        results = Engine(_cfg()).optimize_codebase(str(d / "compile_commands.json"), apply=False)
        vs = _route_verdicts(results)
        assert any(v.accepted and v.reason == "accepted" for v in vs), \
            "cross-TU function should link against the build and be accepted"
        acc = next(v for v in vs if v.accepted)
        assert acc.correctness.rung >= 3, "should reach the sanitizer rung, not just the diff-test"
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.toolchain
def test_missing_dependency_is_an_honest_skip_not_a_reject():
    """Drop geo.cpp from the db: the call can't be linked. BOOSTOPT must skip it
    honestly (reason 'skipped_unverifiable'), never claim it as a rejection."""
    d = _copy_project()
    try:
        db = d / "compile_commands.json"
        entries = [e for e in json.loads(db.read_text()) if e["file"] != "geo.cpp"]
        db.write_text(json.dumps(entries))
        (d / "geo.cpp").unlink()          # dependency genuinely absent

        results = Engine(_cfg()).optimize_codebase(str(db), apply=False)
        vs = _route_verdicts(results)
        assert not any(v.accepted for v in vs), "must not accept an unverifiable function"
        assert all(v.reason == "skipped_unverifiable" for v in vs), \
            f"unlinkable original = skip, not reject; got {[v.reason for v in vs]}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("all link tests passed")
