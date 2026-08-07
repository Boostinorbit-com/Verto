"""The argparse parser — command/flag definitions, the styled help formatter, and
the top-level cheat-sheet generated FROM the flags (so it can't drift from
`boostopt optimize --help`). Per-flag help lives next to each flag; only framing prose
lives in `_help.py`.
"""
from __future__ import annotations

import argparse
import re


def _common(sp, *, apply: bool = False) -> None:
    """Flags shared by analyze/optimize, grouped by concern for a readable --help."""
    tgt = sp.add_argument_group("target selection")
    tgt.add_argument("path", nargs="?",
                     help="a source file (single-file mode); omit with --all")
    tgt.add_argument("-p", "--compile-commands", dest="compile_commands", metavar="DB",
                     help="compile_commands.json, or a build dir containing one — "
                          "the compilation database (canonical source of flags)")
    tgt.add_argument("--all", action="store_true",
                     help="optimize every translation unit in the database (requires -p)")

    pol = sp.add_argument_group("verification policy")
    pol.add_argument("--min-rung", type=int, metavar="N",
                     help="correctness rung required to accept (default 3 = sanitizers)")
    pol.add_argument("--fast", action="store_true",
                     help="skip the Rung-3 sanitizer for speed (UNSOUND — verdict is labeled)")
    pol.add_argument("--offline", action="store_true",
                     help="use the deterministic rule proposer (no model / API)")
    pol.add_argument("--model", metavar="NAME",
                     help="proposer model (frontier | local | rules)")

    if apply:
        ap = sp.add_argument_group("apply")
        ap.add_argument("--apply", action="store_true",
                        help="write accepted, sound changes to source")
        ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="preview only — never write (the default)")
        ap.add_argument("--backup", action="store_true",
                        help="save <file>.bak before overwriting")
        ap.add_argument("--force", action="store_true",
                        help="apply even an unsound (--fast) result")
        ap.add_argument("--export", metavar="FILE",
                        help="write accepted diffs to FILE instead of applying")
        ap.add_argument("--apply-from", metavar="FILE", dest="apply_from",
                        help="apply a diff set written by --export (uses `patch`)")
        ap.add_argument("--emit-patches", metavar="DIR", dest="emit_patches",
                        help="2C: write a ranked, git-apply-able patch series + REPORT.md to DIR")

    tune = sp.add_argument_group("selection & tuning")
    tune.add_argument("--transforms", metavar="GLOB",
                      help="only run transforms matching GLOB (comma-separated globs)")
    tune.add_argument("--list-transforms", action="store_true", dest="list_transforms",
                      help="list the available transforms and exit")
    tune.add_argument("--min-speedup", type=float, metavar="PCT", dest="min_speedup",
                      help="reject gains below PCT%% (default 2)")
    tune.add_argument("--changed", nargs="?", const="", metavar="REF",
                      help="codebase mode: only verify TUs git changed vs REF (default: working tree)")
    tune.add_argument("--jobs", "-j", type=int, metavar="N",
                      help="codebase mode: process N translation units in parallel (default 1)")
    tune.add_argument("--reps", type=int, metavar="N", help="benchmark repetitions (upper bound when adaptive)")
    tune.add_argument("--reps-min", type=int, metavar="N", dest="reps_min",
                      help="adaptive floor — escalate to --reps only if the result is borderline (default 5)")
    tune.add_argument("--no-adaptive", action="store_true", dest="no_adaptive",
                      help="always run the full --reps (disable early-stop when the gain is unambiguous)")
    tune.add_argument("--fp-tolerance", type=float, metavar="REL", dest="fp_tolerance",
                      help="accept FP output within this relative tolerance (item #1b; default 0 = exact)")
    tune.add_argument("--fuzz", type=int, metavar="N", dest="fuzz_inputs",
                      help="seeded fuzzed correctness inputs beyond the fixed edge cases (default 1000)")
    tune.add_argument("--seed", type=int, metavar="N",
                      help="PRNG seed for fuzzed inputs — deterministic, reproducible verdicts (default 0)")
    tune.add_argument("--objectives", metavar="LIST",
                      help="comma-separated Pareto objectives to gate on (e.g. p50,p99,peak_memory)")
    tune.add_argument("--config", metavar="KEY=VAL", action="append",
                      help="inline config override (repeatable)")
    tune.add_argument("--verify-setup", action="store_true", dest="verify_setup",
                      help="check the toolchain (clang, sanitizers, ccache, linker) and exit")

    out = sp.add_argument_group("output & execution")
    out.add_argument("--diff", action="store_true",
                     help="print the full unified diff of each accepted change")
    out.add_argument("--json", action="store_true", help="machine-readable output")
    out.add_argument("--fail-on", metavar="WHAT", dest="fail_on", choices=["none", "any"],
                     help="#18 CI gate: force the exit code — none (always 0; findings are advisory) "
                          "| any (exit 1 if a verified optimization was found). Omit for the default "
                          "codes (0=found, 1=none, 3=all-rejected)")
    out.add_argument("--quiet", "-q", action="store_true",
                     help="only print accepted changes (and their diffs)")
    out.add_argument("--no-color", action="store_true", dest="no_color",
                     help="disable colored output")
    out.add_argument("--no-daemon", action="store_true",
                     help="run in-process even if a boostopt daemon is available")
    out.add_argument("--config-file", metavar="FILE",
                     help="project config (default .boostopt.toml)")
    out.add_argument("--profile", metavar="FILE",
                     help="real profile (perf --stdio / gprof / json / 'symbol cost') to pick the hot function")
    out.add_argument("--test-command", metavar="CMD", dest="test_command",
                     help="build+run the project's own tests to re-confirm each accepted change (exit 0 = pass)")
    out.add_argument("--test-dir", metavar="DIR", dest="test_dir",
                     help="cwd for --test-command (default: the target file's directory)")
    out.add_argument("--test-timeout", type=int, metavar="SEC", dest="test_timeout_sec",
                     help="timeout for --test-command / --bench-command runs (default 600)")
    out.add_argument("--bench-command", metavar="CMD", dest="bench_command",
                     help="2A: build+run a project bench, timed as the perf signal for functions the harness can't reach")
    out.add_argument("--bench-dir", metavar="DIR", dest="bench_dir",
                     help="cwd for --bench-command (default: the target file's directory)")
    out.add_argument("--bench-runs", type=int, metavar="N", dest="bench_runs",
                     help="2A: median-of-N timings of the bench per side (default 5)")
    out.add_argument("--build-command", metavar="CMD", dest="build_command",
                     help="2A: build step run ONCE before timing, so the bench is timed run-only (e.g. 'make')")
    out.add_argument("--ctest-dir", metavar="DIR", dest="ctest_dir",
                     help="2A-1: a CMake build dir — auto-discover the test/bench commands from ctest")
    out.add_argument("--metamorphic", action="store_true", dest="metamorphic",
                     help="2D: also run the metamorphic property rung (Rung 2) — rejects a change that breaks permutation-invariance")
    out.add_argument("--no-sandbox", action="store_true", dest="no_sandbox",
                     help="#13: run untrusted binaries WITHOUT bwrap/cgroup isolation (escape hatch; UNSAFE)")
    out.add_argument("--sandbox-mem", type=int, metavar="MB", dest="sandbox_mem",
                     help="#13: cgroup memory cap (MB) for isolated runs (default 2048)")
    out.add_argument("--budget", metavar="SPEC", dest="budget",
                     help="#12: per-run LLM spend cap — tokens ('500k'), money ('$2'), or time ('90s')")
    out.add_argument("--budget-per-hotspot", metavar="SPEC", dest="budget_per_hotspot",
                     help="#12: per-hotspot LLM spend sub-limit (same SPEC forms as --budget)")
    out.add_argument("--llm-model", metavar="NAME", dest="llm_model",
                     help="#10: LLM name for --model local|frontier (default qwen2.5-coder:7b)")
    out.add_argument("--llm-url", metavar="URL", dest="llm_base_url",
                     help="#10: LLM host base URL (default http://127.0.0.1:11434 — local Ollama)")
    out.add_argument("--candidates", type=int, metavar="N", dest="candidates",
                     help="#11: ask the LLM for N rewrites per hotspot; gate each, keep the best (default 1)")


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Verbatim description/epilog (so our styled prose renders as written), plus
    bold-uppercase section headings and a clean gh-style USAGE block — instead of
    argparse's `usage: prog [-h] [-V] ...` boilerplate."""
    def start_section(self, heading):
        if heading:
            from .. import _help
            heading = _help.section(heading)
        super().start_section(heading)

    def _format_usage(self, usage, actions, groups, prefix):
        from .. import _help
        lines = [ln.strip() for ln in (usage or "").strip().splitlines() if ln.strip()]
        body = "\n".join("  " + ln for ln in lines) if lines else "  boostopt <command>"
        return f"{_help.section('usage')}\n{body}\n\n"


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("boostopt")
    except Exception:
        return "0.1.0"


