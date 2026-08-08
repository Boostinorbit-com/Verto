"""Local-model provisioning — make BOOSTOPT's default Ollama model exist on this machine.

The default local model, `boostopt2.5-coder:7b`, is a **re-tag** of `qwen2.5-coder:7b` with
BOOSTOPT's optimize system prompt and sampling baked in (see `models/*.Modelfile`; the
Apache-2.0 provenance lives in the file header). It is NOT a second download — `ollama create`
re-labels weights Ollama already has, so the only bytes on the wire are the base model's.

**Why this is not a pip step.** Wheels execute no install-time code, so `pip install boostopt`
cannot touch Ollama — and shouldn't: it would turn a 2-second install into a multi-GB one.
Provisioning happens on `boostopt init`, where the user has already opted into a local model,
and the download itself stays behind `--pull`.

Everything here degrades instead of failing. `ensure_local_model()` returns the tag the caller
should actually configure: the branded one when it's usable, otherwise the plain base model, so
a project is always left pointing at something a single `ollama pull` can satisfy.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass

from . import llm, receipt

_PKG = "boostopt.runtime.models"
_FROM = re.compile(r"^\s*FROM\s+(\S+)", re.IGNORECASE | re.MULTILINE)


def modelfile_name(tag: str) -> str:
    """`boostopt2.5-coder:7b` → `boostopt2.5-coder.Modelfile` (the size suffix isn't in the
    filename — one recipe serves every tag of a family)."""
    return tag.split(":", 1)[0] + ".Modelfile"


def has_bundled_modelfile(tag: str) -> bool:
    """Is `tag` one of OURS (a model we know how to build), or a user-supplied one we should
    leave alone? Decides re-tag path vs. plain-pull path."""
    from importlib.resources import files
    try:
        return (files(_PKG) / modelfile_name(tag)).is_file()
    except (ModuleNotFoundError, OSError):
        return False


@contextmanager
def bundled_modelfile(tag: str):
    """Yield a real filesystem path to `tag`'s bundled Modelfile (extracted to a temp file if
    the package is zipped), or None when we don't ship one. `ollama create -f` needs a path."""
    from importlib.resources import as_file, files
    try:
        res = files(_PKG) / modelfile_name(tag)
        if not res.is_file():
            yield None
            return
    except (ModuleNotFoundError, OSError):
        yield None
        return
    with as_file(res) as p:
        yield p


def base_model(tag: str) -> str | None:
    """The upstream model a bundled recipe builds on (its `FROM` line), or None."""
    with bundled_modelfile(tag) as p:
        if p is None:
            return None
        try:
            m = _FROM.search(p.read_text(encoding="utf-8"))
        except OSError:
            return None
    return m.group(1) if m else None


@dataclass
class Provisioned:
    model: str            # the tag the caller should CONFIGURE (branded, or the base fallback)
    ready: bool           # that tag is present in Ollama right now
    built: bool           # we ran `ollama create` during this call


# `_run` / `_run_shell` are the ONLY places this module executes anything. Keeping that to two
# named seams is what lets the test suite stub them out wholesale — patching `subprocess.run`
# instead would mutate the stdlib module every other test shares.

def _run(argv: list[str]) -> bool:
    # Flush first: `ollama` writes straight to the terminal, while our own prints sit in a block
    # buffer whenever stdout is a pipe (CI logs, `| tee`) — without this its progress bar lands
    # ABOVE the lines that introduce it.
    sys.stdout.flush()
    try:
        return subprocess.run(argv).returncode == 0
    except OSError:
        return False


def _run_shell(cmd: str) -> bool:
    """Run a vendor one-liner through a shell (their installer is a `curl … | sh` pipeline).
    Callers pass fixed constants from install_command()/uninstall_commands() — no user input
    ever reaches this."""
    sys.stdout.flush()
    try:
        return subprocess.run(cmd, shell=True).returncode == 0
    except OSError:
        return False


def _plain_emit(msg: str, *, ok: bool = False, warn: bool = False, hint: str = "") -> None:
    """Uncolored default. The CLI passes its own emitter so ok/warn pick up green/yellow —
    this module stays free of terminal concerns (it's runtime, not a surface)."""
    print(msg + (f" — {hint}" if hint else ""))


