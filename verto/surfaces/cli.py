"""VERTO CLI — the v0 surface (a thin client over the Engine API).

Mirrors VERTO_Surfaces §3. Commands: analyze / optimize / report.
Exit codes: 0 verified change found · 1 nothing found · 2 error · 3 all rejected.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import os
import re
import sys

# NOTE: engine imports (Engine/Config) are deliberately LAZY — see _run_command.
# They pull in libclang (~0.5s), and the daemon thin-client path must not pay that
# just to connect. Only the in-process execution path imports them.


_COLOR = "NO_COLOR" not in os.environ   # verdict-render color; --no-color turns it off


def _col(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def _coerce(cur, val: str):
    """Coerce a KEY=VAL string to the type of the existing config field."""
    if isinstance(cur, bool):
        return val.lower() in ("1", "true", "yes", "on")
    if isinstance(cur, int):
        return int(val)
    if isinstance(cur, float):
        return float(val)
    if isinstance(cur, (tuple, list)):
        return tuple(x.strip() for x in val.split(",") if x.strip())
    return val


def _build_config(args):
    from ..engine.config import Config
    cfg = Config.load(getattr(args, "config_file", None))
    if getattr(args, "offline", False):
        cfg.model = "rules"
    if getattr(args, "model", None):
        cfg.model = args.model
    if getattr(args, "fast", False):
        # opt-in speed-over-soundness: skip the Rung-3 sanitizer, fewer reps.
        cfg.fast = True
        cfg.min_rung = 1
        cfg.reps_min = 3
        cfg.reps = 6
    if getattr(args, "min_rung", None) is not None:
        cfg.min_rung = args.min_rung      # explicit --min-rung still wins
    if getattr(args, "fp_tolerance", None) is not None:
        cfg.fp_tolerance = args.fp_tolerance   # FP-tolerance compare (item #1b)
    if getattr(args, "profile", None):
        cfg.profile = args.profile        # real profile drives hotspot selection (item #5)
    if getattr(args, "test_command", None):
        cfg.test_command = args.test_command   # project's own tests re-confirm changes (item #3)
    # selection & tuning knobs (config file covers the rest)
    if getattr(args, "transforms", None):
        cfg.transforms = tuple(g.strip() for g in args.transforms.split(",") if g.strip())
    if getattr(args, "min_speedup", None) is not None:
        cfg.min_speedup_pct = args.min_speedup
    if getattr(args, "reps", None) is not None:
        cfg.reps = args.reps
    if getattr(args, "fuzz_inputs", None) is not None:
        cfg.fuzz_inputs = args.fuzz_inputs     # item #7: wider seeded correctness inputs
    if getattr(args, "seed", None) is not None:
        cfg.seed = args.seed
    if getattr(args, "objectives", None):
        cfg.objectives = tuple(o.strip() for o in args.objectives.split(",") if o.strip())
    for kv in getattr(args, "config", None) or []:        # --config KEY=VAL (repeatable)
        if "=" not in kv:
            raise ValueError(f"--config expects KEY=VAL, got {kv!r}")
        k, val = (s.strip() for s in kv.split("=", 1))
        if not hasattr(cfg, k):
            raise ValueError(f"unknown config key {k!r}")
        setattr(cfg, k, _coerce(getattr(cfg, k), val))
    return cfg


def _render_human(verdicts: list, *, quiet: bool = False, show_diff: bool = False,
                  applying: bool = False) -> None:
    if not verdicts:
        if not quiet:
            print("  no verified opportunity found.")
        return
    for v in verdicts:
        if quiet and not v.accepted:
            continue
        name = v.candidate.transform.name if v.candidate else "?"
        mark = _col("ACCEPT", "32") if v.accepted else f"{_col('REJECT', '31')} ({v.reason})"
        print(f"\n  {name}  →  {mark}")
        if quiet:
            if v.diff:
                print("\n" + _indent(v.diff))
            continue
        if v.candidate:
            print(f"    rationale: {v.candidate.rationale}")
        if v.correctness:
            w = v.correctness.witness
            if w.first_divergence:
                detail = f"output differs — {w.first_divergence}"
            elif not w.build_ok:
                detail = "build failed"
            else:
                detail = w.sanitizer
            print(f"    correctness: Rung {v.correctness.rung} ({detail})")
            if getattr(v, "tests_confirmed", False):
                print(f"    {_col('✓ re-confirmed by the project’s own tests', '32')}")
            if w.sanitizer == "skipped(fast)" and v.accepted:
                print("    " + _col("⚠ UNSOUND (--fast): sanitizer skipped — "
                                    "diff-tested only, not memory-safety verified", "33"))
        if v.performance:
            d = v.performance.vector.get("p50_delta_pct")
            print(f"    performance: p50 {v.performance.vector.get('p50')} ms "
                  f"({'-%.1f%%' % d if d else 'n/a'})  pareto={v.performance.pareto_pass}")
        if v.accepted:
            if v.applied:
                print(f"    {_col('✓ applied to source', '32')}")
            elif applying:
                print(f"    {_col('⚠ not applied', '33')}: unsound (--fast) — re-run with --force")
            else:
                print("    (dry run — re-run with --apply to write this change)")
        if show_diff and v.diff:
            print("\n" + _indent(v.diff))


def _indent(text: str, pad: str = "    ") -> str:
    return "\n".join(pad + ln for ln in text.rstrip("\n").splitlines())


def _render_json(verdicts: list) -> None:
    def enc(o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return getattr(o, "name", str(o))       # render a Transform as its name
    print(json.dumps([enc(v) for v in verdicts], default=enc, indent=2))


def _render_codebase(results: list) -> None:
    n_files = n_cand = n_acc = n_applied = n_skip = 0
    skip_reasons: dict[str, int] = {}
    print(f"\n  codebase scan — {len(results)} translation unit(s)")
    for path, verdicts, err, skips in results:
        rel = os.path.relpath(path)
        if err:
            print(f"\n  {rel}\n    {_col('error', '31')}: {err}")
            continue
        if not verdicts and not skips:
            print(f"\n  {rel}\n    {_col('no opportunity found', '2')}")
            continue
        if verdicts:
            n_files += 1
        print(f"\n  {rel}")
        for v in verdicts:
            name = v.candidate.transform.name if v.candidate else "?"
            fn = getattr(v.candidate.transform, "target_func", None) if v.candidate else None
            if v.accepted:
                n_cand += 1
                n_acc += 1
                d = v.performance.vector.get("p50_delta_pct") if v.performance else None
                delta = f"  (−{d:.1f}%)" if d else ""
                tag = _col("✓ applied", "32") if v.applied else _col("ACCEPT", "32")
                n_applied += bool(v.applied)
                confirmed = _col("  ✓ tests", "32") if getattr(v, "tests_confirmed", False) else ""
                print(f"    {tag}  {name} [{fn}]{delta}{confirmed}")
            elif v.reason.startswith("skipped"):        # gate couldn't verify (item #1/#4)
                n_skip += 1
                skip_reasons[v.reason] = skip_reasons.get(v.reason, 0) + 1
                print(f"    {_col('SKIP', '33')}    {name} [{fn}]  ({v.reason})")
            else:
                n_cand += 1
                print(f"    {_col('REJECT', '31')}  {name} [{fn}]  ({v.reason})")
        for s in skips:                                  # sensor-level skips (item #4)
            n_skip += 1
            skip_reasons[s.reason] = skip_reasons.get(s.reason, 0) + 1
            print(f"    {_col('SKIP', '33')}    [{s.func}]  ({s.stage}: {s.reason})")
    print(f"\n  {'-' * 60}")
    tail = f" · {n_applied} applied" if n_applied else ""
    print(f"  {n_acc} accepted / {n_cand} candidate(s) across {n_files} file(s) "
          f"with opportunities · {n_skip} skipped{tail}")
    if skip_reasons:
        print(f"  {_col('skipped breakdown', '2')}:")
        for reason, count in sorted(skip_reasons.items(), key=lambda kv: -kv[1]):
            print(f"    {count:>3} × {reason}")


def _render_codebase_json(results: list) -> None:
    def enc(o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return getattr(o, "name", str(o))
    payload = [{"file": f, "error": err, "verdicts": v, "skips": sk}
               for f, v, err, sk in results]
    print(json.dumps(payload, default=enc, indent=2))


def _codebase_exit(results: list) -> int:
    if any(v.accepted for _, vs, _, _ in results for v in vs):
        return 0
    if any(vs for _, vs, _, _ in results):
        return 3                       # candidates found but all rejected
    return 1                           # nothing found


def _exit_code(verdicts: list[Verdict]) -> int:
    if not verdicts:
        return 1
    if any(v.accepted for v in verdicts):
        return 0
    return 3


def _common(sp, *, apply: bool = False) -> None:
    """Flags shared by analyze/optimize, grouped by concern for a readable --help.
    Per-flag help lives HERE (next to the flag) so it can't drift from behaviour;
    only framing prose lives in _help.py."""
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
    tune.add_argument("--reps", type=int, metavar="N", help="benchmark repetitions")
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
    out.add_argument("--quiet", "-q", action="store_true",
                     help="only print accepted changes (and their diffs)")
    out.add_argument("--no-color", action="store_true", dest="no_color",
                     help="disable colored output")
    out.add_argument("--no-daemon", action="store_true",
                     help="run in-process even if a verto daemon is available")
    out.add_argument("--config-file", metavar="FILE",
                     help="project config (default .verto.toml)")
    out.add_argument("--profile", metavar="FILE",
                     help="real profile (perf --stdio / gprof / json / 'symbol cost') to pick the hot function")
    out.add_argument("--test-command", metavar="CMD", dest="test_command",
                     help="build+run the project's own tests to re-confirm each accepted change (exit 0 = pass)")


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Verbatim description/epilog (so our styled prose renders as written), plus
    bold-uppercase section headings and a clean gh-style USAGE block — instead of
    argparse's `usage: prog [-h] [-V] ...` boilerplate."""
    def start_section(self, heading):
        if heading:
            from . import _help
            heading = _help.section(heading)
        super().start_section(heading)

    def _format_usage(self, usage, actions, groups, prefix):
        from . import _help
        lines = [ln.strip() for ln in (usage or "").strip().splitlines() if ln.strip()]
        body = "\n".join("  " + ln for ln in lines) if lines else "  verto <command>"
        return f"{_help.section('usage')}\n{body}\n\n"


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("verto")
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
    can never drift from `verto optimize --help`. Descriptions are trimmed of any
    parenthetical for compactness."""
    from . import _help
    lines = [f"{_help.section('common options')} "
             f"{_help.dim('(shared by analyze & optimize; `verto optimize --help` for full detail)')}"]
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
    from . import _help
    fmt = _HelpFormatter
    p = argparse.ArgumentParser(prog="verto", description=_help.DESCRIPTION, usage=_help.USAGE_MAIN,
                                formatter_class=fmt)
    p.add_argument("-V", "--version", action="version", version=f"verto {_version()}")
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
                   usage="verto report", formatter_class=fmt)
    s = sub.add_parser("serve", help=_help.SERVE_DESC, description=_help.SERVE_DESC,
                       usage=_help.USAGE_SERVE, epilog=_help.SERVE_EPILOG, formatter_class=fmt)
    s.add_argument("--stop", action="store_true", help="stop a running daemon")
    return p


def _run_command(args) -> int:
    """Execute a parsed command in THIS process, printing to stdout/stderr."""
    global _COLOR
    _COLOR = ("NO_COLOR" not in os.environ) and not getattr(args, "no_color", False)
    try:
        # --- standalone actions (no target required) ---
        if getattr(args, "list_transforms", False):
            return _list_transforms()
        if getattr(args, "verify_setup", False):
            return _verify_setup()
        if getattr(args, "apply_from", None):
            return _apply_from(args.apply_from)

        if args.cmd == "report":
            from ..engine.api import Engine
            print(json.dumps(Engine().report(), indent=2))
            return 0

        from ..engine.api import Engine
        engine = Engine(_build_config(args))
        do_apply = bool(getattr(args, "apply", False) and not getattr(args, "dry_run", False))
        backup = bool(getattr(args, "backup", False))
        force = bool(getattr(args, "force", False))
        export = getattr(args, "export", None)

        # --- codebase mode: path is a compile_commands.json / a dir holding one ---
        cc = _codebase_db(args)
        if cc is not None:
            results = engine.optimize_codebase(
                cc, apply=do_apply, backup=backup, force=force,
                changed=getattr(args, "changed", None),
                jobs=getattr(args, "jobs", None) or 1)
            if export:
                return _export([v for _, vs, _, _ in results for v in vs], export)
            (_render_codebase_json if args.json else _render_codebase)(results)
            return _codebase_exit(results)

        # --- single file (optionally with flags looked up from -p's db) ---
        if not args.path:
            raise ValueError("no target: give a source <path>, or --all with -p")
        build = _single_file_flags(args)
        if args.cmd == "analyze":
            verdicts = engine.analyze(args.path, build=build)
        else:
            verdicts = engine.optimize(args.path, apply=do_apply, build=build,
                                       backup=backup, force=force)
        if export:
            return _export(verdicts, export)
        if args.json:
            _render_json(verdicts)
        else:
            _render_human(verdicts, quiet=bool(getattr(args, "quiet", False)),
                          show_diff=bool(getattr(args, "diff", False)), applying=do_apply)
        return _exit_code(verdicts)
    except (ValueError, NotImplementedError) as e:
        print(f"verto: error: {e}", file=sys.stderr)
        return 2


def _list_transforms() -> int:
    from ..adapters.transforms import ALL
    print(_col("available transforms", "1") + ":")
    for t in ALL:
        print(f"  {t.name:28} {getattr(t, 'rationale', '')}")
    return 0


def _verify_setup() -> int:
    import shutil as sh
    from ..adapters.language.cpp.build import _ccache, _fast_linker, sanitizer_toolchain
    san = sanitizer_toolchain()
    rows = [
        ("clang++", sh.which("clang++"), True),
        ("g++", sh.which("g++"), True),
        ("sanitizers (Rung 3)", f"{san[0]} {san[1]}" if san else None, True),
        ("libclang (python)", "ok" if _has_libclang() else None, True),
        ("ccache", (_ccache() or [None])[0], False),
        ("fast linker", " ".join(_fast_linker("clang++")) or "default ld", False),
    ]
    print(_col("toolchain", "1") + ":")
    ok = True
    for name, val, required in rows:
        mark = _col("✓", "32") if val else _col("✗", "31")
        print(f"  {mark} {name:22} {val or 'MISSING'}")
        ok = ok and (bool(val) or not required)
    return 0 if ok else 2


def _has_libclang() -> bool:
    try:
        import clang.cindex  # noqa: F401
        return True
    except Exception:
        return False


def _apply_from(path: str) -> int:
    import shutil as sh
    import subprocess
    if not os.path.exists(path):
        print(f"verto: error: no such file: {path}", file=sys.stderr)
        return 2
    if not sh.which("patch"):
        print("verto: error: --apply-from needs the `patch` tool on PATH", file=sys.stderr)
        return 2
    r = subprocess.run(["patch", "-p1", "--backup", "-i", path])
    if r.returncode == 0:
        print(f"  applied diffs from {path}")
    return 0 if r.returncode == 0 else 2


def _export(verdicts: list, path: str) -> int:
    diffs = [v.diff for v in verdicts if v.accepted and v.diff]
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(diffs))
    print(f"  wrote {len(diffs)} accepted diff(s) to {path}")
    return 0 if diffs else 1


def _codebase_db(args) -> str | None:
    """Resolve a compile_commands.json for a whole-codebase run, or None for
    single-file mode. Canonical form: `-p <db> --all`. Also accepted: `-p <db>`
    with no source file, or a directory/.json given as the positional path."""
    from ..adapters.language.cpp import compile_db

    def _resolve(src: str) -> str:
        db = compile_db.find(src)
        if db is None:
            raise ValueError(f"no compile_commands.json found at {src}")
        return str(db)

    if getattr(args, "all", False):                    # explicit whole-codebase
        src = args.compile_commands or args.path
        if not src:
            raise ValueError("--all requires -p/--compile-commands DB (the compilation database)")
        return _resolve(src)
    if args.compile_commands and not args.path:        # `-p <db>` alone → whole codebase
        return _resolve(args.compile_commands)
    p = args.path                                      # convenience: dir/.json as the path
    if p and (p.endswith(".json") or os.path.isdir(p)) and compile_db.find(p):
        return str(compile_db.find(p))
    return None


def _single_file_flags(args) -> dict | None:
    """When `-p` is given with a single source file, look up that file's flags in
    the compile_commands.json so the one file parses/builds like the real project."""
    cc = getattr(args, "compile_commands", None)
    if not cc:
        return None
    from ..adapters.language.cpp import compile_db
    want = os.path.abspath(args.path)
    for tu in compile_db.load(cc):
        if os.path.abspath(tu.file) == want:
            return {"parse_flags": tu.flags, "compile_flags": tu.flags}
    return None


def handle_argv(argv: list[str], cwd: str | None = None) -> tuple[str, str, int]:
    """Run a command for the daemon: resolve paths against the CLIENT's cwd and
    capture output so it can be shipped back over the socket."""
    if cwd:
        os.chdir(cwd)
    out, err = io.StringIO(), io.StringIO()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:                # argparse error/-h: report, don't kill the daemon
        return "", f"verto: bad arguments\n", int(e.code or 2)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = _run_command(args)
    return out.getvalue(), err.getvalue(), code


def main(argv: list[str] | None = None) -> int:
    from . import daemon

    argv = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(argv)

    if args.cmd == "serve":
        return daemon.serve(stop=args.stop)

    # thin-client fast path: hand analyze/optimize to a warm daemon if one is up
    if args.cmd in ("analyze", "optimize") and not args.no_daemon:
        resp = daemon.try_client(argv)
        if resp is not None:
            out, err, code = resp
            sys.stdout.write(out)
            sys.stderr.write(err)
            return code

    return _run_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
