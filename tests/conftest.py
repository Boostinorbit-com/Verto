"""Test hermeticity.

`Config.load` reads machine-wide defaults from `$XDG_CONFIG_HOME/verto/config.toml`. Point
XDG at an empty per-test temp dir so a developer's REAL `~/.config/verto/config.toml` can never
leak into the suite (a stray `model = "local"` there would make tests invoke the LLM and hang).
Tests that exercise global config write into this isolated dir via `config.global_config_path()`.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_global_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
