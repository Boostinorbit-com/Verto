"""Build a Config from parsed CLI args (args → Config), plus KEY=VAL coercion."""
from __future__ import annotations


def _coerce(cur, val: str):
    """Coerce a KEY=VAL string to the type of the existing config field."""
    if isinstance(cur, bool):
        return val.lower() in ("1", "true", "yes", "on")
    if isinstance(cur, int):
        return int(val)
    if isinstance(cur, float):
        return float(val)
    if isinstance(cur, (tuple, list)):
        return tuple(x.strip() for x in val.split(",") if x.strip())
    return val


def _build_config(args):
    from ...engine.config import Config
    cfg = Config.load(getattr(args, "config_file", None))
    if getattr(args, "offline", False):
        cfg.model = "rules"
    if getattr(args, "model", None):
        cfg.model = args.model
    if getattr(args, "fast", False):
        # opt-in speed-over-soundness: skip the Rung-3 sanitizer, fewer reps.
        cfg.fast = True
        cfg.min_rung = 1
        cfg.reps_min = 3
        cfg.reps = 6
    if getattr(args, "min_rung", None) is not None:
        cfg.min_rung = args.min_rung      # explicit --min-rung still wins
    if getattr(args, "fp_tolerance", None) is not None:
        cfg.fp_tolerance = args.fp_tolerance   # FP-tolerance compare (item #1b)
    if getattr(args, "profile", None):
        cfg.profile = args.profile        # real profile drives hotspot selection (item #5)
    if getattr(args, "test_command", None):
        cfg.test_command = args.test_command   # project's own tests re-confirm changes (item #3)
    if getattr(args, "test_dir", None):
        cfg.test_dir = args.test_dir
    if getattr(args, "test_timeout_sec", None) is not None:
        cfg.test_timeout_sec = args.test_timeout_sec
    if getattr(args, "bench_command", None):
        cfg.bench_command = args.bench_command  # 2A: project-level perf signal (test-primary oracle)
    if getattr(args, "bench_dir", None):
        cfg.bench_dir = args.bench_dir
    if getattr(args, "bench_runs", None) is not None:
        cfg.bench_runs = args.bench_runs
    if getattr(args, "build_command", None):
        cfg.build_command = args.build_command      # 2A: manual build step (else set by --ctest-dir)
    if getattr(args, "ctest_dir", None):        # 2A-1: auto-discover test/bench from ctest
        from ...adapters.language.cpp.cmake_ctest import discover_ctest
        cfg.ctest_dir = args.ctest_dir
        tgt = getattr(args, "path", None) if not getattr(args, "all", False) else None
        d = discover_ctest(args.ctest_dir, target_file=tgt)   # 2A-1: narrow to tests exercising this TU
        if d.test_command and not cfg.test_command:
            cfg.test_command = d.test_command
        if d.bench_command and not cfg.bench_command:
            cfg.bench_command = d.bench_command
        if d.bench_argv and not cfg.bench_argv:
            cfg.bench_argv = tuple(d.bench_argv)        # 2A-3: direct bench exe → full Pareto vector
        if d.build_command and not cfg.build_command:
            cfg.build_command = d.build_command
    if getattr(args, "metamorphic", False):
        cfg.metamorphic = True                  # 2D: metamorphic property rung (Rung 2)
    if getattr(args, "no_sandbox", False):
        cfg.sandbox = False                     # #13: escape hatch — disable isolation
    if getattr(args, "sandbox_mem", None) is not None:
        cfg.sandbox_mem_mb = args.sandbox_mem
    if getattr(args, "budget", None):
        cfg.budget = args.budget                # #12: per-run LLM spend cap
    if getattr(args, "budget_per_hotspot", None):
        cfg.budget_per_hotspot = args.budget_per_hotspot
    if getattr(args, "llm_model", None):
        cfg.llm_model = args.llm_model          # #10: pick the LLM (e.g. qwen3:0.6b)
    if getattr(args, "llm_base_url", None):
        cfg.llm_base_url = args.llm_base_url
    if getattr(args, "candidates", None) is not None:
        cfg.candidates = args.candidates        # #11: N LLM rewrites per hotspot
    if cfg.model == "frontier" and not cfg.llm_api_key:
        # #10: secrets come from the ENVIRONMENT, never a flag (argv leaks into
        # `ps`/shell history). BOOSTOPT_LLM_API_KEY wins; OPENAI_API_KEY is the
        # de-facto standard. Self-hosted OpenAI-compatible hosts may need none.
        import os
        cfg.llm_api_key = (os.environ.get("BOOSTOPT_LLM_API_KEY")
                           or os.environ.get("OPENAI_API_KEY"))
        if not cfg.llm_api_key:
            import sys
            print("boostopt: --model frontier selected but no API key found. Set "
                  "OPENAI_API_KEY (or BOOSTOPT_LLM_API_KEY), or use a keyless "
                  "self-hosted --llm-url. Falling back to keyless request.",
                  file=sys.stderr)
    # selection & tuning knobs (config file covers the rest)
    if getattr(args, "transforms", None):
        cfg.transforms = tuple(g.strip() for g in args.transforms.split(",") if g.strip())
    if getattr(args, "min_speedup", None) is not None:
        cfg.min_speedup_pct = args.min_speedup
    if getattr(args, "reps", None) is not None:
        cfg.reps = args.reps
    if getattr(args, "reps_min", None) is not None:
        cfg.reps_min = args.reps_min
    if getattr(args, "no_adaptive", False):
        cfg.adaptive = False                   # always run full --reps (disable early-stop)
    if getattr(args, "fuzz_inputs", None) is not None:
        cfg.fuzz_inputs = args.fuzz_inputs     # item #7: wider seeded correctness inputs
    if getattr(args, "seed", None) is not None:
        cfg.seed = args.seed
    if getattr(args, "objectives", None):
        cfg.objectives = tuple(o.strip() for o in args.objectives.split(",") if o.strip())
    for kv in getattr(args, "config", None) or []:        # --config KEY=VAL (repeatable)
        if "=" not in kv:
            raise ValueError(f"--config expects KEY=VAL, got {kv!r}")
        k, val = (s.strip() for s in kv.split("=", 1))
        if not hasattr(cfg, k):
            raise ValueError(f"unknown config key {k!r}")
        setattr(cfg, k, _coerce(getattr(cfg, k), val))
    return cfg
