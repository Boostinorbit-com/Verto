"""Local-model provisioning — building `boostopt2.5-coder:7b` from its bundled recipe.

The contract under test: `pip install boostopt` ships the Modelfile but touches nothing (wheels
run no install-time code); `boostopt init` is what turns a bare Ollama into one that has our tag,
downloading only under `--pull`; and every failure path falls back to the BASE model so a project
is never left configured for something that doesn't exist.

Ollama is mocked throughout — no daemon, no `ollama` binary, no gigabytes.
"""
import pytest

from boostopt.runtime import llm, provision

BRANDED = "boostopt2.5-coder:7b"
BASE = "qwen2.5-coder:7b"
HOST = "http://127.0.0.1:11434"


# --- the bundled recipe (must survive packaging) ----------------------------

def test_modelfile_is_bundled_and_names_its_base():
    """If this fails, the wheel lost the Modelfile and `init` can only ever use the base."""
    assert provision.has_bundled_modelfile(BRANDED)
    assert provision.base_model(BRANDED) == BASE


def test_provenance_attribution_is_intact():
    """Apache-2.0: the Qwen credit in the header is a license obligation, not a comment."""
    with provision.bundled_modelfile(BRANDED) as p:
        body = p.read_text(encoding="utf-8")
    assert "Apache-2.0" in body and "Qwen2.5-Coder" in body


def test_a_user_supplied_model_is_not_ours():
    assert not provision.has_bundled_modelfile("llama3:8b")
    assert provision.base_model("llama3:8b") is None


def test_the_config_default_is_the_model_we_can_build():
    """The default must be a tag `init` knows how to produce — otherwise a fresh install
    points at a model nothing creates."""
    from boostopt.engine.config import Config
    assert Config().llm_model == BRANDED
    assert provision.has_bundled_modelfile(Config().llm_model)


# --- harness ----------------------------------------------------------------

@pytest.fixture
def ollama(monkeypatch):
    """A fake Ollama: `present` is the set of pulled tags, `calls` records the CLI we'd run.
    `ollama pull X` adds X; `ollama create X` adds X (as a re-tag would)."""
    class Fake:
        def __init__(self):
            self.present, self.calls, self.on_path, self.fail = set(), [], True, set()

        def status(self, host, model, **k):
            return llm.OllamaStatus(self.reachable, model in self.present)

        reachable = True

        def run(self, argv):
            self.calls.append(argv)
            verb, tag = argv[1], argv[2]
            if verb in self.fail:
                return False
            self.present.add(tag)
            return True

    f = Fake()
    monkeypatch.setattr(llm, "ollama_status", f.status)
    monkeypatch.setattr(provision, "_run", f.run)
    monkeypatch.setattr(provision.shutil, "which",
                        lambda n: "/usr/bin/ollama" if f.on_path else None)
    return f


def _quiet(msg, **k):     # provisioning prints; tests assert on the result, not the noise
    pass


def _ensure(pull=False):
    return provision.ensure_local_model(HOST, BRANDED, pull=pull, emit=_quiet)


# --- the paths --------------------------------------------------------------

def test_already_built_is_a_no_op(ollama):
    ollama.present = {BRANDED, BASE}
    got = _ensure()
    assert (got.model, got.ready, got.built) == (BRANDED, True, False)
    assert ollama.calls == []                     # nothing pulled, nothing rebuilt


def test_base_present_retags_without_downloading(ollama):
    """The everyday case: Ollama already has Qwen, so our tag costs seconds and zero bytes —
    and needs no --pull, because nothing is downloaded."""
    ollama.present = {BASE}
    got = _ensure(pull=False)
    assert (got.model, got.ready, got.built) == (BRANDED, True, True)
    assert ollama.calls == [["ollama", "create", BRANDED, "-f", ollama.calls[0][4]]]
    assert ollama.calls[0][4].endswith("boostopt2.5-coder.Modelfile")


