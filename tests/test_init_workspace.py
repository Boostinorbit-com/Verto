"""`verto init` — the `.verto/` local performance workspace ("git for performance").

Covers the pure workspace logic (create / idempotent / discovery / ledger location), the
Ollama probe (mocked — no daemon needed), and the `_init` CLI handler end to end.
"""
import json

import pytest

from verto.engine import workspace


# --- workspace scaffolding --------------------------------------------------

def test_init_creates_the_workspace(tmp_path):
    info = workspace.init(tmp_path, model="qwen3:1.7b", host="http://h:11434")
    ws = tmp_path / ".verto"
    assert not info["existed"]
    assert (ws / "ledger.jsonl").exists()
    assert (ws / "baselines").is_dir() and (ws / "cache").is_dir()
    assert workspace.read_model(ws) == {"model": "qwen3:1.7b", "host": "http://h:11434"}


def test_init_is_idempotent_and_preserves_state(tmp_path):
    workspace.init(tmp_path, model="m", host="h")
    (tmp_path / ".verto" / "ledger.jsonl").write_text('{"kept":1}\n', encoding="utf-8")
    info = workspace.init(tmp_path, model="OTHER", host="OTHER")   # re-run
    assert info["existed"]
    assert (tmp_path / ".verto" / "ledger.jsonl").read_text(encoding="utf-8") == '{"kept":1}\n'
    assert workspace.read_model(tmp_path / ".verto")["model"] == "m"   # pointer not clobbered


def test_gitignore_add_is_idempotent(tmp_path):
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    assert workspace.gitignore_add(tmp_path) is True
    assert workspace.gitignore_add(tmp_path) is False                 # already there → no dup
    body = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert body.count(".verto/") == 1 and "build/" in body


def test_starter_config_written_once(tmp_path):
    assert workspace.write_starter_config(tmp_path, model="qwen3:1.7b", host="h") is True
    assert 'model        = "local"' in (tmp_path / ".verto.toml").read_text(encoding="utf-8")
    assert workspace.write_starter_config(tmp_path, model="x", host="h") is False  # never clobber


# --- discovery + ledger location -------------------------------------------

def test_find_and_ledger_path(tmp_path):
    assert workspace.find(tmp_path) is None                           # none yet
    assert workspace.ledger_path(tmp_path) == "ledger.jsonl"          # legacy fallback
    workspace.init(tmp_path, model="m", host="h")
    sub = tmp_path / "src" / "deep"
    sub.mkdir(parents=True)
    assert workspace.find(sub) == tmp_path / ".verto"                 # discovered walking up
    assert workspace.ledger_path(sub) == str(tmp_path / ".verto" / "ledger.jsonl")


# --- Ollama probe (mocked) --------------------------------------------------

def _fake_tags(names):
    payload = json.dumps({"models": [{"name": n} for n in names]}).encode()

    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return payload
    return lambda url, timeout=0: _R()


def test_ollama_status_reachable_with_model(monkeypatch):
    from verto.runtime import llm
    monkeypatch.setattr(llm.urllib.request, "urlopen", _fake_tags(["qwen3:1.7b", "llama3:8b"]))
    st = llm.ollama_status("http://h:11434", "qwen3:1.7b")
    assert st.reachable and st.has_model


def test_ollama_status_reachable_missing_model(monkeypatch):
    from verto.runtime import llm
    monkeypatch.setattr(llm.urllib.request, "urlopen", _fake_tags(["llama3:8b"]))
    st = llm.ollama_status("http://h:11434", "qwen3:1.7b")
    assert st.reachable and not st.has_model


def test_ollama_status_unreachable(monkeypatch):
    from verto.runtime import llm
    def boom(*a, **k): raise OSError("connection refused")
    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    st = llm.ollama_status("http://h:11434", "qwen3:1.7b")
    assert not st.reachable and not st.has_model


# --- the CLI handler end to end --------------------------------------------

def test_cli_init_handler(tmp_path, monkeypatch, capsys):
    from verto.runtime import llm
    from verto.surfaces.cli.main import _init
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(llm, "ollama_status",
                        lambda host, model, **k: llm.OllamaStatus(True, True))
    rc = _init()
    out = capsys.readouterr().out
    assert rc == 0
    assert (tmp_path / ".verto" / "ledger.jsonl").exists()
    assert (tmp_path / ".verto.toml").exists()
    assert "workspace initialized" in out and "local model ready" in out


if __name__ == "__main__":
    import sys
    sys.exit("run via pytest (uses tmp_path/monkeypatch/capsys fixtures)")
