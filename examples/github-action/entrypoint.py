#!/usr/bin/env python3
"""BOOSTOPT GitHub Action — the entrypoint bridge (#18, step 2).

This is the glue between GitHub's Action interface and the `boostopt` CLI. It does
three things, all network-free and deterministic:

  1. reads the Action's inputs (env vars `INPUT_<NAME>`) and maps them to a
     `boostopt optimize --changed … --json --fail-on …` invocation;
  2. runs boostopt, capturing the machine-readable `--json` verdict report;
  3. translates that report into the Action's outputs (written to the file named
     by `$GITHUB_OUTPUT`) and re-emits boostopt's exit code verbatim — so `fail-on`
     is what turns the CI check red or green.

Posting the PR comment / suggestions is a *separate* step (#18 step 3) that reads
the same report; this bridge deliberately does no network I/O.

GitHub Actions Docker-action contract, for reference:
  * every input `foo-bar` arrives as env var `INPUT_FOO-BAR` (uppercased, dashes
    preserved — we also accept the underscore form for robustness);
  * an output is set by appending a `name=value` line to the file `$GITHUB_OUTPUT`;
  * the container's exit code is the check result.

Testable off-CI: set `BOOSTOPT_BIN` (e.g. `python3 -m boostopt.surfaces.cli`) and,
optionally, `GITHUB_OUTPUT` to a scratch file; with neither `$GITHUB_OUTPUT` set
the outputs are just echoed.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

# input-name -> the CLI flag it maps to (value-taking flags only)
_VALUE_FLAGS = {
    "min-speedup": "--min-speedup",
    "min-rung": "--min-rung",
    "objectives": "--objectives",
    "jobs": "--jobs",
    "budget": "--budget",
    "llm-url": "--llm-url",
    "llm-model": "--llm-model",
    "config-file": "--config-file",
}


def get_input(name: str, default: str = "") -> str:
    """Read one Action input. GitHub sets `INPUT_<UPPER>` with dashes kept; some
    setups underscore them — accept both."""
    key = "INPUT_" + name.upper()
    val = os.environ.get(key)
    if val is None:
        val = os.environ.get(key.replace("-", "_"))
    return (val if val is not None else default).strip()


def workdir() -> str:
    """Where boostopt RUNS — the checked-out repo on CI (so relative `compile-commands`
    paths resolve), else cwd."""
    return os.environ.get("GITHUB_WORKSPACE") or os.getcwd()


def artifact_dir() -> str:
    """Where the bridge WRITES its report/patches — the runner's temp area, never the
    checkout (keeps the workspace clean; `RUNNER_TEMP` is always set on GitHub runners)."""
    return os.environ.get("RUNNER_TEMP") or workdir()


def build_argv(inp=get_input) -> tuple[list[str], str, str]:
    """Map inputs → the `boostopt optimize` argv. `inp` is injectable for testing.
    Returns (argv, patches_dir, mode). Raises SystemExit on a missing required input."""
    db = inp("compile-commands")
    if not db:
        raise SystemExit("boostopt-action: the 'compile-commands' input is required "
                         "(path to compile_commands.json)")

    argv = ["optimize", "-p", db, "--json", "--no-daemon"]

    # Scope to the PR's changed translation units. Empty base-ref → working tree vs HEAD.
    base = inp("base-ref")
    argv += ["--changed", base] if base else ["--changed"]

    model = inp("model", "rules")
    if model:
        argv += ["--model", model]

    for name, flag in _VALUE_FLAGS.items():
        v = inp(name)
        if v:
            argv += [flag, v]

    if inp("metamorphic", "false").lower() == "true":
        argv.append("--metamorphic")

    # The CI exit policy — the whole reason this runs as a check. Default 'none' = advisory.
    argv += ["--fail-on", inp("fail-on", "none") or "none"]

    # 'suggest'/'pr' delivery needs the patch series on disk for step 3 to post.
    mode = inp("mode", "comment") or "comment"
    patches_dir = ""
    if mode in ("suggest", "pr"):
        patches_dir = os.path.join(artifact_dir(), "boostopt-patches")
        argv += ["--emit-patches", patches_dir]

    extra = inp("extra-args")
    if extra:
        argv += shlex.split(extra)

    return argv, patches_dir, mode


def compute_outputs(report, *, mode: str, patches_dir: str, report_path: str) -> dict:
    """Reduce the verdict report (the parsed `--json` codebase payload — a list of
    {file, error, verdicts, skips}) to the Action's outputs."""
    verdicts = [v for f in report for v in (f.get("verdicts") or [])]
    accepted = [v for v in verdicts if v.get("accepted")]
    findings = len(accepted)
    applied = sum(1 for v in accepted if v.get("applied"))   # step-3 posting updates this
    return {
        "status": "found" if findings else "clean",
        "findings": findings,
        "applied": applied,
        "regressions": 0,          # planned — needs the baseline-diff feature
        "report-json": report_path,
        "patches": patches_dir if (patches_dir and os.path.isdir(patches_dir)) else "",
    }


