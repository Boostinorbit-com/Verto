"""CLI dispatch + entry point — parse argv, run the command in-process (or hand
analyze/optimize to a warm daemon), and the standalone actions (list-transforms,
verify-setup, apply-from, export). A thin client over the Engine API."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys

from .config_build import _build_config
from .parser import _parser
from .render import (_codebase_exit, _col, _exit_code, _fail_on_exit,
                     _render_codebase, _render_codebase_json, _render_human,
                     _render_json, set_color)


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

        if args.cmd == "init":
            return _init(model=getattr(args, "model", None), pull=getattr(args, "pull", False),
                         set_global=getattr(args, "global_", False),
                         install_ollama=getattr(args, "install_ollama", False))

        if args.cmd == "demo":
            return _demo(keep=getattr(args, "keep", False))

        if args.cmd == "report":
            from ...engine.api import Engine
            print(json.dumps(Engine().report(), indent=2))
            return 0

        cfg = _build_config(args)
        if getattr(cfg, "model", "") == "hosted":       # PREMIUM: runs on our server, not locally
            return _run_hosted(args, cfg)
        from ...engine.api import Engine
        engine = Engine(cfg)
        do_apply = bool(getattr(args, "apply", False) and not getattr(args, "dry_run", False))
        backup = bool(getattr(args, "backup", False))
        force = bool(getattr(args, "force", False))
        export = getattr(args, "export", None)

        # --- codebase mode: path is a compile_commands.json / a dir holding one ---
        cc = _codebase_db(args)
        if cc is not None:
            # live per-TU progress (to stderr, so --json on stdout stays clean); off when --quiet
            quiet = bool(getattr(args, "quiet", False))
            progress = None if quiet else _codebase_progress
            results = engine.optimize_codebase(
                cc, apply=do_apply, backup=backup, force=force,
                changed=getattr(args, "changed", None),
                jobs=getattr(args, "jobs", None) or 1, on_done=progress)
            if export:
                return _export([v for _, vs, _, _ in results for v in vs], export)
            if getattr(args, "emit_patches", None):
                _emit_patches(results, args.emit_patches)
            if args.json:
                _render_codebase_json(results)
            else:
                _render_codebase(results, show_diff=bool(getattr(args, "diff", False)))
            fail_on = getattr(args, "fail_on", None)
            if fail_on:
                accepted = any(v.accepted for _, vs, _, _ in results for v in vs)
                return _fail_on_exit(fail_on, accepted=accepted)
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
        if getattr(args, "emit_patches", None):
            _emit_patches(verdicts, args.emit_patches, single_file=args.path)
        if args.json:
            _render_json(verdicts)
        else:
            _render_human(verdicts, quiet=bool(getattr(args, "quiet", False)),
                          show_diff=bool(getattr(args, "diff", False)), applying=do_apply)
        fail_on = getattr(args, "fail_on", None)
        if fail_on:
            return _fail_on_exit(fail_on, accepted=any(v.accepted for v in verdicts))
        return _exit_code(verdicts)
    except (ValueError, NotImplementedError) as e:
        print(f"boostopt: error: {e}", file=sys.stderr)
        return 2


def _run_hosted(args, cfg) -> int:
    """PREMIUM (`--model hosted`): run the optimization on BOOSTOPT's server, then render its verdicts
    with the normal renderer (so it looks identical to a local run). Single-file only for now."""
    from ..hosted_client import run as hosted_run
    if _codebase_db(args) is not None:
        raise ValueError("--model hosted: single-file only for now (codebase mode stays local)")
    if not args.path:
        raise ValueError("no target: give a source <path>")
    do_apply = bool(getattr(args, "apply", False) and not getattr(args, "dry_run", False))
    # SAFE preferences forwarded to the server — it only ever tightens the check with these, never
    # weakens it (min-speedup can only rise, metamorphic only turns on, candidates is clamped).
    options = {"min_speedup_pct": getattr(cfg, "min_speedup_pct", None),
               "metamorphic": bool(getattr(cfg, "metamorphic", False)),
               "candidates": getattr(cfg, "candidates", None)}
    verdicts = hosted_run(args.path, url=cfg.hosted_url, token=cfg.boostopt_token, apply=do_apply,
                          backup=bool(getattr(args, "backup", False)), options=options,
                          timeout=getattr(cfg, "llm_timeout_sec", 300))
    export = getattr(args, "export", None)
    if export:                                           # --export: same as the local path
        return _export(verdicts, export)
    if getattr(args, "emit_patches", None):              # --emit-patches: reuse the server's diffs
        _emit_patches(verdicts, args.emit_patches, single_file=args.path)
    if getattr(args, "json", False):
        _render_json(verdicts)
    else:
        _render_human(verdicts, quiet=bool(getattr(args, "quiet", False)),
                      show_diff=bool(getattr(args, "diff", False)), applying=do_apply)
    fail_on = getattr(args, "fail_on", None)
    if fail_on:
        return _fail_on_exit(fail_on, accepted=any(v.accepted for v in verdicts))
    return _exit_code(verdicts)


def _codebase_progress(i: int, total: int, file: str, verdicts: list,
                       err: str | None, skips: list) -> None:
    """One line per TU as it finishes — so a big `--all` run reports live instead of
    going silent. Goes to STDERR (keeps stdout/--json clean)."""
    base = os.path.basename(file)
    if err:
        status = _col("error", "31")
    elif any(v.accepted for v in verdicts):
        n = sum(v.accepted for v in verdicts)
        status = _col(f"✓ {n} win" + ("s" if n > 1 else ""), "32")
    elif skips:
        status = _col(f"{len(skips)} skipped", "33")
    else:
        status = _col("no opportunity", "2")
    w = len(str(total))
    print(f"  [{i:>{w}}/{total}] {base:<32} {status}", file=sys.stderr, flush=True)


def _emit_patches(results, out_dir: str, *, single_file: str | None = None) -> None:
    from ..patches import emit_patches
    n, report = emit_patches(results, out_dir, single_file=single_file)
    # STDERR: this is a status line, and it must not land on stdout ahead of --json
    # (the CI entrypoint parses stdout as the verdict report).
    print(_col(f"→ wrote {n} verified patch(es) + REPORT.md to {out_dir}/", "32"),
          file=sys.stderr)


def _prov_emit(msg: str, *, ok: bool = False, warn: bool = False, hint: str = "") -> None:
    """Printer handed to `provision.ensure_local_model` — the runtime layer decides *what* to
    say, this decides how it looks. Hints stay uncolored so the ! / ✓ carries the signal."""
    body = _col(msg, "32") if ok else _col(msg, "33") if warn else msg
    print(body + (f" — {hint}" if hint else ""))


def _init(*, model: str | None = None, pull: bool = False, set_global: bool = False,
          install_ollama: bool = False, root: str = ".") -> int:
    """`boostopt init` — create the `.boostopt/` performance workspace (like `git init`) and
    prepare the local model. Idempotent; safe to re-run."""
    from ...engine import workspace
    from ...engine.config import Config
    from ...runtime import provision

    cfg = Config.load()
    requested = model or cfg.llm_model
    host = cfg.llm_base_url

    info = workspace.init(root, model=requested, host=host)
    added_gi = workspace.gitignore_add(root)

    verb = "already initialized" if info["existed"] else "initialized"
    print(_col(f"✓ BOOSTOPT workspace {verb}", "32") + f" at {info['workspace']}/")
    print("  ledger     .boostopt/ledger.jsonl   (every accept/reject: transform, rung, Δ)")
    print("  baselines  .boostopt/baselines/     (regression floor — filled as you optimize)")
    if added_gi:
        print("  gitignore  added `.boostopt/`")

    # Model prep — this is where `boostopt2.5-coder:7b` gets BUILT (pip can't: wheels run no
    # install-time code, and nobody wants a multi-GB pip install). Detect + report by default;
    # --pull opts into the base download. Whatever it settles on is what the configs below
    # record, so a project is never left pointing at a model that isn't there.
    prov = provision.ensure_local_model(host, requested, pull=pull, install=install_ollama,
                                        emit=_prov_emit)
    mdl = prov.model

    # INTENT vs REALITY — the two must not be conflated:
    #   .boostopt.toml (committed, shared)  → what the project WANTS: `requested`, always.
    #   .boostopt/model (git-ignored, local) → what this machine actually HAS: `prov.model`.
    # Writing a fallback into the committed file would encode one developer's transient local
    # state into the team's config — and worse, it's self-perpetuating: Config.load reads it back,
    # so the next `init --pull` would request the fallback and never build the real model again.
    recorded = info["model"].get("model")
    if recorded != mdl and recorded in (requested, provision.base_model(requested), None):
        # The pointer is init's own bookkeeping, so it may follow reality — including upgrading a
        # stale value from a run that fell back, or from before a rename. A deliberate third-party
        # choice (`llama3:8b`) is never touched.
        workspace.write_model(info["workspace"], model=mdl, host=host)
        if recorded is not None and recorded != mdl:
            print(f"  model      local pointer updated: {recorded} → {mdl}")

    if workspace.write_starter_config(root, model=requested, host=host):
        print("  config     wrote starter .boostopt.toml (committed team config)")
    if set_global:
        gp = workspace.write_global_config(model=requested, host=host)
        print("  global     machine-wide defaults at " + str(gp))
    if not prov.ready:
        print(_col(f"  note       config asks for '{requested}', which isn't built on this machine"
                   f" — `boostopt init --pull` fixes it", "33"))

    print("\n  ready → try " + _col("boostopt optimize <file>", "1"))
    return 0



def _demo(*, keep: bool = False) -> int:
    """`boostopt demo` — run the full pipeline on a bundled sample, with no setup at all.

    The quickstart used to point at `examples/packet_stats.cpp`, a path that exists in the repo
    and NOT in the wheel — so the first command a pip user typed failed. This ships its own
    source (boostopt/examples/), copies it somewhere writable, and optimizes it with the
    deterministic rule proposer: no model, no API key, no Ollama. Just clang++.
    """
    import shutil as sh
    import tempfile
    from pathlib import Path

    from ...examples import DEMO_NAME, DEMO_SOURCE

    from ...engine.api import Engine
    from ...engine.config import Config

    if not _has_libclang() or sh.which("clang++") is None:
        print(_col("  ! demo needs clang++ (and libclang)", "33")
              + " — run `boostopt analyze --verify-setup` to see what's missing")
        return 2

    out = Path(tempfile.mkdtemp(prefix="boostopt-demo-"))
    target = out / DEMO_NAME
    target.write_text(DEMO_SOURCE, encoding="utf-8")

    print(_col("BOOSTOPT demo", "1") + f" — optimizing {target}")
    print(_col("  rule proposer (--offline): no model, no key. Real compile, differential test,"
               " sanitizers, benchmark.\n", "2"))
    cfg = Config()
    cfg.model = "rules"                      # deterministic: a demo must not need a model
    verdicts = Engine(cfg).optimize(str(target), apply=True)
    _render_human(verdicts, applying=True)

    if keep:
        print(f"\n  source + applied change left in {out}/")
    else:
        sh.rmtree(out, ignore_errors=True)
        print("\n  (temp copy removed; pass --keep to inspect the rewritten source)")
    print("  next → " + _col("boostopt optimize <your-file.cpp> --offline", "1"))
    return 0 if any(v.accepted for v in verdicts) else 1


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
    from ...runtime.sandbox import isolation_available, memory_cap_available
    san = sanitizer_toolchain()
    rows = [
        ("clang++", sh.which("clang++"), True),
        ("g++", sh.which("g++"), True),
        ("sanitizers (Rung 3)", f"{san[0]} {san[1]}" if san else None, True),
        ("libclang (python)", "ok" if _has_libclang() else None, True),
        ("sandbox isolation", "bwrap (no-net, ro-fs)" if isolation_available() else None, False),
        ("sandbox memory cap", "cgroup (systemd-run)" if memory_cap_available() else None, False),
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
        print(f"boostopt: error: no such file: {path}", file=sys.stderr)
        return 2
    if not sh.which("patch"):
        print("boostopt: error: --apply-from needs the `patch` tool on PATH", file=sys.stderr)
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
        return "", "boostopt: bad arguments\n", int(e.code or 2)
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

    # thin-client fast path: hand analyze/optimize to a warm daemon if one is up.
    # (skip for --model hosted — that runs on OUR server, not the local daemon.)
    if (args.cmd in ("analyze", "optimize") and not args.no_daemon
            and getattr(args, "model", None) != "hosted"):
        resp = daemon.try_client(argv)
        if resp is not None:
            out, err, code = resp
            sys.stdout.write(out)
            sys.stderr.write(err)
            return code

    return _run_command(args)
