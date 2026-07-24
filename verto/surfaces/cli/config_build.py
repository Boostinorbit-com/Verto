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
    if getattr(args, "bench_command", None):
        cfg.bench_command = args.bench_command  # 2A: project-level perf signal (test-primary oracle)
    if getattr(args, "bench_dir", None):
        cfg.bench_dir = args.bench_dir
    if getattr(args, "metamorphic", False):
        cfg.metamorphic = True                  # 2D: metamorphic property rung (Rung 2)
    # selection & tuning knobs (config file covers the rest)
    if getattr(args, "transforms", None):
        cfg.transforms = tuple(g.strip() for g in args.transforms.split(",") if g.strip())
    if getattr(args, "min_speedup", None) is not None:
        cfg.min_speedup_pct = args.min_speedup
    if getattr(args, "reps", None) is not None:
        cfg.reps = args.reps
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
