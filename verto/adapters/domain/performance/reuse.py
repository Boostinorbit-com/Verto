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
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReuseVerdict:
    available: bool          # could we use the project's tests at all?
    passed: bool             # did the variant pass them?
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

    def enabled(self) -> bool:
        return bool(self._cmd)

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

    def _run(self, cwd: str) -> bool:
        try:
            r = subprocess.run(self._cmd, shell=True, cwd=cwd, capture_output=True,
                               text=True, timeout=self._timeout)
            return r.returncode == 0
        except Exception:
            return False
