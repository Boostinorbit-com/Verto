"""Human render hides internal no-op rejects (mutation_failed / precondition_failed) — they
read like errors but mean "the proposer had nothing more to add," not a gate rejection. A REAL
gate reject ("not faster", correctness) stays visible; the ledger/--json keep everything.
"""
from types import SimpleNamespace as NS

from verto.surfaces.cli.render import _render_human, set_color


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
    from verto.surfaces.cli.render import _render_codebase
    acc = NS(accepted=True, applied=False, reason="accepted",
             candidate=NS(transform=NS(name="reserve", target_func="f")),
             performance=NS(vector={"p50_delta_pct": 42.0}), tests_confirmed=False,
             diff="--- a/x.cpp\n+++ b/x.cpp\n@@ -1,2 +1,3 @@\n+    out.reserve(n);\n")
    results = [("x.cpp", [acc], None, [])]
    _render_codebase(results, show_diff=False)
    assert "out.reserve(n)" not in capsys.readouterr().out       # default: summary only
    _render_codebase(results, show_diff=True)
    assert "out.reserve(n)" in capsys.readouterr().out           # --diff: the change is shown


if __name__ == "__main__":
    import sys
    sys.exit("run via pytest (uses capsys)")