# --- installing Ollama itself (opt-in only) ---------------------------------
#
# Ollama is NOT a Python dependency and pip cannot deliver it: it's a native binary plus a
# system service. We can shell out to the vendor's installer, but only when the user explicitly
# asks (`--install-ollama`) AND confirms, because it needs root and leaves a daemon enabled at
# boot. A plain `boostopt init --pull` must never trigger it.

def install_command() -> tuple[str, bool]:
    """`(command, we_can_run_it)` for this platform. Windows has no scriptable install we're
    willing to drive, so it gets a link and `False`."""
    if sys.platform.startswith("linux"):
        return "curl -fsSL https://ollama.com/install.sh | sh", True
    if sys.platform == "darwin":
        if shutil.which("brew"):
            return "brew install ollama", True
        return "https://ollama.com/download  (or install Homebrew first)", False
    return "https://ollama.com/download", False


def _confirm(question: str) -> bool:
    """Interactive y/N. A non-TTY (CI, a pipe, a hook) answers NO — never assume consent from
    something that cannot be asked."""
    if not (sys.stdin and sys.stdin.isatty()):
        return False
    try:
        return input(question).strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def install_ollama(base_url: str, *, emit=_plain_emit, timeout: float = 2.0) -> bool:
    """Offer to install Ollama, then wait for its daemon. Returns True only if it ends up
    answering. Declining is a normal outcome, not an error."""
    cmd, runnable = install_command()
    if not runnable:
        emit("  ! can't install Ollama for you on this platform", warn=True, hint=cmd)
        return False

    emit("  Ollama is missing. About to run (this needs sudo and installs a service that"
         " starts at boot):")
    emit(f"      {cmd}")
    if not _confirm("  Proceed? [y/N] "):
        emit("  skipped — install it yourself, then re-run `boostopt init --pull`", warn=True,
             hint=cmd)
        return False

    ok = _run_shell(cmd)
    if not ok:
        emit("  ! the Ollama installer failed — install it yourself and re-run", warn=True,
             hint=cmd)
        return False

    receipt.record_ollama_install(cmd)   # claim it BEFORE the wait: it is installed either way
    emit("  waiting for the Ollama daemon …")
    for _ in range(15):                       # the service needs a moment after install
        if llm.ollama_status(base_url, "", timeout=timeout).reachable:
            emit("  ✓ Ollama is up", ok=True)
            return True
        time.sleep(1)
    emit("  ! Ollama installed but its daemon isn't answering", warn=True,
         hint="start it with `ollama serve`, then re-run `boostopt init --pull`")
    return False


def uninstall_commands() -> list[str]:
    """The teardown for an Ollama WE installed. Deliberately leaves the model store alone —
    it's gigabytes the user may want back, and a reinstall picks it up untouched."""
    if sys.platform.startswith("linux"):
        exe = shutil.which("ollama") or "/usr/local/bin/ollama"
        return ["sudo systemctl stop ollama",
                "sudo systemctl disable ollama",
                "sudo rm -f /etc/systemd/system/ollama.service",
                "sudo systemctl daemon-reload",
                f"sudo rm -f {exe}",
                "sudo userdel ollama", "sudo groupdel ollama"]
    if sys.platform == "darwin" and shutil.which("brew"):
        return ["brew uninstall ollama"]
    return []


def uninstall_ollama(*, emit=_plain_emit, execute: bool = False) -> bool:
    """Show (and, once confirmed, run) the Ollama teardown. Same consent rule as the installer:
    root-level changes are printed first and never happen in a non-TTY."""
    cmds = uninstall_commands()
    if not cmds:
        emit("  ! no scriptable Ollama uninstall for this platform — remove it yourself",
             warn=True, hint="https://ollama.com")
        return False

    emit("  Ollama was installed by BOOSTOPT. Removing it runs (needs sudo):")
    for c in cmds:
        emit(f"      {c}")
    emit("      (the model store is left in place — delete /usr/share/ollama yourself"
         " to reclaim the disk)")
    if not execute:
        return False
    if not _confirm("  Proceed? [y/N] "):
        emit("  skipped — Ollama left installed", warn=True)
        return False

    ok = True
    for c in cmds:
        ok = _run_shell(c) and ok
    return ok


