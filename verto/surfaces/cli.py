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


def _exit_code(verdicts: list[Verdict]) -> int:
    if not verdicts:
        return 1
    if any(v.accepted for v in verdicts):
        return 0
    return 3


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="verto", description="VERTO — verified performance optimizer")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("path")
        sp.add_argument("-p", "--compile-commands", dest="compile_commands")
        sp.add_argument("--profile")
        sp.add_argument("--model")
        sp.add_argument("--offline", action="store_true")
        sp.add_argument("--fast", action="store_true",
                        help="skip the Rung-3 sanitizer for speed (UNSOUND — verdict is labeled)")
        sp.add_argument("--min-rung", type=int)
        sp.add_argument("--config-file")
        sp.add_argument("--json", action="store_true")
        sp.add_argument("--no-daemon", action="store_true",
                        help="run in-process even if an verto daemon is available")

    common(sub.add_parser("analyze", help="detect + explain; writes nothing"))
    o = sub.add_parser("optimize", help="propose → verify → optionally apply")
    common(o)
    o.add_argument("--apply", action="store_true")
    sub.add_parser("report", help="read the Ledger")
    s = sub.add_parser("serve", help="run a warm daemon (skips per-call startup)")
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
        if args.cmd == "analyze":
            verdicts = engine.analyze(args.path)
        else:
            verdicts = engine.optimize(args.path, apply=args.apply)

        (_render_json if args.json else _render_human)(verdicts)
        return _exit_code(verdicts)
    except (ValueError, NotImplementedError) as e:
        print(f"verto: error: {e}", file=sys.stderr)
        return 2


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
