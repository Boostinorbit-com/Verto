"""Managed-model capability — run BOOSTOPT's CORE engine on OUR compute with a curated model.

This is the ONE-WAY dependency in action: we IMPORT the free-tier engine and reuse it verbatim
(same gate, same proof) — the only differences are (a) it runs on our hardware and (b) the SERVER
picks the model (the entitlement decides), not the user. No engine code is duplicated.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from boostopt.engine.api import Engine        # ◀── the shared core (the free tier's own engine)
from boostopt.engine.config import Config

from .entitlement import Entitlement


def _apply_safe_prefs(cfg: Config, options: dict) -> None:
    """Apply client preferences that can only make the check STRICTER or add more checking — never
    weaker. The client is untrusted, so we ENFORCE the safe direction here (server-side):
      • min_speedup_pct  → can only be RAISED (max) — a higher bar is always safe.
      • metamorphic      → can only be turned ON — extra checking is always safe.
      • candidates       → clamped to a small max — a preference, bounded so it can't abuse compute.
    Gate-weakening knobs (min_rung down, --fast, sandbox off, model choice) are NOT accepted here."""
    sp = options.get("min_speedup_pct")
    if isinstance(sp, (int, float)):
        cfg.min_speedup_pct = max(cfg.min_speedup_pct, float(sp))
    if options.get("metamorphic"):
        cfg.metamorphic = True
    c = options.get("candidates")
    if isinstance(c, int) and c > 0:
        cfg.candidates = min(c, 8)


def optimize_hosted(source: str, filename: str, ent: Entitlement,
                    apply: bool = False, options: dict | None = None) -> tuple[list[dict], str | None]:
    """Optimize `source` on our compute under plan `ent`. Returns (verdicts, final_source).

    `apply=True` runs the full apply loop on OUR temp copy (multi-hotspot, re-verified) and returns
    the fully-optimized file as `final_source`, so the client can write it locally. `apply=False`
    (dry-run) returns verdicts + `final_source=None`.

    ⚠ SECURITY (production TODO): this compiles + RUNS user-supplied code. The free engine already
    sandboxes its child processes (item #13), but a multi-tenant host must ALSO isolate each
    request in its own container/VM with no shared FS and no network egress. Do not run this
    open to the internet as-is.
    """
    cfg = Config()
    cfg.model = ent.model or "rules"           # the SERVER chooses the proposer, not the caller
    if ent.llm_model:
        cfg.llm_model = ent.llm_model          # ...and the managed model name (server-side only)
    _apply_safe_prefs(cfg, options or {})      # client may only tighten the check, never weaken it

    with tempfile.TemporaryDirectory(prefix="boostopt-hosted-") as d:
        fp = Path(d) / (Path(filename or "input.cpp").name)
        fp.write_text(source, encoding="utf-8")
        eng = Engine(cfg)
        if apply:                              # SAME gate — write the sound wins to our temp copy…
            verdicts = eng.optimize(str(fp), apply=True)
            final = fp.read_text(encoding="utf-8")   # …then hand the finished file back to the client
        else:
            verdicts = eng.analyze(str(fp))    # dry-run: verify-or-skip, no writes
            final = None
    return [_verdict_json(v) for v in verdicts], final


def _verdict_json(v) -> dict:
    perf = v.performance.vector if v.performance else {}
    tx = getattr(v.candidate, "transform", None)
    return {
        "function": getattr(tx, "target_func", None) or getattr(tx, "name", None),
        "accepted": v.accepted,
        "reason": v.reason,
        "p50_ms": round(perf.get("p50", 0.0), 4),
        "p50_delta_pct": round(perf.get("p50_delta_pct", 0.0), 1),
        "rung": v.correctness.rung if v.correctness else None,
        "diff": v.udiff,
    }
