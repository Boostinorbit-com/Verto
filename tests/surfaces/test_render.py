"""Human render hides internal no-op rejects (mutation_failed / precondition_failed) — they
read like errors but mean "the proposer had nothing more to add," not a gate rejection. A REAL
gate reject ("not faster", correctness) stays visible; the ledger/--json keep everything.
"""
from types import SimpleNamespace as NS

from boostopt.surfaces.cli.render import _render_human, set_color


def _v(accepted, reason, applied=False):
    cand = NS(transform=NS(name="llm_rewrite"), rationale="LLM rewrite (qwen3:1.7b)")
    return NS(accepted=accepted, reason=reason, candidate=cand,
              correctness=None, performance=None, applied=applied, diff=None)


def setup_function():
    set_color(False)          # no ANSI codes in the assertions


def test_noop_rejects_are_hidden_after_a_win(capsys):
    _render_human([_v(True, "accepted", applied=True),
                   _v(False, "mutation_failed"), _v(False, "mutation_failed")])
    out = capsys.readouterr().out
    assert "ACCEPT" in out and "applied to source" in out
    assert "mutation_failed" not in out and "REJECT" not in out   # the noise is gone


def test_only_noop_reads_as_no_opportunity(capsys):
    _render_human([_v(False, "mutation_failed")])
    assert "no verified opportunity found" in capsys.readouterr().out


def test_real_gate_reject_is_still_shown(capsys):
    _render_human([_v(False, "not_faster")])
    out = capsys.readouterr().out
    assert "REJECT" in out and "not_faster" in out               # the gate's work stays visible


def test_codebase_diff_shown_only_with_flag(capsys):
    """--diff must work in codebase (directory) mode too, not just single-file."""
    from boostopt.surfaces.cli.render import _render_codebase
    acc = NS(accepted=True, applied=False, reason="accepted",
             candidate=NS(transform=NS(name="reserve", target_func="f")),
             performance=NS(vector={"p50_delta_pct": 42.0}), tests_confirmed=False,
             diff="--- a/x.cpp\n+++ b/x.cpp\n@@ -1,2 +1,3 @@\n+    out.reserve(n);\n")
    results = [("x.cpp", [acc], None, [])]
    _render_codebase(results, show_diff=False)
    assert "out.reserve(n)" not in capsys.readouterr().out       # default: summary only
    _render_codebase(results, show_diff=True)
    assert "out.reserve(n)" in capsys.readouterr().out           # --diff: the change is shown


def test_fail_on_gate_exit_codes():
    """#18: --fail-on remaps the exit code so a run is CI-actionable."""
    from boostopt.surfaces.cli.render import _fail_on_exit
    # 'any' — fail (exit 1) only when a verified optimization exists to take.
    assert _fail_on_exit("any", accepted=True) == 1
    assert _fail_on_exit("any", accepted=False) == 0
    # 'none' — always pass; findings are advisory.
    assert _fail_on_exit("none", accepted=True) == 0
    assert _fail_on_exit("none", accepted=False) == 0


def test_legacy_exit_codes_unchanged_without_flag():
    """Absent --fail-on, the default codes must be untouched (0=found/1=none/3=rejected)."""
    from boostopt.surfaces.cli.render import _codebase_exit, _exit_code
    assert _exit_code([]) == 1
    assert _exit_code([_v(True, "accepted")]) == 0
    assert _exit_code([_v(False, "not_faster")]) == 3
    assert _codebase_exit([("x.cpp", [_v(True, "accepted")], None, [])]) == 0
    assert _codebase_exit([("x.cpp", [_v(False, "not_faster")], None, [])]) == 3
    assert _codebase_exit([("x.cpp", [], None, [])]) == 1


def test_fail_on_choices_are_restricted():
    """argparse rejects an unknown --fail-on value (guards against silent typos in CI yaml)."""
    import pytest

    from boostopt.surfaces.cli.parser import _parser
    with pytest.raises(SystemExit):
        _parser().parse_args(["optimize", "x.cpp", "--fail-on", "regression"])


if __name__ == "__main__":
    import sys
    sys.exit("run via pytest (uses capsys)")