def test_without_pull_a_missing_base_is_never_downloaded(ollama):
    """`init` must not turn into a multi-GB download by surprise — and it must leave the
    project on the base tag, which one `ollama pull` satisfies."""
    ollama.present = set()
    got = _ensure(pull=False)
    assert (got.model, got.ready, got.built) == (BASE, False, False)
    assert ollama.calls == []


def test_pull_downloads_the_base_then_builds_our_tag(ollama):
    ollama.present = set()
    got = _ensure(pull=True)
    assert (got.model, got.ready, got.built) == (BRANDED, True, True)
    assert [c[:3] for c in ollama.calls] == [["ollama", "pull", BASE],
                                             ["ollama", "create", BRANDED]]


def test_a_failed_base_pull_falls_back_to_the_base_tag(ollama):
    ollama.present, ollama.fail = set(), {"pull"}
    got = _ensure(pull=True)
    assert (got.model, got.ready, got.built) == (BASE, False, False)


def test_a_failed_create_falls_back_to_the_base_tag(ollama):
    ollama.present, ollama.fail = {BASE}, {"create"}
    got = _ensure(pull=True)
    assert got.model == BASE and got.built is False


def test_no_ollama_cli_falls_back_to_the_base_tag(ollama):
    ollama.present, ollama.on_path = {BASE}, False
    got = _ensure(pull=True)
    assert (got.model, got.ready) == (BASE, True)     # base IS pulled, we just can't re-tag
    assert ollama.calls == []


def test_no_daemon_falls_back_to_the_base_tag(ollama):
    ollama.reachable = False
    got = _ensure(pull=True)
    assert (got.model, got.ready) == (BASE, False)
    assert ollama.calls == []


def test_a_user_supplied_model_keeps_the_plain_pull_path(ollama):
    """No recipe for `llama3:8b` — we pull the name as given and never invent a re-tag."""
    ollama.present = set()
    got = provision.ensure_local_model(HOST, "llama3:8b", pull=True, emit=_quiet)
    assert (got.model, got.ready, got.built) == ("llama3:8b", True, False)
    assert [c[:3] for c in ollama.calls] == [["ollama", "pull", "llama3:8b"]]


# --- installing Ollama itself (opt-in, --install-ollama) --------------------
#
# The safety properties matter more than the happy path: this shells out to a vendor script as
# root, so "when does it NOT run" is the part worth pinning.

@pytest.fixture
def installer(monkeypatch, ollama):
    """Ollama absent from PATH; record whether the vendor installer was invoked."""
    ollama.reachable, ollama.on_path = False, False
    calls = []

    def fake_shell(cmd):
        calls.append(cmd)
        ollama.reachable, ollama.on_path = True, True     # a successful install brings it up
        return True

    monkeypatch.setattr(provision, "_run_shell", fake_shell)
    monkeypatch.setattr(provision.time, "sleep", lambda s: None)
    return calls


def _tty(monkeypatch, answer):
    monkeypatch.setattr(provision.sys, "stdin", type("S", (), {"isatty": staticmethod(lambda: True)}))
    monkeypatch.setattr("builtins.input", lambda _: answer)


def test_plain_pull_never_installs_ollama(installer, monkeypatch):
    """The whole point of the flag: a developer typing the ordinary command is never dropped
    into a sudo prompt."""
    _tty(monkeypatch, "y")                       # even with a user who WOULD say yes
    got = provision.ensure_local_model(HOST, BRANDED, pull=True, emit=_quiet)
    assert installer == []
    assert got.model == BASE and got.ready is False


def test_declining_the_prompt_installs_nothing(installer, monkeypatch):
    _tty(monkeypatch, "n")
    got = provision.ensure_local_model(HOST, BRANDED, pull=True, install=True, emit=_quiet)
    assert installer == []
    assert got.model == BASE


def test_a_non_tty_is_never_taken_as_consent(installer, monkeypatch):
    """CI, a pipe, a git hook — nothing that can't be asked may be assumed to have said yes."""
    monkeypatch.setattr(provision.sys, "stdin",
                        type("S", (), {"isatty": staticmethod(lambda: False)}))
    got = provision.ensure_local_model(HOST, BRANDED, pull=True, install=True, emit=_quiet)
    assert installer == []
    assert got.model == BASE


