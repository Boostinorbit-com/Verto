"""Global (machine-wide) config tier: `~/.config/boostopt/config.toml` layered UNDER the project
`.boostopt.toml`. Precedence: project > global > code defaults (the git model).

XDG_CONFIG_HOME is isolated to a temp dir by the autouse conftest fixture, so these tests never
touch a real user config.
"""
import pytest

from boostopt.engine import config as _config
from boostopt.engine.config import Config, global_config_path

pytestmark = pytest.mark.skipif(_config.tomllib is None,
                                reason="no TOML parser (need py3.11+ or `pip install tomli`)")


def _write_global(body):
    p = global_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("[boostopt]\n" + body, encoding="utf-8")
    return p


def test_global_config_path_is_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert global_config_path() == tmp_path / "cfg" / "boostopt" / "config.toml"


def test_global_provides_defaults(tmp_path):
    _write_global('model = "local"\nllm_model = "qwen3:0.6b"\n')
    cfg = Config.load(tmp_path / "no_project.toml")     # no project file → global applies
    assert cfg.model == "local" and cfg.llm_model == "qwen3:0.6b"


def test_project_overrides_global(tmp_path):
    _write_global('model = "local"\nmin_rung = 1\n')
    proj = tmp_path / ".boostopt.toml"
    proj.write_text('[boostopt]\nmodel = "rules"\n', encoding="utf-8")   # project wins on model
    cfg = Config.load(proj)
    assert cfg.model == "rules"        # project overrides global
    assert cfg.min_rung == 1           # global still fills what the project omits


def test_no_config_anywhere_is_defaults(tmp_path):
    cfg = Config.load(tmp_path / "nope.toml")
    assert cfg.model == Config().model and cfg.min_rung == Config().min_rung


def test_init_global_scaffolds_file(tmp_path, monkeypatch):
    from boostopt.engine import workspace
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    p = workspace.write_global_config(model="qwen3:1.7b", host="http://h:11434")
    assert p.exists() and 'model     = "local"' in p.read_text(encoding="utf-8")
    # idempotent — never clobbers an existing global config
    p.write_text("[boostopt]\nmodel = \"frontier\"\n", encoding="utf-8")
    workspace.write_global_config(model="x", host="h")
    assert 'model = "frontier"' in p.read_text(encoding="utf-8")


if __name__ == "__main__":
    import sys
    sys.exit("run via pytest (uses tmp_path/monkeypatch fixtures)")
