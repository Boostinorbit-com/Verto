"""AION CLI — the v0 surface (a thin client over the Engine API).

Mirrors AION_Surfaces §3. Commands: analyze / optimize / report.
Exit codes: 0 verified change found · 1 nothing found · 2 error · 3 all rejected.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from ..engine.api import Engine
from ..engine.config import Config
from ..engine.models import Verdict


def _build_config(args) -> Config:
    cfg = Config.load(getattr(args, "config_file", None))
    if getattr(args, "offline", False):
        cfg.model = "rules"
    if getattr(args, "model", None):
        cfg.model = args.model
    if getattr(args, "min_rung", None) is not None:
        cfg.min_rung = args.min_rung
    return cfg


def _render_human(verdicts: list[Verdict]) -> None:
    if not verdicts:
        print("  no verified opportunity found.")
        return
    for v in verdicts:
        name = v.candidate.transform.name if v.candidate else "?"
        mark = "\033[32mACCEPT\033[0m" if v.accepted else f"\033[31mREJECT\033[0m ({v.reason})"
        print(f"\n  {name}  →  {mark}")
        if v.candidate:
            print(f"    rationale: {v.candidate.rationale}")
        if v.correctness:
            w = v.correctness.witness
            if w.first_divergence:
                detail = f"output differs — {w.first_divergence}"
            elif not w.build_ok:
                detail = "build failed"
            else:
                detail = w.sanitizer
            print(f"    correctness: Rung {v.correctness.rung} ({detail})")
        if v.performance:
            d = v.performance.vector.get("p50_delta_pct")
            print(f"    performance: p50 {v.performance.vector.get('p50')} ms "
                  f"({'-%.1f%%' % d if d else 'n/a'})  pareto={v.performance.pareto_pass}")


def _render_json(verdicts: list[Verdict]) -> None:
    def enc(o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return getattr(o, "name", str(o))       # render a Transform as its name
    print(json.dumps([enc(v) for v in verdicts], default=enc, indent=2))


def _exit_code(verdicts: list[Verdict]) -> int:
    if not verdicts:
        return 1
    if any(v.accepted for v in verdicts):
        return 0
    return 3


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aion", description="AION — verified performance optimizer")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("path")
        sp.add_argument("-p", "--compile-commands", dest="compile_commands")
        sp.add_argument("--profile")
        sp.add_argument("--model")
        sp.add_argument("--offline", action="store_true")
        sp.add_argument("--min-rung", type=int)
        sp.add_argument("--config-file")
        sp.add_argument("--json", action="store_true")

    common(sub.add_parser("analyze", help="detect + explain; writes nothing"))
    o = sub.add_parser("optimize", help="propose → verify → optionally apply")
    common(o)
    o.add_argument("--apply", action="store_true")
    sub.add_parser("report", help="read the Ledger")

    args = p.parse_args(argv)

    try:
        if args.cmd == "report":
            print(json.dumps(Engine().report(), indent=2))
            return 0

        engine = Engine(_build_config(args))
        if args.cmd == "analyze":
            verdicts = engine.analyze(args.path)
        else:
            verdicts = engine.optimize(args.path, apply=args.apply)

        (_render_json if args.json else _render_human)(verdicts)
        return _exit_code(verdicts)
    except (ValueError, NotImplementedError) as e:
        print(f"aion: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
