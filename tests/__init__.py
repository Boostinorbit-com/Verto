"""BOOSTOPT test suite.

Layout mirrors `boostopt/`'s layers — `engine/`, `adapters/`, `runtime/`, `surfaces/` — plus
`premium/` (boostopt_server) and `invariants/` (repo-wide rules like the open-core boundary).
Cost is orthogonal to layer and lives in MARKERS, not folders: `pytest -m "not toolchain"`
skips everything that shells out to clang++. See `[tool.pytest.ini_options]` in pyproject.toml.

The paths below are defined ONCE, here. Tests used to spell the repo root as
`Path(__file__).parent.parent`, which silently pointed at `tests/` the moment the files moved
into subfolders — so it's derived by walking up to the pyproject.toml instead, and survives
any future reshuffle.
"""
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for d in here.parents:
        if (d / "pyproject.toml").is_file():
            return d
    return here.parent.parent            # fallback: installed/ad-hoc layout with no pyproject


REPO_ROOT = _repo_root()
EXAMPLES = REPO_ROOT / "examples"        # the real C++ files the end-to-end tests optimize
LINKED = EXAMPLES / "linked"             # multi-TU project (cross-TU link + harness tests)
FIXTURES = Path(__file__).resolve().parent / "fixtures"   # cmake_project, etc.
