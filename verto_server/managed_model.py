"""Managed-model capability — run VERTO's CORE engine on OUR compute with a curated model.

This is the ONE-WAY dependency in action: we IMPORT the free-tier engine and reuse it verbatim
(same gate, same proof) — the only differences are (a) it runs on our hardware and (b) the SERVER
picks the model (the entitlement decides), not the user. No engine code is duplicated.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from verto.engine.api import Engine        # ◀── the shared core (the free tier's own engine)
from verto.engine.config import Config

from .entitlement import Entitlement


def optimize_hosted(source: str, filename: str, ent: Entitlement) -> list[dict]:
    """Optimize `source` on our compute under plan `ent`, returning JSON-able verdicts.

    ⚠ SECURITY (production TODO): this compiles + RUNS user-supplied code. The free engine already
    sandboxes its child processes (item #13), but a multi-tenant host must ALSO isolate each
    request in its own container/VM with no shared FS and no network egress. Do not run this
    open to the internet as-is.
    """
    cfg = Config()
    cfg.model = ent.model or "rules"           # the SERVER chooses the proposer, not the caller
    if ent.llm_model:
        cfg.llm_model = ent.llm_model          # ...and the managed model name (server-side only)

    with tempfile.TemporaryDirectory(prefix="verto-hosted-") as d:
        fp = Path(d) / (Path(filename or "input.cpp").name)
        fp.write_text(source, encoding="utf-8")
        verdicts = Engine(cfg).analyze(str(fp))   # SAME gate, SAME verify-or-skip — on our box
    return [_verdict_json(v) for v in verdicts]


def _verdict_json(v) -> dict:
    perf = v.performance.vector if v.performance else {}
    tx = getattr(v.candidate, "transform", None)
    return {
        "function": getattr(tx, "target_func", None) or getattr(tx, "name", None),
        "accepted": v.accepted,
        "reason": v.reason,
        "p50_delta_pct": round(perf.get("p50_delta_pct", 0.0), 1),
        "rung": v.correctness.rung if v.correctness else None,
        "diff": v.udiff,
    }
