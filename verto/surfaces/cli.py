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
import sys

# NOTE: engine imports (Engine/Config) are deliberately LAZY — see _run_command.
# They pull in libclang (~0.5s), and the daemon thin-client path must not pay that
# just to connect. Only the in-process execution path imports them.


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
    return cfg


def _render_human(verdicts: list) -> None:
    if not verdicts:
        print("  no verified opportunity found.")
        return
    for v in verdicts:
        name = v.candidate.transform.name if v.candidate else "?"
        mark = "\033[32mACCEPT\033[0m" if v.accepted else f"\033[31mREJECT\033[0m ({v.reason})"
        print(f"\n  {name}  →  {mark}")
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
            if w.sanitizer == "skipped(fast)" and v.accepted:
                print("    \033[33m⚠ UNSOUND (--fast): sanitizer skipped — "
                      "diff-tested only, not memory-safety verified\033[0m")
        if v.performance:
            d = v.performance.vector.get("p50_delta_pct")
            print(f"    performance: p50 {v.performance.vector.get('p50')} ms "
                  f"({'-%.1f%%' % d if d else 'n/a'})  pareto={v.performance.pareto_pass}")


def _render_json(verdicts: list) -> None:
    def enc(o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return getattr(o, "name", str(o))       # render a Transform as its name
    print(json.dumps([enc(v) for v in verdicts], default=enc, indent=2))


def _render_codebase(results: list) -> None:
    GRN, RED, DIM, RST = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
    n_files = n_cand = n_acc = 0
    print(f"\n  codebase scan — {len(results)} translation unit(s)")
    for path, verdicts, err in results:
        rel = os.path.relpath(path)
        if err:
            print(f"\n  {rel}\n    {RED}error{RST}: {err}")
            continue
        if not verdicts:
            print(f"\n  {rel}\n    {DIM}no verified opportunity{RST}")
            continue
        n_files += 1
        print(f"\n  {rel}")
        for v in verdicts:
            n_cand += 1
            name = v.candidate.transform.name if v.candidate else "?"
            fn = getattr(v.candidate.transform, "target_func", None) if v.candidate else None
            if v.accepted:
                n_acc += 1
                d = v.performance.vector.get("p50_delta_pct") if v.performance else None
                delta = f"  (−{d:.1f}%)" if d else ""
                print(f"    {GRN}ACCEPT{RST}  {name} [{fn}]{delta}")
            else:
                print(f"    {RED}REJECT{RST}  {name} [{fn}]  ({v.reason})")
    print(f"\n  {'-' * 60}")
    print(f"  {n_acc} accepted / {n_cand} candidate(s) across {n_files} file(s) with opportunities")


def _render_codebase_json(results: list) -> None:
    def enc(o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return getattr(o, "name", str(o))
    payload = [{"file": f, "error": err, "verdicts": v} for f, v, err in results]
    print(json.dumps(payload, default=enc, indent=2))


def _codebase_exit(results: list) -> int:
    if any(v.accepted for _, vs, _ in results for v in vs):
        return 0
    if any(vs for _, vs, _ in results):
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

    out = sp.add_argument_group("output & execution")
    if apply:
        out.add_argument("--apply", action="store_true",
                         help="write accepted changes back to source (PLANNED — not yet implemented)")
    out.add_argument("--json", action="store_true", help="machine-readable output")
    out.add_argument("--no-daemon", action="store_true",
                     help="run in-process even if a verto daemon is available")
    out.add_argument("--config-file", metavar="FILE",
                     help="project config (default .verto.toml)")
    out.add_argument("--profile", metavar="FILE",
                     help="profile data to guide hotspot selection (PLANNED — not yet consumed)")


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


def _parser() -> argparse.ArgumentParser:
    from . import _help
    fmt = _HelpFormatter
    p = argparse.ArgumentParser(prog="verto", description=_help.DESCRIPTION, usage=_help.USAGE_MAIN,
                                epilog=_help.MAIN_EPILOG, formatter_class=fmt)
    p.add_argument("-V", "--version", action="version", version=f"verto {_version()}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>", title="commands")

    a = sub.add_parser("analyze", help=_help.ANALYZE_DESC, description=_help.ANALYZE_DESC,
                       usage=_help.USAGE_ANALYZE, epilog=_help.ANALYZE_EPILOG, formatter_class=fmt)
    _common(a)

    o = sub.add_parser("optimize", help=_help.OPTIMIZE_DESC, description=_help.OPTIMIZE_DESC,
                       usage=_help.USAGE_OPTIMIZE, epilog=_help.OPTIMIZE_EPILOG, formatter_class=fmt)
    _common(o, apply=True)

    sub.add_parser("report", help=_help.REPORT_DESC, description=_help.REPORT_DESC,
                   usage="verto report", formatter_class=fmt)
    s = sub.add_parser("serve", help=_help.SERVE_DESC, description=_help.SERVE_DESC,
                       usage=_help.USAGE_SERVE, epilog=_help.SERVE_EPILOG, formatter_class=fmt)
    s.add_argument("--stop", action="store_true", help="stop a running daemon")
    return p


def _run_command(args) -> int:
    """Execute a parsed command in THIS process, printing to stdout/stderr."""
    from ..engine.api import Engine
    try:
        if args.cmd == "report":
            print(json.dumps(Engine().report(), indent=2))
            return 0

        engine = Engine(_build_config(args))

        # --- codebase mode: path is a compile_commands.json / a dir holding one ---
        cc = _codebase_db(args)
        if cc is not None:
            results = engine.optimize_codebase(cc, apply=getattr(args, "apply", False))
            (_render_codebase_json if args.json else _render_codebase)(results)
            return _codebase_exit(results)

        # --- single file (optionally with flags looked up from -p's db) ---
        if not args.path:
            raise ValueError("no target: give a source <path>, or --all with -p")
        build = _single_file_flags(args)
        if args.cmd == "analyze":
            verdicts = engine.analyze(args.path, build=build)
        else:
            verdicts = engine.optimize(args.path, apply=args.apply, build=build)

        (_render_json if args.json else _render_human)(verdicts)
        return _exit_code(verdicts)
    except (ValueError, NotImplementedError) as e:
        print(f"verto: error: {e}", file=sys.stderr)
        return 2


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
