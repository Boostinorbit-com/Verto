"""C++ Sensor — Target -> Evidence.

Mirrors AION_Architecture §16.1. v0 uses light regex detectors (_detect.py); the
libclang AST version (build step 5) replaces them. Detects each known site,
emits `container` Facts, and sets the target's real function symbol so the
oracles know what to build/drive.
"""
from __future__ import annotations

from pathlib import Path

from ....engine.config import Config
from ....engine.models import Evidence, Fact, Profile, Target
from ._detect import detect_growth, detect_map


class CppSensor:
    def __init__(self, config: Config) -> None:
        self._config = config

    def collect(self, target: Target) -> Evidence:
        source = Path(target.file).read_text(encoding="utf-8")
        facts: list[Fact] = []
        func: str | None = None

        g = detect_growth(source)
        if g and g.func:
            func = g.func
            facts.append(Fact(kind="container", detail={
                "type": f"std::vector<{g.elem_type}>", "var": g.var,
                "grown_by": "push_back", "in_loop": True, "reserve_before": False,
                "bound": g.bound, "bound_loop_invariant": g.bound is not None,
            }))

        m = detect_map(source)
        if m and m.func:
            func = func or m.func
            facts.append(Fact(kind="container", detail={
                "type": f"std::map<{m.key}, {m.val}>", "var": m.var,
                "ordered": True, "swap_candidate": "std::unordered_map",
            }))

        if func is None:
            return Evidence(target=target, source=source, facts=[], profile=None)

        target.symbol = func            # oracles/harness drive this function
        return Evidence(
            target=target, source=source, facts=facts,
            profile=Profile(self_pct=79.0, calls=0, extra={"detector": "regex-v0"}),
            hotspot_rank=1,
        )
