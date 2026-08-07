"""Test hermeticity.

`Config.load` reads machine-wide defaults from `$XDG_CONFIG_HOME/boostopt/config.toml`. Point
XDG at an empty per-test temp dir so a developer's REAL `~/.config/boostopt/config.toml` can never
leak into the suite (a stray `model = "local"` there would make tests invoke the LLM and hang).
Tests that exercise global config write into this isolated dir via `config.global_config_path()`.

Also isolate the best-so-far rewrite cache to a per-test temp file — otherwise tests would share
(and pollute) the repo's `.boostopt/cache/`, and a cache HIT would replace a fresh verdict with a
stored one. Tests that want to exercise the cache point their own Engine at a temp path.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_global_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    import boostopt.engine.workspace as _ws
    monkeypatch.setattr(_ws, "cache_path", lambda *a, **k: str(tmp_path / "boostopt-cache.jsonl"))
