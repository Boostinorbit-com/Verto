"""C++ Sensor — Target -> Evidence, with profile-guided hotspot selection.

Mirrors VERTO_Architecture §16.1 and the Evidence stage (§8①). It is GENERIC over
transforms: candidate functions come from each registered transform's
`candidates()` — the Sensor no longer hardcodes growth/map/string detection, so
adding a transform needs no Sensor change. Among candidates it can harness AND
soundly verify, it picks the one that's actually HOT (profile-guided, item #5) and
sets `target.symbol` so the proposer/oracles act on it. Everything it can't verify
is reported as an honest skip with a reason (item #4/#1c/#1d).
"""
from __future__ import annotations

from pathlib import Path

from ....engine.config import Config
from ....engine.models import Evidence, Profile, Skip, Target
from ...domain.performance.harness import unsupported_reason
from .profile import load_profile
from .profiler import profile_functions
from .regex_detect import (detect_all_functions, detect_func_span, detect_parse_errors,
                           detect_side_effect_reason, detect_template_candidates,
                           set_parse_flags)
from .transforms import ALL


class CppSensor:
    def __init__(self, config: Config) -> None:
        self._config = config

    def collect(self, target: Target, exclude: frozenset[str] = frozenset()) -> Evidence:
        source = Path(target.file).read_text(encoding="utf-8")
        # codebase mode: parse this TU with its real compile_commands flags so
        # includes/defines/-std resolve (single-file mode leaves this empty).
        set_parse_flags(target.build.get("parse_flags"))

        # Candidate functions: for the LLM proposer (#10), ANY function is fair game (it can
        # optimize what no hand-coded pattern matches); for the rule proposer, the union of
        # each registered transform's candidates() (the generic-sensor payoff — no hardcoded
        # detectors). The skip cascade + profile-selection below are shared.
        candidates: set[str] = set()
        if getattr(self._config, "model", "") in ("local", "frontier"):
            candidates.update(detect_all_functions(source))
        else:
            for t in ALL:
                candidates.update(t.candidates(source))
        # NOTE: `exclude` (already-processed functions, for the multi-hotspot walk) is applied to
        # SELECTION below, NOT here — profiling still needs the full set to know the file's PEAK
        # cost, so a leftover function can be judged hot-enough-to-optimize vs negligibly cold.

        # keep only what VERTO can harness AND soundly verify; skip the rest with a
        # reason (item #4). The cascade also enforces the correctness-completeness
        # gate: a function with un-modeled side effects (item #1c) is refused rather
        # than "verified" on stdout alone.
        skips: list[Skip] = []
        funcs_all: list[str] = []            # every harness-able function (for peak-cost profiling)
        test_funcs: list[str] = []           # 2A: transform-matched but harness can't build a signature oracle
        for f in sorted(candidates):
            sig_reason = unsupported_reason(source, f)             # signature (harness)
            reason = sig_reason or detect_side_effect_reason(source, f)  # item #1c
            if reason is None:
                funcs_all.append(f)
            else:
                skips.append(Skip(func=f, stage="harness", reason=reason))
                if sig_reason is not None and f not in exclude:  # a candidate the project's tests could verify (2A)
                    test_funcs.append(f)
        funcs = [f for f in funcs_all if f not in exclude]         # not-yet-processed → selectable
        # a TU that wouldn't parse looks empty — surface that, don't swallow it.
        for msg in detect_parse_errors(source):
            skips.append(Skip(func=Path(target.file).name, stage="parse", reason=msg))
        # optimizable function TEMPLATES can't be harnessed without instantiation —
        # name them, don't silently ignore them (item #1d).
        for t in detect_template_candidates(source):
            skips.append(Skip(func=t, stage="harness",
                              reason="template function — needs a concrete instantiation to verify"))

        if not funcs:
            # 2A — nothing the synth harness can reach, but a transform matched a
            # function the project's OWN tests could verify. Route it to test-primary
            # mode (needs --test-command; the gate additionally needs --bench-command).
            if test_funcs and getattr(self._config, "test_command", None):
                chosen = test_funcs[0]
                target.symbol = chosen
                target.verify_mode = "tests"
                return Evidence(
                    target=target, source=source, facts=[],
                    profile=Profile(self_pct=0.0, extra={"detector": "test-primary (2A)", "chosen": chosen}),
                    hotspot_rank=1, skips=[s for s in skips if s.func != chosen])
            return Evidence(target=target, source=source, facts=[], profile=None, skips=skips)

        # --- profile-guided selection with a HOTNESS FLOOR ---
        # Cost is measured over the FULL harness-able set (funcs_all) so we know the file's PEAK,
        # then the hottest not-yet-processed function is chosen. If even that one is negligibly cold
        # vs the peak, there is NO real hotspot left — return none so the walk stops rather than
        # making a pointless change to cold code (the profile-guided-focus invariant; wedge B1).
        profile = None
        times: dict[str, float] = {}
        profiler = ""
        if len(funcs_all) > 1:
            real = load_profile(self._config.profile) if getattr(self._config, "profile", None) else {}
            if real and any(f in real for f in funcs_all):
                # REAL profile (perf/gprof/…) — the function that's actually hot in the user's
                # workload, not a synthetic micro-benchmark (item #5).
                times = {f: real.get(f, 0.0) for f in funcs_all}
                profiler = "external"
            else:
                times = self._profile_cached(source, funcs_all)
                profiler = "microbench-v0"

        chosen = max(funcs, key=lambda f: times.get(f, 0.0))       # funcs is sorted → deterministic on ties
        peak = max(times.values(), default=0.0)
        floor = getattr(self._config, "hotspot_floor_pct", 5.0) / 100.0
        if peak > 0 and times.get(chosen, 0.0) < floor * peak:
            # only negligibly-cold functions remain (e.g. an 8-iteration path) — not worth a pass.
            return Evidence(target=target, source=source, facts=[], profile=None, skips=skips)

        if profiler == "external":
            profile = Profile(self_pct=times.get(chosen, 0.0), calls=0,
                              extra={"costs": times, "chosen": chosen, "profiler": profiler})
        elif profiler == "microbench-v0":
            profile = Profile(self_pct=0.0, calls=0,
                              extra={"times_ms": times, "chosen": chosen, "profiler": profiler})

        target.symbol = chosen           # oracles/harness/proposer act on the hot function
        span = detect_func_span(source, chosen)
        return Evidence(
            target=target, source=source, facts=[],
            profile=profile or Profile(self_pct=79.0, extra={"detector": "single-candidate"}),
            hotspot_rank=1, skips=skips,
            func_source=source[span[0]:span[1]] if span else "",   # rewrite-cache key
        )

    def _profile_cached(self, source: str, funcs: list[str]) -> dict[str, float]:
        """Micro-profile `funcs`, memoized per (source, funcs) so a multi-round walk over the
        SAME source (dry-run) profiles once, not once per round."""
        key = (hash(source), tuple(sorted(funcs)))
        cache = getattr(self, "_prof_cache", None)
        if cache is None:
            cache = self._prof_cache = {}
        if key not in cache:
            cache[key] = profile_functions(source, funcs)
        return cache[key]
