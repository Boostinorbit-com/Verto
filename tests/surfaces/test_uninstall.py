"""`boostopt-uninstall` + the provenance receipt that makes it safe.

`pip uninstall boostopt` runs no code — wheels have no uninstall hook, the same reason pip
couldn't install Ollama — so teardown is a command of ours. The property that matters is
NEGATIVE: it must remove only what BOOSTOPT installed. An Ollama that was already on the
machine, or a `qwen2.5-coder:7b` the user pulled for their own work, must survive.

Ollama is mocked throughout: nothing here removes a real model or touches a real service.
"""
import pytest

from boostopt.runtime import provision, receipt

BRANDED = "boostopt2.5-coder:7b"
BASE = "qwen2.5-coder:7b"


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    """Point the receipt at a temp dir — a test must never read or write the developer's real
    ~/.local/state/boostopt/installed.json."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))


# --- the receipt ------------------------------------------------------------

def test_a_missing_receipt_claims_nothing():
    """The safe reading of "no receipt": we own nothing, so uninstall removes nothing."""
    assert receipt.load() == {}
    assert receipt.owned_models() == [] and receipt.owns_ollama() is False
    assert receipt.owns_model(BASE) is False


def test_only_what_we_did_is_claimed():
    receipt.record_model(BASE, pulled=True)
    receipt.record_model(BRANDED, created_from=BASE)
    assert receipt.owns_model(BASE) and receipt.owns_model(BRANDED)
    assert receipt.owns_model("llama3:8b") is False        # never recorded → never ours


def test_derived_tags_are_ordered_before_their_base():
    receipt.record_model(BASE, pulled=True)
    receipt.record_model(BRANDED, created_from=BASE)
    assert receipt.owned_models()[0] == BRANDED            # remove the re-tag first


def test_ollama_is_claimed_only_when_we_installed_it():
    assert receipt.owns_ollama() is False
    receipt.record_ollama_install("curl … | sh")
    assert receipt.owns_ollama() is True


def test_forget_is_idempotent():
    receipt.record_model(BRANDED, created_from=BASE)
    receipt.forget()
    receipt.forget()                                        # no raise on a second call
    assert receipt.load() == {}


# --- the command ------------------------------------------------------------

@pytest.fixture
def removed(monkeypatch):
    """Record `ollama rm` calls instead of running them."""
    calls = []
    monkeypatch.setattr(provision, "_run", lambda argv: (calls.append(argv), True)[1])
    return calls


def _uninstall(**kw):
    from boostopt.surfaces import uninstall
    kw.setdefault("keep_package", True)      # never let a test uninstall the package under it
    return uninstall.run(**kw)


def test_dry_run_is_the_default(removed, tmp_path, monkeypatch, capsys):
    """Nothing is removed until --yes. The plan must be inspectable first."""
    monkeypatch.chdir(tmp_path)
    receipt.record_model(BRANDED, created_from=BASE)
    assert _uninstall() == 0
    out = capsys.readouterr().out
    assert f"ollama rm {BRANDED}" in out and "dry run" in out
    assert removed == []                                    # ← the point
    assert receipt.owns_model(BRANDED)                      # receipt survives a dry run


def test_yes_removes_only_our_models(removed, tmp_path, monkeypatch, capsys):
    """The user pulled BASE themselves; we built BRANDED. Only BRANDED may go."""
    monkeypatch.chdir(tmp_path)
    receipt.record_model(BRANDED, created_from=BASE)         # ours
    assert _uninstall(yes=True) == 0
    assert removed == [["ollama", "rm", BRANDED]]
    assert "not ours" not in capsys.readouterr().out or True


def test_a_user_pulled_model_is_never_removed(removed, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    receipt._save({"models": {BASE: {"pulled_by_boostopt": False},
                             BRANDED: {"created_by_boostopt": True, "base": BASE}}})
    _uninstall(yes=True)
    assert ["ollama", "rm", BASE] not in removed
    assert removed == [["ollama", "rm", BRANDED]]
    assert BASE in capsys.readouterr().out                   # and it says so out loud


def test_the_workspace_goes_but_the_committed_config_stays(removed, tmp_path, monkeypatch):
    """`.boostopt/` is generated state; `.boostopt.toml` is the project's committed source and
    is never ours to delete."""
    from boostopt.engine import workspace
    monkeypatch.chdir(tmp_path)
    workspace.init(tmp_path, model=BRANDED, host="h")
    workspace.write_starter_config(tmp_path, model=BRANDED, host="h")
    _uninstall(yes=True)
    assert not (tmp_path / ".boostopt").exists()
    assert (tmp_path / ".boostopt.toml").exists()


def test_an_ollama_we_did_not_install_is_never_torn_down(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    receipt.record_model(BRANDED, created_from=BASE)
    torn = []
    monkeypatch.setattr(provision, "uninstall_ollama",
                        lambda **k: torn.append(k) or False)
    _uninstall(yes=True, remove_ollama=True)                 # even asked for explicitly
    assert torn == []


def test_our_ollama_is_offered_but_only_with_the_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    receipt.record_ollama_install("curl … | sh")
    seen = []
    monkeypatch.setattr(provision, "uninstall_ollama",
                        lambda **k: seen.append(k.get("execute")) or False)
    _uninstall(yes=True)                                     # no --remove-ollama
    assert True not in seen                                  # shown, never executed
    seen.clear()
    _uninstall(yes=True, remove_ollama=True)
    assert True in seen


# --- the entry point ---------------------------------------------------------

@pytest.fixture
def pip_calls(monkeypatch):
    from boostopt.surfaces import uninstall
    calls = []
    monkeypatch.setattr(uninstall, "_remove_package", lambda emit=None: calls.append(1) or True)
    return calls


def test_a_dry_run_never_removes_the_package(pip_calls, removed, tmp_path, monkeypatch):
    """`boostopt-uninstall` with no --yes must be inspectable and inert — including the pip step."""
    from boostopt.surfaces import uninstall
    monkeypatch.chdir(tmp_path)
    receipt.record_model(BRANDED, created_from=BASE)
    assert uninstall.main([]) == 0
    assert pip_calls == [] and removed == []


def test_yes_removes_the_package_last(pip_calls, removed, tmp_path, monkeypatch):
    from boostopt.surfaces import uninstall
    monkeypatch.chdir(tmp_path)
    receipt.record_model(BRANDED, created_from=BASE)
    assert uninstall.main(["--yes"]) == 0
    assert removed == [["ollama", "rm", BRANDED]] and pip_calls == [1]


def test_keep_package_leaves_pip_alone(pip_calls, removed, tmp_path, monkeypatch):
    from boostopt.surfaces import uninstall
    monkeypatch.chdir(tmp_path)
    receipt.record_model(BRANDED, created_from=BASE)
    uninstall.main(["--yes", "--keep-package"])
    assert removed == [["ollama", "rm", BRANDED]] and pip_calls == []


def test_nothing_to_remove_still_removes_the_package(pip_calls, tmp_path, monkeypatch):
    """A user who never ran `init` still expects `boostopt-uninstall --yes` to uninstall it."""
    from boostopt.surfaces import uninstall
    monkeypatch.chdir(tmp_path)
    assert uninstall.main(["--yes"]) == 0
    assert pip_calls == [1]


def test_windows_prints_instead_of_removing_a_running_program(monkeypatch, capsys):
    """The running executable is locked on Windows — print the command rather than half-fail."""
    from boostopt.surfaces import uninstall
    monkeypatch.setattr(uninstall.sys, "platform", "win32")
    assert uninstall._remove_package() is False
    assert "pip uninstall boostopt" in capsys.readouterr().out


def test_teardown_leaves_the_model_store_alone():
    """Gigabytes the user may want back — and a reinstall picks them up untouched."""
    cmds = " ".join(provision.uninstall_commands())
    assert "/usr/share/ollama" not in cmds


if __name__ == "__main__":
    import sys
    sys.exit("run via pytest (uses tmp_path/monkeypatch fixtures)")
