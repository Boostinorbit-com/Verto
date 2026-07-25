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
from .regex_detect import (detect_all_functions, detect_parse_errors,
                           detect_side_effect_reason, detect_template_candidates,
                           set_parse_flags)
from .transforms import ALL


class CppSensor:
    def __init__(self, config: Config) -> None:
        self._config = config

    def collect(self, target: Target) -> Evidence:
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

        # keep only what VERTO can harness AND soundly verify; skip the rest with a
        # reason (item #4). The cascade also enforces the correctness-completeness
        # gate: a function with un-modeled side effects (item #1c) is refused rather
        # than "verified" on stdout alone.
        skips: list[Skip] = []
        funcs: list[str] = []
        test_funcs: list[str] = []           # 2A: transform-matched but harness can't build a signature oracle
        for f in sorted(candidates):
            sig_reason = unsupported_reason(source, f)             # signature (harness)
            reason = sig_reason or detect_side_effect_reason(source, f)  # item #1c
            if reason is None:
                funcs.append(f)
            else:
                skips.append(Skip(func=f, stage="harness", reason=reason))
                if sig_reason is not None:    # a candidate the project's OWN tests could still verify (2A)
                    test_funcs.append(f)
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

        target.symbol = chosen           # oracles/harness/proposer act on the hot function
        return Evidence(
            target=target, source=source, facts=[],
            profile=profile or Profile(self_pct=79.0, extra={"detector": "single-candidate"}),
            hotspot_rank=1, skips=skips,
        )
