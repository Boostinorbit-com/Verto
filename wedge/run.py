"""Run the Wedge Test and print the scorecard.

Usage:  PYTHONPATH=. python3 -m wedge.run
"""
from __future__ import annotations

from aion.adapters.domain.performance.correctness import PerfCorrectnessOracle
from aion.adapters.domain.performance.inputs import HeldOutInputs
from aion.adapters.domain.performance.performance import PerformanceOracleImpl
from aion.engine.api import Engine
from aion.engine.config import Config
from aion.engine.gate import InvariantGate
from aion.engine.models import Candidate, Contract, Target, Variant

from .cases import CASES, Case

GRN, RED, DIM, BOLD, RST = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def _cfg() -> Config:
    c = Config()
    c.model = "rules"          # deterministic proposer (no LLM/API key needed)
    return c


def _run_pipeline(case: Case) -> tuple[bool, str]:
    verdicts = Engine(_cfg()).optimize(case.file, apply=False)
    if case.expect == "none":
        return (len(verdicts) == 0), ("no-opportunity" if not verdicts else f"{len(verdicts)} verdict(s)")
    if not verdicts:
        return False, "no-opportunity"
    v = verdicts[-1]
    if case.expect == "accept":
        chosen = getattr(v.candidate.transform, "target_func", None) if v.candidate else None
        actual = f"accept:{chosen}" if chosen else "accept"
        ok = v.accepted and (not case.expect_symbol or chosen == case.expect_symbol)
        return ok, actual
    actual = "accept" if v.accepted else f"reject:{v.reason}"
    return (not v.accepted and (not case.reason or case.reason in v.reason)), actual


def _run_gate(case: Case) -> tuple[bool, str]:
    cfg = Config()
    gate = InvariantGate(PerfCorrectnessOracle(cfg), PerformanceOracleImpl(cfg), cfg)
    orig = Target(file=case.file, symbol=case.symbol, line=0, language="cpp")
    var = Variant(target=orig, patch="", source_after=case.variant)
    cand = Candidate(transform=type("T", (), {"name": case.id})(), contract=Contract())
    v = gate.decide(orig, var, cand, HeldOutInputs(cfg))
    actual = "accept" if v.accepted else f"reject:{v.reason}"
    return (not v.accepted and (not case.reason or case.reason in v.reason)), actual


def main() -> int:
    print(f"\n{BOLD}AION — Wedge Test scorecard{RST}")
    print("AION is the judge; competitors (Codeflash / CompilerGPT) compared structurally.\n")
    header = f"  {'CASE':16} {'EXPECT':7} {'ACTUAL':22} {'RESULT':7} WHY IT'S A WEDGE"
    print(header)
    print("  " + "-" * (len(header) + 20))

    passed = total = 0
    last_cat = None
    for c in CASES:
        if c.category != last_cat:
            print(f"\n  {BOLD}{c.category}{RST}")
            last_cat = c.category

        if c.kind == "pending":
            print(f"    {DIM}{c.id:16} {c.expect:7} {'PENDING':22} {'—':7} {c.note}{RST}")
            continue

        ok, actual = (_run_pipeline if c.kind == "pipeline" else _run_gate)(c)
        total += 1
        passed += ok
        tag = f"{GRN}PASS{RST}" if ok else f"{RED}FAIL{RST}"
        print(f"    {c.id:16} {c.expect:7} {actual[:22]:22} {tag:7} {DIM}{c.gap}{RST}")

    print("\n  " + "-" * (len(header) + 20))
    verdict = f"{GRN}all matched{RST}" if passed == total else f"{RED}{total - passed} mismatch{RST}"
    print(f"  runnable cases: {passed}/{total} matched pre-registration   ({verdict})")
    pend = ", ".join(sorted({c.category.split()[0] for c in CASES if c.kind == "pending"}))
    print(f"  {DIM}pending categories: {pend or 'none'} (await further engine work).{RST}\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