def _flag_spec(action) -> str:
    """`-p, --compile-commands DB` / `--apply` / `<path>` — the invocation form."""
    if not action.option_strings:
        return f"<{action.dest}>"
    opts = ", ".join(action.option_strings)
    no_value = (argparse._StoreTrueAction, argparse._StoreFalseAction,
                argparse._StoreConstAction, argparse._HelpAction)
    if isinstance(action, no_value):
        return opts
    return f"{opts} {action.metavar or action.dest.upper()}"


def _cheatsheet(sp) -> str:
    """Build the top-level COMMON OPTIONS block FROM the parser — flag names AND
    their descriptions come from the single source (the flags' own `help=`), so it
    can never drift from `boostopt optimize --help`. Descriptions are trimmed of any
    parenthetical for compactness."""
    from .. import _help
    lines = [f"{_help.section('common options')} "
             f"{_help.dim('(shared by analyze & optimize; `boostopt optimize --help` for full detail)')}"]
    for group in sp._action_groups:
        acts = [a for a in group._group_actions if not isinstance(a, argparse._HelpAction)]
        if not acts or group.title in ("options", "positional arguments"):
            continue
        lines.append("  " + _help.bold(group.title))
        for a in acts:
            desc = re.sub(r"\s*\([^()]*\)\s*$", "", a.help or "")   # drop only a TRAILING (…)
            desc = desc.replace("%%", "%").strip()
            lines.append(f"    {_flag_spec(a):26} {_help.dim(desc)}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    from .. import _help
    fmt = _HelpFormatter
    p = argparse.ArgumentParser(prog="boostopt", description=_help.DESCRIPTION, usage=_help.USAGE_MAIN,
                                formatter_class=fmt)
    p.add_argument("-V", "--version", action="version", version=f"boostopt {_version()}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>", title="commands")

    a = sub.add_parser("analyze", help=_help.ANALYZE_DESC, description=_help.ANALYZE_DESC,
                       usage=_help.USAGE_ANALYZE, epilog=_help.ANALYZE_EPILOG, formatter_class=fmt)
    _common(a)

    o = sub.add_parser("optimize", help=_help.OPTIMIZE_DESC, description=_help.OPTIMIZE_DESC,
                       usage=_help.USAGE_OPTIMIZE, epilog=_help.OPTIMIZE_EPILOG, formatter_class=fmt)
    _common(o, apply=True)

    # top-level epilog = a cheat-sheet GENERATED from the optimize flags + TAIL,
    # so the flag list & descriptions can't drift (the drift `--apply` just hit).
    p.epilog = f"{_cheatsheet(o)}\n\n{_help.MAIN_EPILOG_TAIL}"

    sub.add_parser("report", help=_help.REPORT_DESC, description=_help.REPORT_DESC,
                   usage="boostopt report", formatter_class=fmt)

    ini = sub.add_parser("init", help=_help.INIT_DESC, description=_help.INIT_DESC,
                         usage=_help.USAGE_INIT, formatter_class=fmt)
    ini.add_argument("--model", metavar="NAME",
                     help="local model to record as the project default (default: config llm_model)")
    ini.add_argument("--pull", action="store_true",
                     help="pull the model now via Ollama if missing (may download GBs)")
    ini.add_argument("--global", dest="global_", action="store_true",
                     help="also scaffold machine-wide defaults at ~/.config/boostopt/config.toml")

    s = sub.add_parser("serve", help=_help.SERVE_DESC, description=_help.SERVE_DESC,
                       usage=_help.USAGE_SERVE, epilog=_help.SERVE_EPILOG, formatter_class=fmt)
    s.add_argument("--stop", action="store_true", help="stop a running daemon")
    return p
