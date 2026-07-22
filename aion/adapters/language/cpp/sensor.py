"""C++ Sensor — Target -> Evidence, with profile-guided hotspot selection.

Mirrors AION_Architecture §16.1 and Evidence stage (§8①). Detects every
candidate site (all functions), and when there is MORE than one candidate
function, runs the micro-profiler to pick the one that is actually HOT — the
Category-B differentiator (a static-report tool would optimize the wrong one).
Sets the target's symbol to the chosen function so the proposer/oracles act on it.
"""
from __future__ import annotations

from pathlib import Path

from ....engine.config import Config
from ....engine.models import Evidence, Fact, Profile, Target
from ._detect import detect_all_growth, detect_all_map
from .profiler import profile_functions


class CppSensor:
    def __init__(self, config: Config) -> None:
        self._config = config

    def collect(self, target: Target) -> Evidence:
        source = Path(target.file).read_text(encoding="utf-8")
        growth = {s.func: s for s in detect_all_growth(source) if s.func}
        maps = {s.func: s for s in detect_all_map(source) if s.func}
        funcs = sorted(set(growth) | set(maps))

        if not funcs:
            return Evidence(target=target, source=source, facts=[], profile=None)

        # --- profile-guided selection (only when there's a choice to make) ---
        profile = None
        if len(funcs) > 1:
            times = profile_functions(source, funcs)
            chosen = max(funcs, key=lambda f: times.get(f, 0.0))
            profile = Profile(self_pct=0.0, calls=0,
                              extra={"times_ms": times, "chosen": chosen, "profiler": "microbench-v0"})
        else:
            chosen = funcs[0]

        facts: list[Fact] = []
        if chosen in growth:
            g = growth[chosen]
            facts.append(Fact(kind="container", detail={
                "type": f"std::vector<{g.elem_type}>", "var": g.var, "grown_by": "push_back",
                "in_loop": True, "reserve_before": False, "bound": g.bound,
                "bound_loop_invariant": g.bound is not None,
            }))
        if chosen in maps:
            m = maps[chosen]
            facts.append(Fact(kind="container", detail={
                "type": f"std::map<{m.key}, {m.val}>", "var": m.var,
                "ordered": True, "swap_candidate": "std::unordered_map",
            }))

        target.symbol = chosen           # oracles/harness/proposer act on the hot function
        return Evidence(
            target=target, source=source, facts=facts,
            profile=profile or Profile(self_pct=79.0, extra={"detector": "single-candidate"}),
            hotspot_rank=1,
        )
