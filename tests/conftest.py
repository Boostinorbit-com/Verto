"""Test hermeticity.

`Config.load` reads machine-wide defaults from `$XDG_CONFIG_HOME/boostopt/config.toml`. Point
XDG at an empty per-test temp dir so a developer's REAL `~/.config/boostopt/config.toml` can never
leak into the suite (a stray `model = "local"` there would make tests invoke the LLM and hang).
Tests that exercise global config write into this isolated dir via `config.global_config_path()`.

`$XDG_STATE_HOME` is isolated for a sharper reason: the provenance receipt
(`runtime/receipt.py`) is WRITTEN by the provisioning tests. Those tests mock Ollama, so a
`pulled` or `installed` entry they record is fiction — but the file it lands in is real. Left
unisolated, the suite tells the developer's own `boostopt uninstall` that it owns a base model
the developer pulled themselves, and an Ollama they installed themselves. The next
`--remove-ollama` would then destroy both. That happened once; this line is why it can't again.

Also isolate the best-so-far rewrite cache to a per-test temp file — otherwise tests would share
(and pollute) the repo's `.boostopt/cache/`, and a cache HIT would replace a fresh verdict with a
stored one. Tests that want to exercise the cache point their own Engine at a temp path.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_global_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    import boostopt.engine.workspace as _ws
    monkeypatch.setattr(_ws, "cache_path", lambda *a, **k: str(tmp_path / "boostopt-cache.jsonl"))


@pytest.fixture(autouse=True)
def _no_real_ollama(monkeypatch):
    """No test may shell out to the developer's real Ollama.

    Provisioning and uninstall drive `ollama pull/create/rm` through `provision.subprocess.run`.
    A test that forgets to mock it doesn't fail — it silently succeeds while deleting a 4.7 GB
    model off the machine. (That is not hypothetical: a uninstall test did exactly that.)

    So both seams are stubbed here by default. Tests that want to observe the calls replace them
    with their own fakes — a later, test-scoped monkeypatch wins — and get the same interface.
    Nothing has to opt IN to safety.

    Note it patches `provision._run` / `provision._run_shell`, NOT `subprocess.run`: the latter
    is the shared stdlib module object, so stubbing it there also breaks the sandbox tests that
    legitimately spawn processes.
    """
    import boostopt.runtime.provision as _p
    monkeypatch.setattr(_p, "_run", lambda argv: True)
    monkeypatch.setattr(_p, "_run_shell", lambda cmd: True)
