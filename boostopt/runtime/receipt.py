"""Provenance receipt — what BOOSTOPT installed on THIS machine, so uninstall can be honest.

pip cannot help in either direction: a wheel runs no code at install time (which is why Ollama
and the model are provisioned by `boostopt init`) and none at uninstall time (which is why
`pip uninstall boostopt` can never undo that). The gap is bridged by writing down what we did.

The point is not the bookkeeping — it's the **negative** information. An uninstaller without a
receipt has to guess, and guessing here means ripping out an Ollama that was already on the
machine, or deleting a `qwen2.5-coder:7b` that three other projects use. `boostopt uninstall`
removes ONLY what this file claims as ours; anything pre-existing is never touched.

Machine-scoped (`$XDG_STATE_HOME/boostopt/installed.json`), not the per-project `.boostopt/`:
an Ollama install is system-wide, so one project's teardown must not claim another's. State,
not config — it's generated, not edited, so it doesn't belong next to `config.toml`.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def receipt_path() -> Path:
    """`$XDG_STATE_HOME/boostopt/installed.json` (default `~/.local/state/boostopt/`)."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "boostopt" / "installed.json"


def load() -> dict:
    """The receipt, or `{}` when absent/unreadable. Never raises — a missing receipt means
    "we have no claim on anything", which is the safe reading."""
    try:
        return json.loads(receipt_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    p = receipt_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass          # a receipt we can't write is a smaller problem than a failed install


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def record_ollama_install(command: str) -> None:
    """Called ONLY after we actually installed Ollama ourselves."""
    data = load()
    data["ollama"] = {"installed_by_boostopt": True, "at": _now(), "command": command}
    _save(data)


def record_model(tag: str, *, created_from: str | None = None, pulled: bool = False) -> None:
    """Called ONLY after we pulled or built `tag` ourselves — never for one that was already
    there. `created_from` marks a re-tag we built; `pulled` marks a download we performed."""
    data = load()
    models = data.setdefault("models", {})
    entry = models.setdefault(tag, {})
    entry["at"] = _now()
    if created_from:
        entry["created_by_boostopt"] = True
        entry["base"] = created_from
    if pulled:
        entry["pulled_by_boostopt"] = True
    _save(data)


def owns_model(tag: str) -> bool:
    """Did we put this model here? A model the user pulled themselves answers False, and so is
    left alone by uninstall."""
    e = load().get("models", {}).get(tag, {})
    return bool(e.get("created_by_boostopt") or e.get("pulled_by_boostopt"))


def owned_models() -> list[str]:
    """Ours, re-tags first — removing a derived tag before its base keeps Ollama's shared blobs
    from being reference-counted in a confusing order."""
    models = load().get("models", {})
    ours = [t for t in models if owns_model(t)]
    return sorted(ours, key=lambda t: not models[t].get("created_by_boostopt"))


def owns_ollama() -> bool:
    """Did we install the Ollama runtime itself? False when the user already had it — in which
    case uninstall must never offer to tear it down."""
    return bool(load().get("ollama", {}).get("installed_by_boostopt"))


def forget() -> None:
    """Drop the receipt (after a successful teardown). Idempotent."""
    try:
        receipt_path().unlink()
    except OSError:
        pass
