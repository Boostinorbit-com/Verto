"""The `.boostopt/` workspace — BOOSTOPT's per-project state directory, like `.git/`.

`boostopt init` creates it; the Engine reads its ledger from here when one is present. It holds
**local, generated** state — the ledger, baselines, cache, and a small pointer to *which*
global model to use — and is git-ignored. The **committed, shared** team config stays at the
repo-root `.boostopt.toml`.

The model **weights never live here.** They're global and gigabytes — Ollama already stores
them once (`~/.ollama`), shared across every project. `.boostopt/model` records only the model's
*name + host*, never the weights. (This is also why the workspace dir is `.boostopt/` and the
global store is Ollama's own — so a walk-up from `~` can never mistake one for the other.)
"""
from __future__ import annotations

import json
from pathlib import Path

DIRNAME = ".boostopt"
_SUBDIRS = ("baselines", "cache")
_LEDGER = "ledger.jsonl"
_MODEL = "model"
_ROOT_CONFIG = ".boostopt.toml"


def find(start: str | Path | None = None) -> Path | None:
    """The nearest ancestor's `.boostopt/` workspace (like git discovering `.git/`), or None.

    Ascends from `start` (default cwd) but stops at `$HOME`, so a stray directory above the
    user's home is never treated as a project workspace."""
    here = Path(start or Path.cwd()).resolve()
    home = Path.home().resolve()
    for d in (here, *here.parents):
        if (d / DIRNAME).is_dir():
            return d / DIRNAME
        if d == home:                        # don't ascend past $HOME hunting for a workspace
            break
    return None


def ledger_path(start: str | Path | None = None) -> str:
    """Where the ledger lives: inside the workspace when one exists, else the legacy
    repo-root `ledger.jsonl` (so everything works before `boostopt init` is ever run)."""
    ws = find(start)
    return str(ws / _LEDGER) if ws else _LEDGER


def read_model(ws: str | Path) -> dict:
    """The `{model, host}` pointer, or {} if unset/unreadable."""
    p = Path(ws) / _MODEL
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_model(ws: str | Path, *, model: str, host: str) -> None:
    (Path(ws) / _MODEL).write_text(
        json.dumps({"model": model, "host": host}, indent=2) + "\n", encoding="utf-8")


def init(root: str | Path = ".", *, model: str, host: str) -> dict:
    """Create (or top-up) the `.boostopt/` workspace. **Idempotent** — never clobbers an
    existing ledger or model pointer; only fills in what's missing. Returns a summary."""
    ws = Path(root) / DIRNAME
    existed = ws.is_dir()
    ws.mkdir(exist_ok=True)
    for d in _SUBDIRS:
        (ws / d).mkdir(exist_ok=True)
    if not (ws / _LEDGER).exists():
        (ws / _LEDGER).touch()
    if not (ws / _MODEL).exists():
        write_model(ws, model=model, host=host)
    return {"workspace": str(ws), "existed": existed, "model": read_model(ws)}


def gitignore_add(root: str | Path = ".") -> bool:
    """Ensure `.boostopt/` is git-ignored. Idempotent — returns True only if it added the line."""
    gi = Path(root) / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if any(ln.strip().rstrip("/") == DIRNAME for ln in existing.splitlines()):
        return False
    with gi.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(f"\n# BOOSTOPT local performance workspace (generated state)\n{DIRNAME}/\n")
    return True


def write_global_config(*, model: str, host: str) -> Path:
    """Scaffold the machine-wide user defaults at `~/.config/boostopt/config.toml` (only if
    absent), then return its path. These apply to every project unless a project `.boostopt.toml`
    overrides them. Not the per-project workspace — global, XDG-idiomatic, never `~/.boostopt/`."""
    from .config import global_config_path
    p = global_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(
            "# BOOSTOPT machine-wide defaults (apply to every project; a project .boostopt.toml wins).\n"
            "[boostopt]\n"
            'model     = "local"          # local (Ollama, no key) | frontier | rules\n'
            f'llm_model = "{model}"\n'
            f'# llm_base_url = "{host}"\n'
            "# budget    = \"$0.50\"        # default per-run LLM spend cap\n",
            encoding="utf-8")
    return p


def write_starter_config(root: str | Path = ".", *, model: str, host: str) -> bool:
    """Write a committed starter `.boostopt.toml` (the shared team config) **only if absent**.
    Local-first: it defaults the proposer to `local`. Returns True if written."""
    p = Path(root) / _ROOT_CONFIG
    if p.exists():
        return False
    p.write_text(
        "# BOOSTOPT project config — committed, shared by the team.\n"
        "# Local performance state (ledger, baselines, cache) lives in .boostopt/ (git-ignored).\n"
        "# Full key list: Docs/BOOSTOPT_Surfaces.\n"
        "[boostopt]\n"
        'model        = "local"          # local (Ollama, no key) | frontier | rules\n'
        f'llm_model    = "{model}"\n'
        f'# llm_base_url = "{host}"\n'
        "# min_rung   = 3                 # 1 = differential test, 3 = sanitizers\n"
        "# candidates = 1                 # N LLM rewrites per hotspot (best-of-N)\n",
        encoding="utf-8")
    return True
