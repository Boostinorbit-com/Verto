"""The persisted regression floor (`.boostopt/baselines/`).

The point of a floor is that it only fires when code we ALREADY optimized got slow
again — so most of these tests are about when it must stay quiet.
"""
from __future__ import annotations

import json
from pathlib import Path

from boostopt.engine.baselines import Baselines
from boostopt.engine.models import (Candidate, CorrectnessVerdict, PerfVerdict, Target,
                                    Verdict, Witness)


def _target(file="a.cpp", symbol="hot", language="cpp"):
    return Target(file=file, symbol=symbol, line=1, language=language)


def _verdict(p50, before=None, accepted=True, rung=3):
    vec = {"p50": p50}
    if before is not None:
        vec["p50_before"] = before
    return Verdict(accepted, None,
                   CorrectnessVerdict(rung=rung, passed=True, witness=Witness()),
                   PerfVerdict(vector=vec, pareto_pass=True), reason="accepted")


def test_disabled_without_a_workspace():
    """No `boostopt init` → no floor, and nothing blows up."""
    b = Baselines(None)
    assert b.record(_target(), _verdict(1.0), applied=True) is False
    assert b.lookup(_target()) is None
    assert b.check(_target(), {"p50_before": 99.0}) == ""


def test_records_an_applied_accept(tmp_path: Path):
    b = Baselines(tmp_path)
    assert b.record(_target(), _verdict(2.0, before=8.0), applied=True) is True
    entry = b.lookup(_target())
    assert entry["p50"] == 2.0 and entry["applied"] is True
    assert entry["origin_p50"] == 8.0
    # stored where a human can read it
    assert json.loads((tmp_path / "cpp.json").read_text())["a.cpp::hot"]["symbol"] == "hot"


def test_rejects_are_never_floors(tmp_path: Path):
    b = Baselines(tmp_path)
    assert b.record(_target(), _verdict(2.0, accepted=False), applied=True) is False
    assert b.lookup(_target()) is None


def test_floor_only_improves(tmp_path: Path):
    """A later, slower accept must not raise the floor — otherwise the floor drifts
    upward and silently stops catching regressions."""
    b = Baselines(tmp_path)
    b.record(_target(), _verdict(2.0), applied=True)
    assert b.record(_target(), _verdict(5.0), applied=True) is False
    assert b.lookup(_target())["p50"] == 2.0
    assert b.record(_target(), _verdict(1.5), applied=True) is True
    assert b.lookup(_target())["p50"] == 1.5


def test_unapplied_accept_does_not_arm_the_check(tmp_path: Path):
    """A dry run proves a number but writes nothing. The original still being slower
    than that number is the win still being AVAILABLE — not a regression."""
    b = Baselines(tmp_path)
    b.record(_target(), _verdict(2.0), applied=False)
    assert b.lookup(_target())["applied"] is False
    assert b.check(_target(), {"p50_before": 8.0}) == ""


def test_applying_later_arms_an_existing_floor(tmp_path: Path):
    b = Baselines(tmp_path)
    b.record(_target(), _verdict(2.0), applied=False)
    assert b.record(_target(), _verdict(2.0), applied=True) is True   # same floor, now written
    assert b.lookup(_target())["applied"] is True
    assert "regressed vs baseline" in b.check(_target(), {"p50_before": 8.0})


def test_quiet_when_code_still_meets_its_floor(tmp_path: Path):
    b = Baselines(tmp_path)
    b.record(_target(), _verdict(2.0), applied=True)
    assert b.check(_target(), {"p50_before": 2.0}) == ""
    assert b.check(_target(), {"p50_before": 1.8}) == ""     # faster than the floor


def test_noise_does_not_trip_the_floor(tmp_path: Path):
    """1% slower is measurement noise on a real machine, not a regression."""
    b = Baselines(tmp_path)
    b.record(_target(), _verdict(2.0), applied=True)
    assert b.check(_target(), {"p50_before": 2.02}) == ""     # +1%
    assert b.check(_target(), {"p50_before": 2.10}) != ""     # +5%


def test_regression_note_reports_both_numbers(tmp_path: Path):
    b = Baselines(tmp_path)
    b.record(_target(), _verdict(2.0), applied=True)
    note = b.check(_target(), {"p50_before": 4.0})
    assert "2 ms" in note and "4 ms" in note and "100.0% slower" in note


def test_symbols_and_languages_are_separate(tmp_path: Path):
    b = Baselines(tmp_path)
    b.record(_target(symbol="hot"), _verdict(2.0), applied=True)
    assert b.lookup(_target(symbol="cold")) is None
    assert b.lookup(_target(language="python")) is None


def test_corrupt_file_never_breaks_a_run(tmp_path: Path):
    (tmp_path / "cpp.json").write_text("{not json")
    b = Baselines(tmp_path)
    assert b.lookup(_target()) is None
    assert b.check(_target(), {"p50_before": 9.0}) == ""
    assert b.record(_target(), _verdict(2.0), applied=True) is True   # recovers by rewriting


def test_missing_measurements_are_ignored(tmp_path: Path):
    b = Baselines(tmp_path)
    assert b.record(_target(), _verdict(0.0), applied=True) is False          # no usable p50
    b.record(_target(), _verdict(2.0), applied=True)
    assert b.check(_target(), {}) == ""                                       # no p50_before
    assert b.check(_target(), None) == ""
