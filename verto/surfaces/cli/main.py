"""CLI dispatch + entry point — parse argv, run the command in-process (or hand
analyze/optimize to a warm daemon), and the standalone actions (list-transforms,
verify-setup, apply-from, export). A thin client over the Engine API."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys

from .config_build import _build_config
from .parser import _parser
from .render import (_codebase_exit, _col, _exit_code, _render_codebase,
                     _render_codebase_json, _render_human, _render_json, set_color)


def _run_command(args) -> int:
    """Execute a parsed command in THIS process, printing to stdout/stderr."""
    set_color(("NO_COLOR" not in os.environ) and not getattr(args, "no_color", False))
    try:
        # --- standalone actions (no target required) ---
        if getattr(args, "list_transforms", False):
            return _list_transforms()
        if getattr(args, "verify_setup", False):
            return _verify_setup()
        if getattr(args, "apply_from", None):
            return _apply_from(args.apply_from)

        if args.cmd == "report":
            from ...engine.api import Engine
            print(json.dumps(Engine().report(), indent=2))
            return 0

        from ...engine.api import Engine
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
    from ...adapters.language.cpp.transforms import ALL
    print(_col("available transforms", "1") + ":")
    for t in ALL:
        print(f"  {t.name:28} {getattr(t, 'rationale', '')}")
    return 0


def _verify_setup() -> int:
    import shutil as sh
    from ...adapters.language.cpp.build import sanitizer_toolchain
    from ...adapters.language.cpp.build.compile import _ccache, _fast_linker
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
    from ...adapters.language.cpp import compile_db

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
    from ...adapters.language.cpp import compile_db
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
        return "", "verto: bad arguments\n", int(e.code or 2)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = _run_command(args)
    return out.getvalue(), err.getvalue(), code


def main(argv: list[str] | None = None) -> int:
    from .. import daemon

    argv = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(argv)

    # Auto-disable color when the CLIENT's stdout isn't a TTY (piped/redirected) or
    # NO_COLOR is set. Decided HERE because main() sees the real stdout — inside the
    # daemon it's a captured buffer. Inject --no-color so BOTH the in-process and the
    # forwarded-to-daemon paths render plain. (--no-color exists only on
    # analyze/optimize, which is exactly where color output happens.)
    if (hasattr(args, "no_color") and not args.no_color
            and (not sys.stdout.isatty() or "NO_COLOR" in os.environ)):
        args.no_color = True
        argv = argv + ["--no-color"]

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
