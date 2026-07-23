"""C++ Sensor — Target -> Evidence, with profile-guided hotspot selection.

Mirrors VERTO_Architecture §16.1 and Evidence stage (§8①). Detects every
candidate site (all functions), and when there is MORE than one candidate
function, runs the micro-profiler to pick the one that is actually HOT — the
Category-B differentiator (a static-report tool would optimize the wrong one).
Sets the target's symbol to the chosen function so the proposer/oracles act on it.
"""
from __future__ import annotations

from pathlib import Path

from ....engine.config import Config
from ....engine.models import Evidence, Fact, Profile, Skip, Target
from ...domain.performance.harness_gen import unsupported_reason
from ._detect import (
    detect_all_growth, detect_all_map, detect_all_string_growth,
    detect_parse_errors, detect_side_effect_reason, detect_template_candidates,
    set_parse_flags,
)
from .profile import load_profile
from .profiler import profile_functions


class CppSensor:
    def __init__(self, config: Config) -> None:
        self._config = config

    def collect(self, target: Target) -> Evidence:
        source = Path(target.file).read_text(encoding="utf-8")
        # codebase mode: parse this TU with its real compile_commands flags so
        # includes/defines/-std resolve (single-file mode leaves this empty).
        set_parse_flags(target.build.get("parse_flags"))
        growth = {s.func: s for s in detect_all_growth(source) if s.func}
        maps = {s.func: s for s in detect_all_map(source) if s.func}
        strs = {s.func: s for s in detect_all_string_growth(source) if s.func}

        # only candidates VERTO can actually harness AND soundly verify; the rest
        # are skipped honestly WITH A REASON (item #4) instead of silently dropped.
        # The cascade also enforces the correctness-completeness gates: a function
        # with un-modeled side effects (item #1c) is refused rather than "verified"
        # on stdout alone.
        skips: list[Skip] = []
        funcs: list[str] = []
        for f in sorted(set(growth) | set(maps) | set(strs)):
            reason = (unsupported_reason(source, f)                 # signature (harness_gen)
                      or detect_side_effect_reason(source, f))      # item #1c
            if reason is None:
                funcs.append(f)
            else:
                skips.append(Skip(func=f, stage="harness", reason=reason))
        # a TU that wouldn't parse looks empty — surface that, don't swallow it.
        for msg in detect_parse_errors(source):
            skips.append(Skip(func=Path(target.file).name, stage="parse", reason=msg))
        # optimizable function TEMPLATES can't be harnessed without instantiation —
        # name them, don't silently ignore them (item #1d).
        for t in detect_template_candidates(source):
            skips.append(Skip(func=t, stage="harness",
                              reason="template function — needs a concrete instantiation to verify"))

        if not funcs:
            return Evidence(target=target, source=source, facts=[], profile=None, skips=skips)

        # --- profile-guided selection (only when there's a choice to make) ---
        profile = None
        chosen = funcs[0]
        if len(funcs) > 1:
            real = load_profile(self._config.profile) if getattr(self._config, "profile", None) else {}
            if real and any(f in real for f in funcs):
                # REAL profile (perf/gprof/…) — optimize the function that's actually
                # hot in the user's workload, not a synthetic micro-benchmark (item #5).
                chosen = max(funcs, key=lambda f: real.get(f, 0.0))
                profile = Profile(self_pct=real.get(chosen, 0.0), calls=0,
                                  extra={"costs": {f: real.get(f, 0.0) for f in funcs},
                                         "chosen": chosen, "profiler": "external"})
            else:
                times = profile_functions(source, funcs)
                chosen = max(funcs, key=lambda f: times.get(f, 0.0))
                profile = Profile(self_pct=0.0, calls=0,
                                  extra={"times_ms": times, "chosen": chosen, "profiler": "microbench-v0"})

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
        if chosen in strs:
            sg = strs[chosen]
            facts.append(Fact(kind="container", detail={
                "type": "std::string", "var": sg.var, "grown_by": "+=",
                "in_loop": True, "reserve_before": False, "bound": sg.bound,
                "bound_loop_invariant": sg.bound is not None,
            }))

        target.symbol = chosen           # oracles/harness/proposer act on the hot function
        return Evidence(
            target=target, source=source, facts=facts,
            profile=profile or Profile(self_pct=79.0, extra={"detector": "single-candidate"}),
            hotspot_rank=1, skips=skips,
        )