def ensure_local_model(base_url: str, tag: str, *, pull: bool = False, install: bool = False,
                       emit=_plain_emit, timeout: float = 2.0) -> Provisioned:
    """Make `tag` usable, downloading only when `pull` is set.

    The happy path for a fresh `pip install` + `boostopt init --pull`: pull `qwen2.5-coder:7b`
    once, then `ollama create boostopt2.5-coder:7b` from the bundled recipe (seconds, no extra
    download). Every failure falls back to the base tag rather than leaving the project pointed
    at a model that doesn't exist.

    `install=True` (the CLI's `--install-ollama`) additionally offers to install Ollama itself
    when it's absent — with a confirmation prompt, since that needs root. Off by default.
    """
    st = llm.ollama_status(base_url, tag, timeout=timeout)
    base = base_model(tag)
    fallback = Provisioned(base or tag, False, False)

    if not st.reachable:
        if shutil.which("ollama") is None:
            if not (install and install_ollama(base_url, emit=emit, timeout=timeout)):
                cmd, _ = install_command()
                emit("  ! Ollama not detected — needed for --model local", warn=True)
                emit(f"      install:   {cmd}")
                emit("      re-run:    boostopt init --pull   (add --install-ollama to do both)")
                emit("      or skip:   boostopt optimize <file> --offline   (no model needed)")
                return fallback
        else:
            emit("  ! Ollama is installed but its daemon isn't answering", warn=True,
                 hint="start it with `ollama serve`, then re-run `boostopt init --pull`")
            return fallback
        st = llm.ollama_status(base_url, tag, timeout=timeout)   # re-probe after a fresh install
        if not st.reachable:
            return fallback

    if st.has_model:
        emit(f"  ✓ local model ready: {tag}", ok=True)
        return Provisioned(tag, True, False)

    if base is None:                       # not one of ours — the plain pull path, unchanged
        emit(f"  ! model '{tag}' not pulled", warn=True, hint=f"run: ollama pull {tag}")
        if pull:
            if shutil.which("ollama") is None:
                emit("  (ollama CLI not on PATH — pull it yourself, or use --model frontier)")
                return Provisioned(tag, False, False)
            emit(f"  pulling {tag} … (this can take a while)")
            if _run(["ollama", "pull", tag]):
                receipt.record_model(tag, pulled=True)
                emit(f"  ✓ local model ready: {tag}", ok=True)
                return Provisioned(tag, True, False)
            emit(f"  ! pull failed for '{tag}'", warn=True)
        return Provisioned(tag, False, False)

    # --- ours: base + re-tag ------------------------------------------------
    if shutil.which("ollama") is None:
        emit("  ! ollama CLI not on PATH — can't build " + tag, warn=True,
             hint=f"using the base model '{base}' instead")
        return Provisioned(base, llm.ollama_status(base_url, base, timeout=timeout).has_model,
                           False)

    if not llm.ollama_status(base_url, base, timeout=timeout).has_model:
        if not pull:
            emit(f"  ! base model '{base}' not pulled — {tag} not built yet", warn=True,
                 hint="run: boostopt init --pull   (downloads the base once, ~4GB)")
            return Provisioned(base, False, False)     # config the base: one `ollama pull` away
        emit(f"  pulling {base} … (this can take a while)")
        if not _run(["ollama", "pull", base]):
            emit(f"  ! pull failed for '{base}' — leaving the base tag configured", warn=True)
            return Provisioned(base, False, False)
        receipt.record_model(base, pulled=True)

    emit(f"  building {tag} from {base} … (re-tag, no extra download)")
    with bundled_modelfile(tag) as mf:
        ok = mf is not None and _run(["ollama", "create", tag, "-f", str(mf)])
    if not ok:
        emit(f"  ! `ollama create {tag}` failed — falling back to '{base}'", warn=True)
        return Provisioned(base, True, False)
    emit(f"  ✓ local model ready: {tag}  (from {base})", ok=True)
    receipt.record_model(tag, created_from=base)
    return Provisioned(tag, True, True)
