"""Open-core boundary invariants — the paywall is ARCHITECTURAL, so it must be tested, not trusted.

Two things that, if they silently break, leak the proprietary hosted tier into the free product:

  1. the published wheel must EXCLUDE `boostopt_server` (a careless `include = ["boostopt*"]` glob bundles
     it — that bug shipped once and was caught by hand; this locks it), and
  2. the free client `boostopt/` must NEVER import `boostopt_server` (the dependency is one-way:
     boostopt_server → boostopt, never the reverse).

Both are cheap static checks with no build step, so they run in the normal suite / CI.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from setuptools import find_packages

_ROOT = Path(__file__).resolve().parent.parent


def _packages_find_config() -> tuple[list[str], list[str]]:
    """Read `include`/`exclude` from [tool.setuptools.packages.find] in pyproject.toml without a
    TOML lib (system python here is 3.8, no tomllib). Guards the REAL arrays the build uses."""
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r"^\[tool\.setuptools\.packages\.find\]\s*$", text, re.M)
    assert m, "pyproject.toml lost its [tool.setuptools.packages.find] section"
    block = text[m.end():]
    block = block[: (re.search(r"^\[", block, re.M) or re.search(r"\Z", block)).start()]

    def _arr(key: str) -> list[str]:
        km = re.search(rf"^{key}\s*=\s*(\[[^\]]*\])", block, re.M)
        return ast.literal_eval(km.group(1)) if km else []

    return _arr("include"), _arr("exclude")


def test_wheel_excludes_boostopt_server():
    include, exclude = _packages_find_config()
    assert "boostopt_server*" in exclude, (
        "pyproject must exclude boostopt_server* from the published wheel — without it the "
        "'boostopt*' include glob bundles the proprietary hosted package into the free build.")
    pkgs = find_packages(where=str(_ROOT), include=include, exclude=exclude)
    leaked = [p for p in pkgs if p == "boostopt_server" or p.startswith("boostopt_server.")]
    assert not leaked, f"boostopt_server would ship in the wheel: {leaked}"
    assert "boostopt" in pkgs, "sanity: the free core 'boostopt' must still be included"


def test_client_never_imports_server():
    offenders: list[str] = []
    pat = re.compile(r"^\s*(?:import\s+boostopt_server|from\s+boostopt_server)\b", re.M)
    for py in (_ROOT / "boostopt").rglob("*.py"):
        if pat.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py.relative_to(_ROOT)))
    assert not offenders, (
        "the free client imports boostopt_server (dependency must be one-way, "
        f"boostopt_server → boostopt only): {offenders}")
