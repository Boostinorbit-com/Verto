"""VERTO data schemas — the objects that flow through the four-stage loop.

Mirrors VERTO_Architecture §6/§7. These are language-agnostic; per-language
content is confined to `Fact.detail` and `Target.build`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Target:
    """The code under optimization."""
    file: str
    symbol: str
    line: int
    language: str                      # "cpp" | "python" | …  (Registry sets this)
    build: dict[str, Any] = field(default_factory=dict)  # opaque to engine; adapter interprets
    verify_mode: str = "harness"       # "harness" (synth oracle) | "tests" (2A: project-tests primary oracle)


@dataclass
class Fact:
    """One structured observation from the language parser.

    `kind` uses a shared vocabulary (container/loop/alloc/copy/call); `detail`
    holds the language-specific payload. The engine treats both as opaque.
    """
    kind: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Profile:
    self_pct: float = 0.0
    calls: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Skip:
    """A candidate site VERTO saw but did NOT optimize, and why (Phase-1 item #4).

    Surfaced so a real-repo scan is legible instead of a silent "nothing found".
    `stage`: parse (TU wouldn't parse) | harness (opportunity found but its
    signature can't be verified) | verify (original harness wouldn't build/link)."""
    func: str
    reason: str
    stage: str = "harness"


@dataclass
class Evidence:
    """Sensor.collect() output — reasoning input for the Proposer."""
    target: Target
    source: str
    facts: list[Fact] = field(default_factory=list)
    profile: Profile | None = None
    hotspot_rank: int = 0
    skips: list["Skip"] = field(default_factory=list)   # sites seen but not optimized (item #4)
    func_source: str = ""              # the chosen function's exact text — the rewrite-cache key


@dataclass
class Contract:
    """A transform's legality (precondition) + equivalence (postcondition)."""
    precondition: list[str] = field(default_factory=list)
    postcondition: str = "output-equivalent"


@dataclass
class Candidate:
    """Proposer.propose() output — UNTRUSTED until the gate verifies it."""
    transform: Any                     # a Transform (see adapters/transforms/base.py)
    contract: Contract
    rationale: str = ""


@dataclass
class Variant:
    """Mutator.apply() output — a real, compilable artifact."""
    target: Target
    patch: str                         # unified diff
    source_after: str


@dataclass
class Witness:
    build_ok: bool = True
    inputs_run: int = 0
    first_divergence: Any | None = None
    sanitizer: str = "clean"           # "clean" | "asan:..." | "ubsan:..." | "tsan:..."


@dataclass
class CorrectnessVerdict:
    rung: int                          # 0..4 — highest ladder level PASSED
    passed: bool
    witness: Witness = field(default_factory=Witness)


@dataclass
class PerfVerdict:
    vector: dict[str, float] = field(default_factory=dict)  # {p50, p99, peak_memory, ...}
    pareto_pass: bool = False
    samples: int = 0
    reason: str = ""                    # why Pareto failed (e.g. "peak_memory regressed …")


@dataclass
class Verdict:
    """Per-candidate result — the payload every surface renders."""
    accepted: bool
    candidate: Candidate | None
    correctness: CorrectnessVerdict | None
    performance: PerfVerdict | None
    reason: str                        # accepted | precondition_failed | unsafe | slower | build_failed | tests_failed
    diff: str = ""                     # concise pseudo-patch for display (@@ func @@ -old +new)
    udiff: str = ""                    # real git-apply-able unified diff (2C patch series)
    applied: bool = False              # True iff --apply actually wrote it to source
    tests_confirmed: bool = False      # True iff the project's own test suite re-confirmed it (item #3)
    via: str = "harness"               # correctness basis: "harness" (sanitizers) | "tests" (project suite, 2A)
    metamorphic: str = ""              # property confirmed by the metamorphic rung, if any (2D)
    cached: bool = False               # True iff reused from the best-so-far rewrite cache (not re-gated)


@dataclass
class Episode:
    """What the Ledger stores."""
    evidence: Evidence
    candidate: Candidate | None
    verdict: Verdict


@dataclass
class Priors:
    """Recalled from the Ledger to sharpen the next proposal."""
    accepted_transforms: list[str] = field(default_factory=list)
    rejected_transforms: list[str] = field(default_factory=list)


@dataclass
class VerifyCtx:
    """A shared workdir + compile cache the gate hands to both oracles so the
    original/variant are compiled once and reused (not once per oracle). A plain
    data holder — the engine creates it without importing any adapter."""
    workdir: str
    cache: dict = field(default_factory=dict)
    extra_cflags: tuple = ()           # codebase mode: -I/-D/-std from compile_commands.json
    link_inputs: tuple = ()            # codebase mode: project archive to link the harness against
    opt_flags: tuple = ()              # codebase mode: -O/-march/-f… so timing matches the real build (item #6)
