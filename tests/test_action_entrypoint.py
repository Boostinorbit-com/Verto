"""#18 step 2 — the GitHub Action entrypoint bridge.

Pure-function tests (input→argv mapping, report→outputs, $GITHUB_OUTPUT writing)
run everywhere; one integration test drives the whole bridge through the real
`verto` CLI against examples/linked, diffing vs the git empty-tree so every tracked
TU counts as "changed" (deterministic). The bridge lives outside the package, so
we load it by path.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENTRY = os.path.join(_ROOT, "examples", "github-action", "entrypoint.py")
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"   # git's canonical empty tree


def _load():
    spec = importlib.util.spec_from_file_location("verto_action_entrypoint", _ENTRY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _inp(d: dict):
    """A get_input stand-in backed by a plain dict of input-name → value."""
    return lambda name, default="": (d.get(name) or default)


# ---- build_argv: inputs → CLI ---------------------------------------------------

def test_build_argv_minimal_defaults():
    m = _load()
    argv, patches, mode = m.build_argv(_inp({"compile-commands": "build/cc.json"}))
    assert argv[:4] == ["optimize", "-p", "build/cc.json", "--json"]
    assert "--changed" in argv                      # PR-scoped by default
    assert argv[argv.index("--fail-on") + 1] == "none"   # advisory unless asked
    assert mode == "comment" and patches == ""      # no patch emission in comment mode


def test_build_argv_full_mapping():
    m = _load()
    argv, patches, mode = m.build_argv(_inp({
        "compile-commands": "cc.json", "base-ref": "origin/main", "model": "local",
        "min-speedup": "3", "min-rung": "1", "objectives": "p50,peak_memory",
        "jobs": "4", "metamorphic": "true", "fail-on": "any", "mode": "suggest",
        "extra-args": "--fp-tolerance 1e-9",
    }))
    # base-ref becomes the --changed argument (not the default working-tree form)
    assert argv[argv.index("--changed") + 1] == "origin/main"
    assert argv[argv.index("--model") + 1] == "local"
    assert argv[argv.index("--min-speedup") + 1] == "3"
    assert argv[argv.index("--fail-on") + 1] == "any"
    assert "--metamorphic" in argv
    assert argv[-2:] == ["--fp-tolerance", "1e-9"]  # extra-args passed through, last
    assert mode == "suggest" and patches.endswith("verto-patches")
    assert "--emit-patches" in argv                 # suggest/pr emit patches for step 3


def test_build_argv_requires_compile_commands():
    m = _load()
    with pytest.raises(SystemExit):
        m.build_argv(_inp({}))


# ---- compute_outputs: report → outputs -----------------------------------------

def test_compute_outputs_found_and_clean():
    m = _load()
    report = [
        {"file": "a.cpp", "error": None, "skips": [],
         "verdicts": [{"accepted": True, "applied": False},
                      {"accepted": False, "applied": False}]},
        {"file": "b.cpp", "error": None, "skips": [], "verdicts": []},
    ]
    out = m.compute_outputs(report, mode="comment", patches_dir="", report_path="/r.json")
    assert out["status"] == "found" and out["findings"] == 1
    assert out["applied"] == 0 and out["regressions"] == 0
    assert out["report-json"] == "/r.json" and out["patches"] == ""

    empty = m.compute_outputs([], mode="comment", patches_dir="", report_path="/r.json")
    assert empty["status"] == "clean" and empty["findings"] == 0


def test_write_outputs_to_github_output(tmp_path, monkeypatch):
    m = _load()
    gh = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    m.write_outputs({"status": "found", "findings": 2})
    text = gh.read_text()
    assert "status=found" in text and "findings=2" in text


# ---- end-to-end: the bridge drives the real CLI --------------------------------

@pytest.mark.skipif(not shutil.which("clang++"), reason="needs a C++ toolchain")
def test_entrypoint_end_to_end(tmp_path, monkeypatch):
    """Run the whole bridge. Diffing vs the empty tree makes every tracked TU
    'changed', so examples/linked is actually processed. We assert the wiring
    invariant that holds regardless of how many wins land: with fail-on=any the
    exit code is 1 iff a verified optimization was found."""
    if not shutil.which("git"):
        pytest.skip("needs git")
    gh_out = tmp_path / "gh_output.txt"
    env = dict(os.environ)
    env.update({
        "VERTO_BIN": f"{sys.executable} -m verto.surfaces.cli",
        "GITHUB_WORKSPACE": _ROOT,               # verto runs here (resolves the relative db)
        "RUNNER_TEMP": str(tmp_path),            # …but artifacts land here, not in the repo
        "GITHUB_OUTPUT": str(gh_out),
        "INPUT_COMPILE-COMMANDS": "examples/linked/compile_commands.json",
        "INPUT_BASE-REF": _EMPTY_TREE,
        "INPUT_MODEL": "rules",
        "INPUT_FAIL-ON": "any",
    })
    proc = subprocess.run([sys.executable, _ENTRY], cwd=_ROOT, env=env,
                          capture_output=True, text=True, timeout=300)

    outs = dict(ln.split("=", 1) for ln in gh_out.read_text().splitlines() if "=" in ln)
    findings = int(outs["findings"])
    assert outs["status"] == ("found" if findings else "clean")
    # the point of the whole feature: fail-on=any → red iff there's a verified win
    assert proc.returncode == (1 if findings else 0), proc.stderr
    assert os.path.exists(outs["report-json"])
    json.loads(open(outs["report-json"]).read())        # report is valid JSON
