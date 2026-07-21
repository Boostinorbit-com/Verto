# AION — Engineering Architecture (Generic / Multi-Language)

**The language-agnostic blueprint: the one engine that never changes, and the adapters that make it speak any language.**

This document defines the **engine core** (shared by every language and domain), the **abstract adapter contracts** a new language must satisfy, and — because C++ is the only language today — the **concrete C++ instance (v0)** inline in §16.

- **§1–15** — the generic engine + how multi-language support works.
- **§16** — the concrete C++ (v0) instance: libclang, `clang++`, sanitizers, Google Benchmark, build order.
- *When a second language (Python) lands,* §16 splits into its own `AION_Architecture_Cpp` and each language gets a child doc — the split **earned at instance #2, not before** (the same rule-of-three discipline we apply to the code).

**Boundaries (one fact, one home):** concepts/why → `AION.md` · delivery → `AION_Surfaces` · proof → `WEDGE_TEST` · **how it's built → this doc** (C++ instance in §16).

---

## Table of contents

1. [Purpose & document map](#1-purpose)
2. [One engine, many adapters](#2-thesis)
3. [Universal vs per-language](#3-universal)
4. [Module / directory tree](#4-modules)
5. [The Engine API](#5-api)
6. [The six ports (abstract contracts)](#6-ports)
7. [Data schemas](#7-schemas)
8. [Component catalog](#8-components)
9. [Control flow](#9-control-flow)
10. [Trust boundary & sandbox](#10-sandbox)
11. [Technology stack (core + per-language requirements)](#11-tech-stack)
12. [Adapter contracts (Language / Domain / Model)](#12-contracts)
13. [Multi-language support matrix](#13-matrix)
14. [Extension recipe — add a language](#14-extension)
15. [Failure handling & language roadmap](#15-roadmap)
16. [C++ instance (v0) — adapter internals & build order](#16-cpp-instance)

---

<a name="1-purpose"></a>
## 1. Purpose & document map

AION is designed to optimize **any** language (Axis A: C++ → Python → Rust / Java / Go / JS). It does this **not** by cramming languages into one code path, but by keeping a small, fixed **engine** and swapping **thick, language-specific adapters** behind fixed interfaces.

This document specifies the fixed part and the interface every language plugs into.

```
                 ┌──────────────────────────────┐
                 │   AION.md   (concepts / why)  │
                 └──────────────┬───────────────┘
                                │
             ┌──────────────────┴───────────────────┐
             ▼                                       ▼
   AION_Architecture (this)                  AION_Surfaces (delivery)
   generic engine + adapter                  CLI / CI / IDE / …
   contracts (multi-language)
             │
             ▼
   C++ instance (v0) — inline in §16
   (Python / Rust / … get their own child docs when they land)
```

---

<a name="2-thesis"></a>
## 2. One engine, many adapters

**The engine knows only the four-stage loop.** It has never heard of C++ or Python. Everything language-, domain-, or model-specific is an *adapter* behind one of six ports.

```
┌───────────────────────────────────────────────────────────────┐
│ ENGINE CORE  (language-agnostic, built once)                  │
│   Orchestrator · Invariant Gate · Ledger · Registry · Config  │
└───────────────┬───────────────────────────────────────────────┘
                │  depends only on the six PORT interfaces
   ┌────────────┼──────────────┬──────────────────────┐
   ▼            ▼              ▼                       ▼
 Language     Domain         Model                 (Runtime:
 adapter      adapter        provider               Sandbox +
 (C++,Py,…)   (Perf,DB,…)    (frontier,local)       Bench runner)
```

An **adapter set** for any job is chosen by **(Language × Domain × Model)**. Add C++ → a Language adapter. Add Python → another Language adapter. Add Database → a Domain adapter. The engine is untouched in every case.

**Why this is the right factoring for multi-language:** the *hard, novel* part of AION (the trusted correctness/performance gate, the loop, the ledger) is **identical across languages** — so it's written once and reused. Only the *mechanical* parts (parse, rewrite, build, measure) differ per language, and those are exactly what an adapter isolates.

---

<a name="3-universal"></a>
## 3. Universal vs per-language

The single most important table in this document — it decides what lives in the engine and what every new language must bring.

| Concern | Universal (engine) | Per-language (adapter) |
|---|---|---|
| Loop orchestration | ✅ | — |
| Invariant Gate / ACCEPT policy | ✅ | — |
| Ledger, priors, learning | ✅ | — |
| Trust split (untrusted proposer / trusted gate) | ✅ | — |
| Sandbox (isolation mechanism) | ✅ | — |
| Core data schemas (Target/Evidence/Verdict/Episode) | ✅ *shape* | the `facts[]` content & `build_flags` |
| **Correctness — the *idea*** (same input → same output) | ✅ | — |
| Correctness — *how to run the program & what "output" is* | — | ✅ |
| Correctness — UB / safety checks | — | ✅ (C++ UBSan; Java NPE/overflow; Python overflow/exceptions; Rust `miri`) |
| **"Faster" — the measurement protocol** | — | ✅ **irreducibly per-language** |
| Fact extraction (parser) | — | ✅ (each language's parser) |
| Source→source mutation | — | ✅ |
| Build / compile / run step | — | ✅ |
| Transform library | partly (some ideas port) | ✅ (most transforms are language-specific) |

**The deepest per-language item is measurement.** "Faster" does not port:

- **C++** — pinned-core microbenchmark, `{p50, p99, memory, size}`.
- **Java** — **JIT warmup**: you must measure *steady state* and discard warmup (this is why JMH exists). Naive timing is garbage.
- **Python** — you're mostly measuring "did we leave the interpreter"; GIL-aware; `timeit`/`pyperf`.
- **JS** — event-loop and GC sensitive; benchmark.js-style.

So the `PerformanceOracle` interface is universal, but **its implementation is a Domain×Language responsibility** — the adapter owns the honest protocol.

---

<a name="4-modules"></a>
## 4. Module / directory tree

Generic layout; the engine is fixed, `adapters/language/*` grows one subtree per language.

```
aion/
├─ engine/                         # ── language-agnostic core (never per-language) ──
│  ├─ api.py                       # Engine API: analyze / optimize / report
│  ├─ orchestrator.py             # the four-stage loop
│  ├─ gate.py                     # Invariant Gate — the ONLY ACCEPT
│  ├─ ledger.py                   # append-only episodes + priors
│  ├─ ports.py                    # the six abstract Protocol interfaces
│  ├─ models.py                   # core data schemas
│  ├─ config.py                   # .aion.toml, policy (min-rung, objectives…)
│  └─ registry.py                 # (language × domain × model) → adapter set
│
├─ adapters/
│  ├─ language/                    # ONE subtree per language — the multi-language axis
│  │  ├─ cpp/                     # C++ adapter (v0) — internals in §16
│  │  ├─ python/                  # future (own child doc)
│  │  ├─ rust/  · java/ · go/ · ts/     (future)
│  │  └─ base.py                  # LanguageAdapter ABC (what every language must provide)
│  ├─ domain/
│  │  ├─ performance/             # Performance domain (v0)
│  │  ├─ database/ · network/ …   (future)
│  │  └─ base.py                  # DomainAdapter ABC
│  └─ model/
│     ├─ frontier.py · local.py · rules.py
│     └─ base.py                  # ModelProvider ABC
│
├─ runtime/
│  ├─ sandbox.py                  # isolation (language-agnostic)
│  └─ bench_runner.py             # generic timing harness (protocol supplied per language)
│
├─ surfaces/ …                     # thin clients (see AION_Surfaces)
└─ tests/
```

**Rule:** nothing in `engine/` imports from `adapters/`. Adapters implement the ABCs in `adapters/*/base.py`; the engine talks only to `ports.py`.

---

<a name="5-api"></a>
## 5. The Engine API

Language-agnostic. Surfaces call these; the API resolves the right adapter set via the Registry (§8) before running the loop.

```python
# engine/api.py
class Engine:
    def __init__(self, config: Config): ...
    def analyze(self, target: TargetSpec) -> Report: ...
    def optimize(self, target: TargetSpec, *, apply: bool) -> list[Verdict]: ...
    def report(self, since: Date | None = None) -> LedgerSummary: ...
```

`TargetSpec` carries the file(s) and options; the Engine inspects it, asks the **Registry** for the `(Language, Domain, Model)` adapter set (e.g. file ends in `.cpp` → C++ adapter), and runs the same loop regardless of language.

---

<a name="6-ports"></a>
## 6. The six ports (abstract contracts)

Identical to the per-language docs, but stated **abstractly** — no libclang, no `ast`; just the contract every language's adapter fulfils.

```python
# engine/ports.py
class Sensor(Protocol):            # language + domain
    def collect(self, target: Target) -> Evidence: ...
        # extract structured facts via THE LANGUAGE'S parser + attach a profile

class Proposer(Protocol):          # model                       (UNTRUSTED)
    def propose(self, ev: Evidence, priors: Priors) -> Candidate | None: ...

class Mutator(Protocol):           # language
    def apply(self, target: Target, transform: Transform) -> Variant: ...
        # source→source rewrite using the language's own tooling

class CorrectnessOracle(Protocol): # domain                      (TRUSTED)
    def equivalent(self, orig: Target, var: Variant,
                   inputs: HeldOutInputs) -> CorrectnessVerdict: ...

class PerformanceOracle(Protocol): # domain × language           (TRUSTED)
    def compare(self, orig: Target, var: Variant) -> PerfVerdict: ...
        # runs the LANGUAGE'S honest measurement protocol

class Ledger(Protocol):            # engine
    def record(self, ep: Episode) -> None: ...
    def recall(self, ev: Evidence) -> Priors: ...
```

Binding: `Sensor` and `Mutator` are **language**-bound; the two Oracles are **domain**-bound but their measurement/execution details are **language**-supplied; `Proposer` is **model**-bound; `Ledger` is engine-provided.

---

<a name="7-schemas"></a>
## 7. Data schemas

The core schemas are language-agnostic; per-language content is confined to two open fields — `facts[]` and `build_flags` — so the engine never needs to know the language.

```python
@dataclass
class Target:
    file: str; symbol: str; line: int
    language: str                   # "cpp" | "python" | …  (Registry sets this)
    build: BuildSpec                # opaque to the engine; language adapter interprets

@dataclass
class Evidence:
    target: Target
    source: str
    facts: list[Fact]               # Fact.kind is a shared vocabulary; detail is language-specific
    profile: Profile | None
    hotspot_rank: int

@dataclass
class Contract:                     # a transform's legality + equivalence promise
    precondition: list[str]         # checkable predicates on the AST/CFG
    postcondition: str              # "output-equivalent"

@dataclass
class Candidate:                    # Proposer.propose() output   (UNTRUSTED)
    transform: Transform; contract: Contract; rationale: str

@dataclass
class Variant:                      # Mutator.apply() output — a compilable artifact
    target: Target; patch: str; source_after: str

@dataclass
class CorrectnessVerdict:
    rung: int                       # 0..4 — highest ladder level PASSED
    passed: bool; witness: Witness  # counter-example / sanitizer report / build status

@dataclass
class PerfVerdict:
    vector: dict                    # {p50, p99, peak_memory, allocs, binary_size, …}
    pareto_pass: bool; samples: int

@dataclass
class Verdict:                      # per-candidate result — the surface payload
    accepted: bool; candidate: Candidate
    correctness: CorrectnessVerdict; performance: PerfVerdict
    reason: str                     # "accepted" | "precondition_failed" | "unsafe" | "slower"

@dataclass
class Episode:                      # what the Ledger stores
    evidence: Evidence; candidate: Candidate; verdict: Verdict
```

**Key design choice:** `Fact.kind` uses a *shared vocabulary* (`container`, `loop`, `alloc`, `copy`, `call`), so a transform can reason across languages where the concept exists, while `Fact.detail` holds the language-specific payload. The engine treats both as opaque.

---

<a name="8-components"></a>
## 8. Component catalog (engine core)

Only the language-agnostic components live here. The C++ adapter's concrete components + internals are in **§16** (the C++ instance); future languages get their own child doc.

```
Orchestrator                                             [ENGINE · universal]
Responsibility  Run the four-stage loop for any adapter set.
In → Out        TargetSpec → list[Verdict]
Depends on      the six ports (never a concrete adapter)
```
```
Invariant Gate                                           [ENGINE · universal · TRUSTED]
Responsibility  The single ACCEPT. accept ⟺ rung≥policy ∧ pareto_pass.
Note            same code for every language — correctness policy is universal
```
```
Ledger                                                   [ENGINE · universal]
Responsibility  Record every episode; serve priors. Seed of the Network (Axis E).
Note            language tag is stored so priors can be language-scoped or shared
```
```
Registry                                                 [ENGINE · universal]
Responsibility  Map a Target → (Language, Domain, Model) adapter set.
Key functions   resolve(target) → AdapterSet
                _language_of(file)   # by extension / config
                _domain_of(config)   # default: performance
                _model_of(config)    # frontier | local | rules
```
```
Config                                                   [ENGINE · universal]
Responsibility  Load .aion.toml; hold policy (min-rung, objectives, budgets,
                enabled transforms). Applied identically across surfaces & languages.
```
```
Sandbox / Benchmark Runner                               [RUNTIME · universal]
Responsibility  Sandbox: isolate untrusted builds/runs (rlimits, no-net).
                Bench runner: generic harness; the *protocol* (reps, warmup,
                steady-state) is supplied by the language adapter.
```

---

<a name="9-control-flow"></a>
## 9. Control flow

Identical for every language — the loop doesn't branch on language; the adapter set it was handed does the language-specific work.

```
Engine.optimize(spec):
  adapters = Registry.resolve(spec)          # picks Language×Domain×Model
  Orchestrator(adapters).run(spec.target):
    1. ev    = adapters.sensor.collect(target)      # language parser + profile
    2. prior = Ledger.recall(ev)
    3. cand  = adapters.proposer.propose(ev, prior) # UNTRUSTED
    4. check contract precondition on the AST/CFG → else REJECT
    5. var   = adapters.mutator.apply(target, cand.transform)
    6. Gate.decide(target, var):                    # TRUSTED, in sandbox
         adapters.correctness.equivalent(...) → rung   ; rung<policy → REJECT
         adapters.performance.compare(...)    → vector ; !pareto    → REJECT
         else ACCEPT
    7. Ledger.record(episode)
    8. re-profile; loop; stop on no-hotspot / N-no-accept / budget
```

---

<a name="10-sandbox"></a>
## 10. Trust boundary & sandbox

Language-agnostic (the mechanism doesn't care what it's running):

- **Process isolation** per build/run; fresh temp workdir.
- **Resource limits** (`rlimit`): CPU, memory, wall-clock, output size.
- **No network** during verification.
- **Filesystem scope** limited to source + toolchain (read) and workdir (write); optional `bubblewrap`.
- Any variant that times out / OOMs / touches the network → **REJECT**, never a crash.

The only language-specific input is *which command* to run (the Language adapter's build/run), which the sandbox executes opaquely.

---

<a name="11-tech-stack"></a>
## 11. Technology stack

### Core (language-agnostic — fixed for all languages)

| Concern | Choice | Note |
|---|---|---|
| Engine language | Python 3.11+ | orchestration only |
| Ports / schemas | stdlib `typing.Protocol`, `dataclasses` | no framework lock-in |
| Ledger | JSONL / SQLite (stdlib) | flat until the Network needs retrieval |
| Sandbox | `subprocess` + `resource.setrlimit` + `unshare`/bubblewrap | Linux |
| Config | TOML (`tomllib`) | `.aion.toml` |
| Model provider | frontier LLM API (v0); local later; rules for `--offline` | model-swappable |
| CLI | `typer` / `argparse` | see `AION_Surfaces` |

**Deliberately NOT in the core:** FAISS/vector-DB and PyTorch (we call an LLM, we don't train one) — added only if/when the Network or fine-tuning demands it.

### Per-language toolchain — what each Language adapter must supply

Every new language provides these five things. This table *is* the multi-language plan.

| Requirement | What it does | C++ (v0) | Python | Rust | Java | Go | JS/TS |
|---|---|---|---|---|---|---|---|
| **Parser** | source → facts | libclang | `ast`/libcst | `syn`/ra | JavaParser | `go/ast` | TS compiler |
| **Mutator** | source→source rewrite | libclang edits | libcst | `syn` | JDT | `go/ast` | ts-morph |
| **Build/run** | produce a runnable artifact | `clang++`+`compile_commands` | interpret / `py_compile` | `cargo` | `javac` | `go build` | `tsc`/node |
| **Profiler** | hotspots | perf / gbench | cProfile / pyinstrument | perf / criterion | async-profiler | pprof | node `--prof` |
| **Measurement protocol** | honest "faster" | pinned microbench | GIL-aware `timeit` | criterion | **JMH (JIT warmup)** | `go test -bench` | benchmark.js |
| **Safety check** *(optional)* | UB / crashes | ASan/UBSan/TSan | overflow, exceptions | `miri` | NPE, overflow | race detector | runtime checks |

---

<a name="12-contracts"></a>
## 12. Adapter contracts (Language / Domain / Model)

The abstract base classes a new adapter implements (`adapters/*/base.py`).

**LanguageAdapter** — everything language-specific:
```python
class LanguageAdapter(ABC):
    ext: tuple[str, ...]                                  # e.g. (".cpp",".hpp")
    def parse_facts(self, target) -> list[Fact]: ...      # via the language parser
    def apply(self, target, transform) -> Variant: ...    # source→source
    def build(self, target, *, sanitize=False) -> Artifact: ...
    def run(self, artifact, inputs) -> RunResult: ...
    def measurement_protocol(self) -> BenchProtocol: ...  # reps/warmup/steady-state
```

**DomainAdapter** — what "success" and "equivalent" mean:
```python
class DomainAdapter(ABC):
    def relevant_facts(self, ev) -> list[Fact]: ...       # which evidence matters
    def equivalent(self, orig_out, var_out) -> bool: ...  # Perf: byte-identical;
                                                          # DB: same result set; …
    def objectives(self) -> list[str]: ...                # {p50,p99,mem,…} to score
```

**ModelProvider** — how a candidate is generated:
```python
class ModelProvider(ABC):
    def propose(self, context, priors) -> Candidate | None: ...   # LLM or rules
```

A working AION instance = one `LanguageAdapter` × one `DomainAdapter` × one `ModelProvider`, wired by the Registry.

### Proposer / model requirements

The `ModelProvider` is **untrusted** and swappable — the gate re-verifies everything, so the model is a *quality knob*, not a correctness dependency. A weak model just proposes fewer good transforms; it can never cause a bad accepted change. **Pick for quality-per-dollar, not for trust.**

**No specific model is required.** What actually matters for proposing a `Transform` + `Contract`:
- **Code reasoning** — algorithm/data-structure judgment ("should this `map` be `unordered_map`?"), not mere completion.
- **Structured output** — reliable JSON / tool-calling, so a candidate parses deterministically.
- **Modest context** — AION feeds *source + compact facts*, not raw AST dumps, so a huge context window is not needed.

**Staged choice:**

| Stage | Model | Why |
|---|---|---|
| **v0 — prove the reasoning** | a **frontier code model** (Claude Opus/Sonnet, or GPT / Gemini-class) | a weak model would make you wrongly conclude the *idea* fails when it's the *model* that failed |
| **Scale / privacy / cost** | a **local open-weight code model** — Qwen2.5-Coder, DeepSeek-Coder, Codestral, Llama (via Ollama / vLLM), **distilled on the Ledger** | cheap, on-prem, and fine-tuned on *your* accepted transforms |
| **CI / known patterns** | **`--offline` rules** — no LLM (`adapters/model/rules.py`) | deterministic, free, reproducible |

**Cost tactic (safe because gated):** run a **cheap model first**, escalate to a **strong model only on misses**, and use **`--candidates N`** to sample several proposals and keep the best *verified* one.

Runtime selection is the `--model NAME` / `--offline` flags (see `AION_Surfaces`).

---

<a name="13-matrix"></a>
## 13. Multi-language support matrix

Where each language sits, and the one gotcha that dominates its adapter.

| Language | Status | Correctness note | Measurement gotcha | Best early transforms |
|---|---|---|---|---|
| **C++** | **v0** | UBSan is essential (UB passes diff-testing) | pinned core, else noise | `reserve`, `map→unordered_map`, copy→move |
| **Python** | planned #2 | NumPy int64 overflow vs Python bigint | must *leave the interpreter* to matter; GIL | loop→vectorized/NumPy, comprehension, better containers |
| **Rust** | later | mostly safe; `miri` for `unsafe` | criterion handles stats | clone elimination, iterator fusion |
| **Java** | later | NPE / overflow edge cases | **JIT warmup** — steady-state only (JMH) | collection choice, allocation reduction, stream fixes |
| **Go** | later | race detector for goroutine changes | GC pauses; `-bench` stats | slice preallocation, escape reduction |
| **JS/TS** | later | type coercion edge cases | event loop / GC; microbench care | re-render/DOM, async patterns, hot-loop shapes |

**Why Python is #2 (not the biggest-market pick):** it's *maximally different* from C++ (cache-layout vs escape-the-interpreter). If the generic engine survives that jump, it survives anything — the best possible stress test of this architecture. (See `AION.md` §12.)

---

<a name="14-extension"></a>
## 14. Extension recipe — add a language

Concrete, engine-untouched. To add language **L**:

1. **`adapters/language/L/`** — implement `LanguageAdapter`: `parse_facts` (L's parser), `apply` (L's rewriter), `build`/`run`, and `measurement_protocol` (L's honest timing — the part that does *not* port).
2. **Register** L in `registry.py` by file extension.
3. **Reuse** the existing `DomainAdapter` (Performance) and `ModelProvider` unchanged.
4. **Seed transforms** — start with 1–2 L-specific transforms + contracts.
5. **Validate on the Wedge Test** — the judge is language-agnostic; it just needs L's build/run.
6. **Do not modify `engine/`.** If you must, the abstraction leaked — fix the seam, not the core.

**Discipline (rule of three):** don't build language #2 until language #1 (C++) works end-to-end. You earn the abstraction at the *second* instance, not by imagining it at the first — which is why v0 ships C++-only even though this doc is generic.

---

<a name="15-roadmap"></a>
## 15. Failure handling & language roadmap

**Failure handling** — universal, language-agnostic (details of the *cause* come from the adapter, the *policy* is the engine's):

| Situation | Behavior |
|---|---|
| Language not registered for a file | clean error, exit 2 |
| Adapter parse/build fails | REJECT / exit 2 (never a crash) |
| Variant unsafe (sanitizer/race/UB) | REJECT `unsafe` |
| Not Pareto-faster | REJECT `slower` |
| Noisy measurement | re-run K× → else `inconclusive` |
| Precondition unprovable | REJECT `precondition_failed` |

**Language roadmap** (Axis A, staged — ambition visible, scope disciplined):

```
 v0 ── C++            (proves the generic engine on the hardest-to-verify language)
 #2 ── Python         (proves generality: maximally different regime)
 later ── Rust · Java · Go · JS/TS   (each a new LanguageAdapter, engine untouched)
```

Each step is **a new adapter, not a new engine** — which is the entire point of this document.

---

<a name="16-cpp-instance"></a>
## 16. C++ instance (v0) — adapter internals & build order

The one concrete instantiation of the generic architecture: the **C++ Language adapter** + **Performance Domain adapter** that make up v0. *(When a second language lands, this section splits out into its own `AION_Architecture_Cpp`.)*

### 16.1 Fact extraction (`adapters/language/cpp/sensor.py`)
- Parse the translation unit with **libclang**, using the flags from `compile_commands.json` (without them C++ won't parse — includes, `-std`, defines all matter).
- Walk the AST for the target function; emit `Fact`s: **container** (type + usage: grown by `push_back`? `reserve` before? iteration-order observed?), **loop** (invariant bound? independent iterations?), **alloc/copy** (needless copies, missing `move`).
- Attach the **profile**: map `perf`/Google-Benchmark hotspots to functions/lines.

Concrete `Evidence` (`--json`):
```jsonc
{ "target": { "file": "packet_stats.cpp", "function": "build_histogram", "line": 14,
              "language": "cpp",
              "build": { "compile_commands": "build/compile_commands.json",
                         "flags": ["-O2","-std=c++20","-Iinc"] } },
  "facts": [ { "kind": "container", "detail": { "type": "std::vector<int>", "var": "out",
               "grown_by": "push_back", "in_loop": true, "reserve_before": false } } ],
  "profile": { "self_pct": 79.0, "calls": 2300000, "reallocations": 17 },
  "hotspot_rank": 1 }
```

### 16.2 Source→source mutation (`mutator.py`)
- Transforms are **text edits at libclang source locations** — precise, minimal, reviewable diffs.
- Example (`reserve_before_pushback`): insert `v.reserve(n);` immediately before the loop's opening brace, at the `ForStmt` source location.
- Optionally run **clang-format** on the touched range; output a unified diff + full rewritten source.

### 16.3 Build (`build.py`)
- Compile original and variant with the *exact* flags from `compile_commands.json` (+ any `-- passthrough`), inside the sandbox.
- Correctness runs add `-fsanitize=…`; performance runs use real `-O2`/`-O3` — **never sanitized** (sanitizers distort timing).

### 16.4 Correctness ladder (`correctness.py`)
- **Rung 1** — compile both, run over held-out inputs, assert byte-identical output.
- **Rung 2** — coverage-guided fuzzing on the changed region + boundary/edge inputs (empty, max, overflow, NaN).
- **Rung 3** — rebuild with **UBSan/ASan/TSan**; any trip → REJECT. *The trap-catcher* — the "equivalent but relies on UB" case.
- **Rung 4** *(later)* — Alive2 for IR peepholes; symbolic execution for source.

### 16.5 Performance vector (`performance.py`)
- Build both at real `-O` levels; benchmark via the pinned-core runner (N reps + warmup).
- Capture `{p50, p99, peak_memory(RSS), allocs, binary_size}`.
- **Pareto rule:** accept only if ≥1 objective improves significantly and none regresses past its `--allow-regression` budget.

### 16.6 C++ toolchain (verified on this machine)
- **Present:** Clang/LLVM 19 (`clang++`, `opt`, `llc`, `clang-tidy`), Python `libclang`, CMake 3.26, Ninja, g++ 9.4. Sanitizers ship with Clang → **Rung 3 reachable now.**
- **Install before v0:** `perf` + `valgrind` (profiling), Google Benchmark library, Python 3.11+ (system is 3.8).

### 16.7 v0 build order
Each step ships something runnable; the hard, novel part (the trusted gate) comes first.

1. **Data model + engine skeleton** — `models.py`, `ports.py`, a no-op orchestrator, config loading.
2. **Runtime substrate** — `sandbox.py` (rlimits, no-net) + `bench_runner.py` (pinned, stat).
3. **The trusted Gate, no AI** — `CorrectnessOracle` (Rung 1 diff-test + Rung 3 UBSan) + `PerformanceOracle` (vector + Pareto), wired to a **hardcoded** `reserve()` transform. Prove it **accepts** the real win and **rejects** a deliberately-UB rewrite.
4. **Contract check** — precondition on the AST/CFG + rung labelling.
5. **C++ Sensor** — libclang detector for `grow-without-reserve`.
6. **Proposer** — the LLM behind the now-trusted gate (keep `rules.py` as `--offline`).
7. **Ledger + loop close** — record episodes, re-profile, iterate.
8. **CLI surface** — `analyze` / `optimize` / `report` (see `AION_Surfaces`).

> Steps 2–3 are AION — and they are *also* the Wedge Test's judge, so building the core and building the proof are the same work.

---

*The engine is universal; languages are adapters. This doc owns the universal part, the adapter contracts, and (today) the concrete C++ instance in §16. When a second language lands, §16 splits into `AION_Architecture_Cpp` and each language gets its own child doc. Concepts → `AION.md` · delivery → `AION_Surfaces` · proof → `WEDGE_TEST`.*
