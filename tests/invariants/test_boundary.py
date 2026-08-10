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

from setuptools import find_packages

from tests import REPO_ROOT as _ROOT


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


def test_runtime_assets_are_module_constants_not_data_files():
    """`boostopt demo` and `boostopt init` must work from a COMPILED distribution.

    A Nuitka `--module` build collapses the package into one .so, leaving no filesystem package
    for importlib.resources — verified: as data files these silently resolved to "not found",
    losing the demo and downgrading every install to the bare base model. As module constants
    they compile into the binary. Reintroducing package data would regress the compiled build,
    which no pure-Python test run would catch.
    """
    from boostopt.examples import DEMO_NAME, DEMO_SOURCE
    from boostopt.runtime.models import MODELFILES

    assert DEMO_NAME.endswith(".cpp") and "build_histogram" in DEMO_SOURCE
    assert "boostopt2.5-coder" in MODELFILES
    assert "FROM qwen2.5-coder:7b" in MODELFILES["boostopt2.5-coder"]

    # Apache-2.0 attribution to Qwen is a licence obligation, not a comment.
    assert "Apache-2.0" in MODELFILES["boostopt2.5-coder"]

    # No package-data glob should come back: it would imply a shipped file again. Match the
    # SECTION HEADER at line start — the name also appears in a comment explaining its absence,
    # and a plain substring check flags that comment as the very thing it warns against.
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert not re.search(r"^\[tool\.setuptools\.package-data\]", text, re.M), \
        "package data reintroduced — compiled builds lose it silently"


def test_no_stray_data_files_left_inside_the_package():
    """The .Modelfile / .cpp used to live here. If one reappears it is a second source of truth
    that the compiled build will not ship."""
    strays = [p.name for p in (_ROOT / "boostopt").rglob("*")
              if p.suffix in (".Modelfile", ".cpp", ".modelfile")]
    assert not strays, f"data files inside boostopt/ won't survive compilation: {strays}"
