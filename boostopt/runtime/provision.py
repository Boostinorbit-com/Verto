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
from contextlib import contextmanager
from dataclasses import dataclass

from . import llm

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


def _run(argv: list[str]) -> bool:
    # Flush first: `ollama` writes straight to the terminal, while our own prints sit in a block
    # buffer whenever stdout is a pipe (CI logs, `| tee`) — without this its progress bar lands
    # ABOVE the lines that introduce it.
    sys.stdout.flush()
    try:
        return subprocess.run(argv).returncode == 0
    except OSError:
        return False


def _plain_emit(msg: str, *, ok: bool = False, warn: bool = False, hint: str = "") -> None:
    """Uncolored default. The CLI passes its own emitter so ok/warn pick up green/yellow —
    this module stays free of terminal concerns (it's runtime, not a surface)."""
    print(msg + (f" — {hint}" if hint else ""))


def ensure_local_model(base_url: str, tag: str, *, pull: bool = False,
                       emit=_plain_emit, timeout: float = 2.0) -> Provisioned:
    """Make `tag` usable, downloading only when `pull` is set.

    The happy path for a fresh `pip install` + `boostopt init --pull`: pull `qwen2.5-coder:7b`
    once, then `ollama create boostopt2.5-coder:7b` from the bundled recipe (seconds, no extra
    download). Every failure falls back to the base tag rather than leaving the project pointed
    at a model that doesn't exist.
    """
    st = llm.ollama_status(base_url, tag, timeout=timeout)
    base = base_model(tag)

    if not st.reachable:
        emit(("  ! Ollama not detected — for --model local see https://ollama.com,"
              " or use --model frontier with OPENAI_API_KEY set"), warn=True)
        if base:
            emit(f"    (once Ollama is installed, `boostopt init --pull` builds {tag})")
            return Provisioned(base, False, False)
        return Provisioned(tag, False, False)

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

    emit(f"  building {tag} from {base} … (re-tag, no extra download)")
    with bundled_modelfile(tag) as mf:
        ok = mf is not None and _run(["ollama", "create", tag, "-f", str(mf)])
    if not ok:
        emit(f"  ! `ollama create {tag}` failed — falling back to '{base}'", warn=True)
        return Provisioned(base, True, False)
    emit(f"  ✓ local model ready: {tag}  (from {base})", ok=True)
    return Provisioned(tag, True, True)
