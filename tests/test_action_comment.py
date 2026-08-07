"""#18 step 3 — PR/MR comment rendering + suggestion extraction (the pure half).

The GitHub posting in gh.py needs a real repo+token, so it isn't exercised here;
this covers everything that turns a verdict report into what a developer sees.
"""
import importlib.util
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MOD = os.path.join(_ROOT, "examples", "github-action", "comment.py")


def _load():
    spec = importlib.util.spec_from_file_location("boostopt_action_comment", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report():
    """One accepted reserve() finding, shaped like the real --json payload."""
    udiff = ("--- a/src/route.cpp\n+++ b/src/route.cpp\n"
             "@@ -10,6 +10,7 @@\n"
             " std::vector<int> route_costs(std::size_t n) {\n"
             "     std::vector<int> out;\n"
             "+    out.reserve(n);\n"
             "     for (std::size_t i = 0; i < n; ++i)\n"
             "-        out.push_back(point_weight(i) + (int)i);\n"
             "+        out.emplace_back(point_weight(i) + (int)i);\n"
             "     return out;\n }\n")
    v = {"accepted": True, "reason": "accepted", "applied": False, "via": "harness",
         "tests_confirmed": False,
         "candidate": {"transform": "reserve_before_pushback",
                       "rationale": "vector grown by push_back with no prior reserve()"},
         "correctness": {"rung": 3, "passed": True,
                         "witness": {"sanitizer": "clean", "inputs_run": 1010}},
         "performance": {"pareto_pass": True,
                         "vector": {"p50": 4.85, "p50_before": 10.06, "p50_delta_pct": 51.8}},
         "diff": udiff, "udiff": udiff}
    return [{"file": os.path.join(_ROOT, "src", "route.cpp"),
             "error": None, "skips": [], "verdicts": [v]}]


def test_summary_has_marker_header_table_and_diff():
    m = _load()
    out = m.render_comment(_report(), repo_root=_ROOT)
    assert out.startswith(m.MARKER)                       # editable in place
    assert "1 verified optimization" in out
    assert "src/route.cpp · route_costs()" in out         # rel path + sniffed function
    assert "**−52%**" in out                              # p50 delta, rounded
    assert "Rung 3" in out
    assert "```diff" in out and "out.reserve(n)" in out   # the change is shown
    assert "1,010 fuzzed inputs" in out                   # trust line


def test_blocking_header_explains_fail_on():
    m = _load()
    out = m.render_comment(_report(), repo_root=_ROOT, blocking=True)
    assert "❌" in out and "left unapplied" in out
    assert "fail-on: any" in out and "never correctness" in out


def test_no_findings_is_quiet():
    m = _load()
    clean = [{"file": "a.cpp", "error": None,
              "verdicts": [{"accepted": False, "reason": "skipped(sig)"}],
              "skips": []}]
    out = m.render_comment(clean, repo_root=_ROOT)
    assert out.startswith(m.MARKER)
    assert "no verified optimizations" in out
    assert "1 skipped" in out                             # disclosed, but quiet
    assert "```diff" not in out                           # no heavy content


def test_extract_suggestions_from_udiff():
    m = _load()
    sugg = m.extract_suggestions(_report(), repo_root=_ROOT)
    assert len(sugg) == 1
    s = sugg[0]
    assert s["path"] == os.path.join("src", "route.cpp")
    # new-side content only: context + additions, never the removed '-' line
    assert "out.reserve(n);" in s["suggestion"]
    assert "out.emplace_back" in s["suggestion"]
    assert "out.push_back(point_weight" not in s["suggestion"]
    assert "```suggestion" in s["body"] and "verified **−52%**" in s["body"]
    # anchored to the old-side line range the hunk covers
    assert s["start_line"] == 10 and s["line"] == 15


def test_parse_hunks_multiple():
    m = _load()
    ud = ("--- a/x\n+++ b/x\n"
          "@@ -1,2 +1,3 @@\n a\n+b\n c\n"
          "@@ -10,1 +11,1 @@\n-old\n+new\n")
    hunks = m._parse_hunks(ud)
    assert len(hunks) == 2
    assert hunks[0]["new_lines"] == ["a", "b", "c"]
    assert hunks[1]["new_lines"] == ["new"] and hunks[1]["old_start"] == 10