def test_confirmed_install_then_builds_the_model(installer, monkeypatch):
    _tty(monkeypatch, "y")
    got = provision.ensure_local_model(HOST, BRANDED, pull=True, install=True, emit=_quiet)
    assert installer and "ollama.com/install.sh" in installer[0]
    assert (got.model, got.ready, got.built) == (BRANDED, True, True)


def test_a_daemon_that_is_down_is_not_a_missing_install(ollama, monkeypatch):
    """Ollama on PATH but not answering → tell them to start it, never re-install it."""
    ollama.reachable, ollama.on_path = False, True
    _tty(monkeypatch, "y")
    got = provision.ensure_local_model(HOST, BRANDED, pull=True, install=True, emit=_quiet)
    assert got.model == BASE and ollama.calls == []


def test_install_command_is_never_run_on_an_unsupported_platform(monkeypatch, ollama):
    monkeypatch.setattr(provision.sys, "platform", "win32")
    cmd, runnable = provision.install_command()
    assert not runnable and "ollama.com" in cmd
    _tty(monkeypatch, "y")
    assert provision.install_ollama(HOST, emit=_quiet) is False


# --- end to end through `boostopt init` -------------------------------------

def test_init_builds_the_model_and_records_it(tmp_path, monkeypatch, ollama):
    from boostopt.surfaces.cli.main import _init
    monkeypatch.chdir(tmp_path)
    ollama.present = {BASE}
    assert _init() == 0
    cfg = (tmp_path / ".boostopt.toml").read_text(encoding="utf-8")
    assert f'llm_model    = "{BRANDED}"' in cfg
    assert BRANDED in ollama.present


def test_a_fallback_never_leaks_into_the_committed_config(tmp_path, monkeypatch, ollama):
    """Intent vs reality. `.boostopt.toml` is committed and shared, so it records what the project
    WANTS regardless of this machine's state; only the git-ignored pointer records the fallback.

    Putting the fallback in the .toml would be self-perpetuating — Config.load reads it back, so
    the next `init --pull` would request the fallback and never build the real model again."""
    from boostopt.engine import workspace
    from boostopt.surfaces.cli.main import _init
    monkeypatch.chdir(tmp_path)
    ollama.present = set()                       # no base, and no --pull
    assert _init() == 0
    assert f'llm_model    = "{BRANDED}"' in (tmp_path / ".boostopt.toml").read_text(encoding="utf-8")
    assert workspace.read_model(tmp_path / ".boostopt")["model"] == BASE


def test_init_upgrades_a_stale_pointer_left_by_an_earlier_fallback(tmp_path, monkeypatch, ollama):
    """First run has no base and no --pull → records the base. A later run builds our tag, and
    the pointer must FOLLOW — `.boostopt/model` describes what init prepared, and a workspace
    that predates a rename (or a failed run) otherwise reports the wrong model forever."""
    from boostopt.engine import workspace
    from boostopt.surfaces.cli.main import _init
    monkeypatch.chdir(tmp_path)

    ollama.present = set()
    _init()                                                  # falls back
    assert workspace.read_model(tmp_path / ".boostopt")["model"] == BASE

    ollama.present = {BASE}
    _init()                                                  # now buildable
    assert workspace.read_model(tmp_path / ".boostopt")["model"] == BRANDED


def test_init_does_not_clobber_an_existing_model_pointer(tmp_path, monkeypatch, ollama):
    from boostopt.engine import workspace
    from boostopt.surfaces.cli.main import _init
    monkeypatch.chdir(tmp_path)
    workspace.init(tmp_path, model="llama3:8b", host=HOST)   # a previous, deliberate choice
    ollama.present = set()
    assert _init() == 0
    assert workspace.read_model(tmp_path / ".boostopt")["model"] == "llama3:8b"


if __name__ == "__main__":
    import sys
    sys.exit("run via pytest (uses tmp_path/monkeypatch fixtures)")
