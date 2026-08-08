"""`boostopt-uninstall` — the reverse of `install.sh`, in one command.

**Why this is a separate console script and not `pip uninstall`.** pip executes no code when it
removes a distribution: an uninstall is "delete the files listed in RECORD", and no wheel hook
has ever existed to change that. It is the same wall that stops pip from *installing* Ollama —
a native binary plus a system service is not something a Python package can deliver. So the
teardown has to be a program of ours, and this is it. It finishes by calling `pip uninstall`
itself, so the user still types one command.

**The safety rule, and why it needs a receipt.** Removing "everything BOOSTOPT touched" is easy
and wrong: it would delete a `qwen2.5-coder:7b` three other projects share, or tear down an
Ollama that was on the machine long before us. So we remove only what `runtime/receipt.py`
records as ours, and say out loud what we are leaving alone.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from ..engine import workspace
from ..engine.config import global_config_path
from ..runtime import provision, receipt
from .cli.render import _col


def _emit(msg: str, *, ok: bool = False, warn: bool = False, hint: str = "") -> None:
    body = _col(msg, "32") if ok else _col(msg, "33") if warn else msg
    print(body + (f" — {hint}" if hint else ""))


def build_plan(root: str = ".") -> list[tuple[str, object]]:
    """`(description, action)` for everything we may remove. Description first so a dry run can
    show the exact set without being able to perform any of it."""
    plan: list[tuple[str, object]] = []
    for tag in receipt.owned_models():
        plan.append((f"ollama rm {tag}", lambda t=tag: provision._run(["ollama", "rm", t])))

    ws = Path(root) / workspace.DIRNAME
    if ws.is_dir():
        plan.append((f"rm -r {ws}/", lambda: shutil.rmtree(ws, ignore_errors=True)))

    gc = global_config_path()
    if gc.exists():
        plan.append((f"rm {gc}", lambda: gc.unlink(missing_ok=True)))
    return plan


def _remove_package(emit=_emit) -> bool:
    """`pip uninstall boostopt` — deleting the package that provides this very command.

    Fine on POSIX: our code is already resident and unlinking an open file is legal. Windows
    locks a running executable, so there we print the command instead of failing halfway."""
    if sys.platform == "win32":
        emit("  · Windows can't remove a running program — finish with:", warn=True,
             hint="pip uninstall boostopt")
        return False
    sys.stdout.flush()
    try:
        return subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y",
                               "boostopt"]).returncode == 0
    except OSError:
        return False


def run(*, yes: bool = False, remove_ollama: bool = False, keep_package: bool = False,
        root: str = ".") -> int:
    plan = build_plan(root)

    # Read the Ollama claim ONCE, up front: the receipt is deleted at the end of a full teardown,
    # and anything consulting it afterwards would see "we own nothing" and silently skip.
    ours_ollama = receipt.owns_ollama()
    rp = receipt.receipt_path()

    if not plan and not ours_ollama:
        print("nothing to remove — no BOOSTOPT-installed models, workspace, or config found")
        if not keep_package and yes:
            _remove_package()
        return 0

    print(_col("boostopt-uninstall", "1") + (" — plan" if not yes else ""))
    for what, _ in plan:
        print(f"    {what}")

    # The whole reason the receipt exists. Say it out loud, so "where did my qwen go?" is a
    # question nobody ever has to ask.
    kept = [t for t in receipt.load().get("models", {}) if not receipt.owns_model(t)]
    if kept:
        print(_col(f"    (leaving alone, not ours: {', '.join(kept)})", "2"))

    if ours_ollama:
        provision.uninstall_ollama(emit=_emit, execute=False)
    elif shutil.which("ollama"):
        print(_col("    (Ollama was already on this machine — left installed)", "2"))
    if not keep_package:
        print("    pip uninstall boostopt")

    if not yes:
        print("\n  dry run — nothing removed. Re-run with " + _col("--yes", "1")
              + (" (add --remove-ollama to include Ollama)" if ours_ollama else ""))
        return 0

    for what, action in plan:
        action()
        print(_col(f"  ✓ {what}", "32"))

    ollama_gone = provision.uninstall_ollama(emit=_emit, execute=True) \
        if (remove_ollama and ours_ollama) else not ours_ollama

    # Deleted LAST, and only once nothing it vouches for remains: dropping it while our Ollama is
    # still installed would strand it — a later `--remove-ollama` would see "not ours" and refuse.
    if rp.exists() and ollama_gone:
        receipt.forget()
        print(_col(f"  ✓ rm {rp}", "32"))
    elif not ollama_gone:
        print(_col("  · receipt kept — Ollama is still installed and still ours;"
                   " `boostopt-uninstall --yes --remove-ollama` finishes the job", "2"))

    if not keep_package:
        _remove_package()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="boostopt-uninstall",
        description="Remove BOOSTOPT: the models it built, the workspace, the global config, "
                    "Ollama if BOOSTOPT installed it, and finally the package itself. "
                    "Anything that was already on this machine is left alone.")
    p.add_argument("--yes", action="store_true",
                   help="actually remove (without this it only prints the plan)")
    p.add_argument("--remove-ollama", dest="remove_ollama", action="store_true",
                   help="also tear down Ollama — only if BOOSTOPT installed it; asks first")
    p.add_argument("--keep-package", dest="keep_package", action="store_true",
                   help="leave the pip package installed (remove only what init created)")
    a = p.parse_args(argv)
    return run(yes=a.yes, remove_ollama=a.remove_ollama, keep_package=a.keep_package)


if __name__ == "__main__":
    sys.exit(main())