def write_outputs(outputs: dict) -> None:
    """Append `name=value` lines to `$GITHUB_OUTPUT`; off-CI, echo them instead."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        for k, v in outputs.items():
            print(f"[output] {k}={v}", file=sys.stderr)
        return
    with open(path, "a", encoding="utf-8") as f:
        for k, v in outputs.items():
            f.write(f"{k}={v}\n")


def main() -> int:
    argv, patches_dir, mode = build_argv()
    boostopt = shlex.split(os.environ.get("BOOSTOPT_BIN", "boostopt"))
    report_path = os.path.join(artifact_dir(), "boostopt-report.json")

    proc = subprocess.run(boostopt + argv, cwd=workdir(),
                          capture_output=True, text=True)
    sys.stderr.write(proc.stderr)          # boostopt's status/progress goes to the CI log

    raw = proc.stdout
    try:
        report = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError:
        report = None

    if report is None or not isinstance(report, list):
        sys.stderr.write("boostopt-action: could not parse boostopt --json output; "
                         "treating as an error.\n")
        write_outputs({"status": "error", "findings": 0, "applied": 0,
                       "regressions": 0, "report-json": "", "patches": ""})
        return proc.returncode or 2

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(raw)
    outputs = compute_outputs(report, mode=mode, patches_dir=patches_dir,
                              report_path=report_path)
    write_outputs(outputs)

    # Deliver the findings (step 3). Isolated so a posting failure never changes the
    # check result — that was already decided by boostopt's exit code (--fail-on).
    blocking = get_input("fail-on", "none") == "any" and outputs["findings"] > 0
    try:
        _post(report, mode=mode, blocking=blocking)
    except Exception as e:                       # never let delivery break the build
        sys.stderr.write(f"boostopt-action: delivery step failed (non-fatal): {e}\n")

    sys.stderr.write(
        f"boostopt-action: {outputs['findings']} verified optimization(s) · "
        f"status={outputs['status']} · fail-on exit={proc.returncode}\n")
    return proc.returncode          # verbatim → --fail-on drives the check


def _post(report, *, mode: str, blocking: bool) -> None:
    """Render + post the PR comment / suggestions per `mode`. No-ops off a PR."""
    if mode not in ("comment", "suggest", "pr"):
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import comment as _c
    import gh as _gh

    root = workdir()
    _gh.post_or_update_summary(_c.render_comment(report, repo_root=root, blocking=blocking),
                               _c.MARKER)
    if mode in ("suggest", "pr"):
        _gh.post_suggestions(_c.extract_suggestions(report, repo_root=root))
    if mode == "pr":
        sys.stderr.write("boostopt-action: mode 'pr' (open a follow-up PR) is not yet "
                         "implemented — posted the summary + suggestions instead.\n")


if __name__ == "__main__":
    sys.exit(main())
