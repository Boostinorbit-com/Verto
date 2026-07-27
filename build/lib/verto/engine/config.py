"""Configuration & policy — loaded from .verto.toml, applied across all surfaces.

Mirrors VERTO_Architecture §8 (Config). Holds the gate policy the Invariant
Gate enforces: min_rung, objectives, allow_regression, enabled transforms.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:                                     # 3.8 (see §16.6): tomllib is 3.11+; tomli backports it
    try:
        import tomli as tomllib          # pip install tomli
    except ImportError:                   # soft fallback — config file just won't load
        tomllib = None  # type: ignore


def global_config_path() -> Path:
    """Machine-wide user defaults: ``$XDG_CONFIG_HOME/verto/config.toml`` (default
    ``~/.config/verto/config.toml``). Deliberately NOT ``~/.verto/`` — XDG-idiomatic, and it
    never collides with the per-project ``.verto/`` workspace that discovery walks up to find."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "verto" / "config.toml"


@dataclass
class Config:
    # gate policy
    min_rung: int = 3                     # auto-apply only at correctness Rung >= 3 (UBSan)
    # NOTE: binary_size is measured & REPORTED but NOT a default hard gate. It's the
    # size of VERTO's synthetic harness binary (driver+STL dominated), and it proved
    # LINKER-dependent — the same map→unordered swap read +8% under bfd ld but +27%
    # under gold. Unreliable to gate on, and code size rarely justifies rejecting a
    # −90% speedup. It returns as a gate once we measure the REAL project binary.
    objectives: tuple[str, ...] = ("p50", "p99", "peak_memory")
    # Regression budgets (§9.3). peak_memory=0.12: a data-structure swap that trades
    # a little memory for a large speedup (map→unordered_map, ~7% RSS on a tiny
    # baseline) is a core Category-A win and must clear the budget, while an
    # egregious resident table (memoization, ~16%+) still fails it. 5% was too tight
    # to distinguish the two — it cut through the swap's measurement band.
    allow_regression: dict[str, float] = field(
        default_factory=lambda: {"binary_size": 0.10, "peak_memory": 0.12})
    min_speedup_pct: float = 2.0          # reject gains below this (kills noise)
    fp_tolerance: float = 0.0             # >0 → compare FP output within this relative tol (item #1b)
    reps: int = 12                        # benchmark repetitions (upper bound when adaptive)
    reps_min: int = 5                     # adaptive floor — escalate to `reps` only if borderline
    adaptive: bool = True                 # stop early when the gain is unambiguous vs threshold
    fast: bool = False                    # --fast: skip Rung-3 sanitizer (UNSOUND — opt-in only)
    # evidence
    profile: str | None = None            # path to a real profile (perf/gprof/json) → hot-code selection (item #5)
    # test-reuse oracle (item #3): confirm accepted changes against the project's OWN tests
    test_command: str | None = None       # shell cmd that builds+runs the tests (exit 0 = pass)
    test_dir: str | None = None           # cwd for test_command (default: the target file's dir)
    test_timeout_sec: int = 600
    # 2A — test-reuse PRIMARY oracle: verify functions the synth harness can't reach,
    # using the project's own tests (correctness) + a project-level bench (performance).
    bench_command: str | None = None      # shell cmd timed for the project-level perf signal
    bench_dir: str | None = None          # cwd for bench_command (default: the target file's dir)
    bench_runs: int = 5                   # median-of-N timings of bench_command per side
    ctest_dir: str | None = None          # 2A-1: a CMake build dir — auto-discover test/bench commands from ctest
    build_command: str | None = None      # 2A-3: build step run ONCE before timing (so bench timing is run-only)
    bench_argv: tuple = ()                # 2A-3: a direct bench executable (from ctest) → clean p50/p99/peak
    # 2D — metamorphic property rung (Rung 2): opt-in; rejects a change that breaks a
    # property the original had (e.g. permutation invariance). Sound (rejects only).
    metamorphic: bool = False
    # sandbox (#13): isolate untrusted binary runs (no network + read-only fs via bwrap) and
    # cap their memory (cgroup). ON by default; --no-sandbox is an escape hatch.
    sandbox: bool = True
    sandbox_mem_mb: int = 2048            # cgroup MemoryMax for isolated runs
    # proposal
    model: str = "frontier"               # frontier | local | rules(--offline)
    transforms: tuple[str, ...] = ("*",)  # glob(s) of enabled transforms
    # cost cap (#12): ceilings on LLM spend — spec = tokens ('500k'), money ('$2'), or time ('90s')
    budget: str | None = None             # per-RUN total
    budget_per_hotspot: str | None = None  # per-HOTSPOT sub-limit
    llm_price_input: float = 3.0          # USD per 1M input tokens (adjust per model; config-file)
    llm_price_output: float = 15.0        # USD per 1M output tokens
    # LLM proposer (#10): --model local → Ollama; --model frontier → an OpenAI-compatible host
    llm_base_url: str = "http://127.0.0.1:11434"   # Ollama default
    llm_model: str = "qwen2.5-coder:7b"   # code-specialized default; the gate makes it a pure
                                          # yield knob (bigger/better model = more real wins, never less safe)
    llm_api_key: str | None = None        # frontier only; local (Ollama) needs none
    llm_timeout_sec: int = 180
    candidates: int = 1                   # #11: LLM proposals per hotspot; gate each, keep the best
    # runtime
    fuzz_inputs: int = 1000
    seed: int = 0

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """Layered config: machine-wide global defaults first, then the project file OVER them.
        Precedence: project `.verto.toml` > global `~/.config/verto/config.toml` > code defaults
        (the git model — repo config overrides user config). `path` overrides the project file."""
        cfg = cls()
        if tomllib is None:
            return cfg
        project = Path(path) if path else Path(".verto.toml")
        for p in (global_config_path(), project):     # global is the base; project wins
            if not p.exists():
                continue
            with p.open("rb") as f:
                data = tomllib.load(f)
            for k, v in data.get("verto", {}).items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        return cfg
