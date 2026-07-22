# VERTO — Design & Specification

**VERTO (Verified Transforming Optimizer)** — an AI system that makes existing programs measurably faster by reasoning about them the way a senior performance engineer does, and that **only keeps a change it has proven to be both correct and faster.**

This is the single source of truth for the project: what it is, why it must exist, where it sits in the compilation process, how it works internally, and how it is built.
Every claim about the compiler in this document was produced by running the real toolchain (Clang/LLVM 19) on a real machine; the commands and outputs are shown inline so nothing has to be taken on faith.

---

## Table of contents

1. [The one-paragraph version](#1-the-one-paragraph-version)
2. [What VERTO is — precise definition](#2-what-verto-is)
3. [Why VERTO is required — proven, not asserted](#3-why-verto-is-required)
4. [Background: how C++ actually becomes machine code](#4-background-the-c-compilation-pipeline)
5. [Where VERTO sits in the compilation stages](#5-where-verto-sits)
6. [Why source-level + profile-guided is the correct layer](#6-why-this-layer)
7. [The core invariant](#7-the-core-invariant)
8. [The engine: the four-stage loop, in depth](#8-the-engine)
9. [Verification depth: contracts & the correctness ladder](#9-verification-depth)
10. [Core architecture: ports, adapters, and the trust split](#10-core-architecture)
11. [End-to-end worked example (real numbers)](#11-worked-example)
12. [How VERTO extends: the seven axes](#12-extension-axes)
13. [v0 scope, dependencies, and build order](#13-v0)
14. [Prior art and exactly how VERTO differs](#14-prior-art)
15. [Risks and how the design answers them](#15-risks)
16. [Glossary](#16-glossary)

---

<a name="1-the-one-paragraph-version"></a>
## 1. The one-paragraph version

A compiler like Clang optimizes *instructions*: it schedules them, allocates registers, eliminates dead code.
It does this superbly.
But it cannot change your *algorithm*, your *data structure*, or your *memory strategy*, because those are decisions encoded in your source before the compiler ever runs — and undoing them would change what your program means, which a compiler is forbidden to do.
Those higher-level decisions are exactly where most real-world slowness lives.
VERTO is an AI that operates at that higher level: it reads your source and a real execution profile, reasons about *why* the code is slow, proposes a concrete rewrite, and then — this is the part that makes it trustworthy — it **refuses to keep the rewrite unless a trusted checker proves the output is unchanged and a real benchmark proves it is faster.** It sits *above* the compiler, feeds it better source, and learns from every measured result.

---

<a name="2-what-verto-is"></a>
## 2. What VERTO is

**VERTO is a verified, profile-guided, source-level optimizer driven by an AI reasoning engine.**

Unpacking every word, because each one is load-bearing:

| Word | Meaning | Why it matters |
|---|---|---|
| **verified** | Every change passes a trusted correctness check and a trusted speed check before it is kept. | This is the difference between a tool you can run unattended and a toy. A faster-but-wrong program is worthless. |
| **profile-guided** | It reasons from *measured* runtime behavior, not from reading the code cold. | Optimizing what isn't hot is wasted effort; guessing is how humans waste days. |
| **source-level** | Its output is a human-readable diff to your source code, recompiled by your normal toolchain. | It stays reviewable and never fights your compiler; the compiler still does all the instruction-level work. |
| **AI reasoning engine** | An LLM decides *what* to try — algorithm swaps, data-structure changes, `reserve()`, parallelization. | This is judgment that rule-based linters cannot produce. But (see §7) the AI never has the final say. |

**What VERTO is NOT:**
- Not a replacement for GCC/Clang/LLVM. It sits above them and hands them better input.
- Not a code-writing assistant (Copilot/ChatGPT). Those generate code; they never *measure* or *prove* anything.
- Not a linter (clang-tidy). Linters pattern-match on source and *suggest*; they do not run your program, do not measure, and cannot reason about algorithms.
- Not a new intermediate representation or a new language.

---

<a name="3-why-verto-is-required"></a>
## 3. Why VERTO is required — proven, not asserted

The usual objection is: *"Compilers already have `-O3`.
Isn't optimization solved?"* No.
Here is the proof, run on the real toolchain.

### The experiment

A trivial, extremely common piece of C++ — build a vector in a loop:

```cpp
std::vector<int> build(std::size_t n) {
    std::vector<int> v;                       // no reserve()
    for (std::size_t i = 0; i < n; ++i)
        v.push_back(static_cast<int>(i * 2)); // grows, reallocating repeatedly
    return v;
}
```

We compile it at `-O2`, which runs LLVM's **entire 107-pass optimization pipeline**, and inspect the result:

```
$ clang++ -O2 -S -emit-llvm sample.cpp        # after all 107 passes
$ grep -c _M_realloc_insert sample_O2.ll
1                                              # the reallocation call SURVIVES

$ clang++ -O2 -S sample.cpp                    # final x86-64 assembly
$ grep -Eo '_M_realloc_insert|_Znwm' sample.s
_M_realloc_insert                              # still reallocating
_Znwm                                          # still calling operator new in the loop
```

The optimizer **cannot** remove the repeated reallocation, because it cannot prove how large the vector will get — the size `n` is a runtime value.
Removing the reallocation would require *changing the program's meaning* (pre-sizing the buffer), which a compiler is not allowed to do.

### The fix lives one level up — and it is huge

The correct fix is a *source-level* change a human (or VERTO) makes: reserve the space first.

```cpp
v.reserve(n);            // one line — the compiler could never insert this for you
```

Measured on this machine (i5-1135G7, pinned core, 50 reps, two runs for stability):

```
CORRECTNESS: identical=true  checksum_no=3999998000000 checksum_yes=3999998000000
PERF:  no_reserve=8.264 ms   reserve=2.348 ms   speedup=3.52x  (-71.6%)
PERF:  no_reserve=7.885 ms   reserve=2.312 ms   speedup=3.41x  (-70.7%)
```

**The best C++ compiler in existence, running every optimization it has, left ~71% of the performance on the table** — and the recovered performance came from a one-line semantic change with *provably identical output*.
This is not an edge case; it is one of the most common performance bugs in all of C++.

Multiply this across every hot loop, every wrong container choice (`std::map` where `unordered_map` fits), every needless copy, every serial loop that could be parallel, across an entire codebase, and the gap between "what `-O3` gives you" and "what the code could do" is enormous.
**That gap is the reason VERTO exists.** Today, closing it requires a scarce senior engineer with a profiler and a week.
VERTO automates that engineer's loop — safely.

---

<a name="4-background-the-c-compilation-pipeline"></a>
## 4. Background: how C++ actually becomes machine code

To say precisely *where* VERTO operates, we need the real stages.
These are the actual phases Clang/LLVM runs, each demonstrated on `sample.cpp`.

```
   ┌────────────┐  ┌──────────┐  ┌──────────────┐  ┌──────────┐  ┌───────────────┐  ┌──────────┐  ┌────────┐
   │  SOURCE    │─▶│ 1. PRE-  │─▶│ 2. LEX +     │─▶│ 3. AST   │─▶│ 4. LLVM IR    │─▶│ 5. LLVM  │─▶│ 6. CODE│─▶ 7. LINK ─▶ EXE
   │  main.cpp  │  │ PROCESS  │  │   PARSE +    │  │ (typed,  │  │  GENERATION   │  │ OPT      │  │  GEN   │
   │            │  │ #include │  │   SEMA       │  │ checked) │  │ (unoptimized) │  │ (107     │  │ (x86)  │
   └────────────┘  └──────────┘  └──────────────┘  └──────────┘  └───────────────┘  │ passes)  │  └────────┘
                                                                                    └──────────┘
```

**Stage 1 — Preprocessing** (`clang -E`): macro expansion, `#include` inlining, conditional compilation.
Measured:
```
source lines:        10
preprocessed lines:  26041      # after #include <vector> is expanded
```

**Stage 2–3 — Lex, Parse, Semantic Analysis → AST** (`clang -Xclang -ast-dump`): source becomes a typed, checked tree.
This is the first structured form and the primary thing VERTO reads.
For `build()`:
```
FunctionDecl  build 'std::vector (std::size_t)'
  `-CXXConstructExpr 'std::vector' 'void () noexcept'   // v constructed empty
  |-ForStmt
  |   `-CXXMemberCallExpr 'void'
  |     |-MemberExpr .push_back                          // the growth call
  `-CXXConstructExpr 'std::vector' 'void (vector &&)'    // return by move
```
Everything VERTO needs to recognize "vector grown by push_back in a loop with no prior reserve" is right here, as facts — no fragile text parsing required.

**Stage 4 — IR Generation** (`clang -emit-llvm`): the AST is lowered to LLVM IR, a target-independent instruction language.
Unoptimized: **1057 lines**.

**Stage 5 — Middle-end optimization** (`opt`, the `-O2`/`-O3` pipeline): the famous part.
The default `-O2` pipeline is **107 passes**:
```
$ opt -passes='default<O2>' -print-pipeline-passes | tr ',' '\n' | wc -l
107
# first passes: annotation2metadata, forceattrs, inferattrs, sroa, early-cse,
#               ipsccp, globalopt, mem2reg, instcombine, simplifycfg, inline, ...
```
This shrinks our IR from 1057 → **187 lines**.
It is extraordinarily good at instruction-level work.
It is also where **MLGO** (Google's ML-for-inlining/register-allocation) plugs in.
**It is NOT where VERTO operates**, and §3 shows why: it cannot make semantic changes.

**Stage 6 — Code generation** (`llc`): IR → x86-64 assembly (instruction selection, scheduling, register allocation).

**Stage 7 — Linking**: object files + libraries → executable.

Then the program *runs* — and only by running do we learn where time is actually spent.
That runtime signal is the other half of what VERTO consumes.

---

<a name="5-where-verto-sits"></a>
## 5. Where VERTO sits in the compilation stages

VERTO does not live *inside* any single stage.
It **wraps the whole pipeline plus execution in a feedback loop**, and its transformations re-enter at Stage 0 (source):

```
        ┌─────────────────────────── VERTO FEEDBACK LOOP ───────────────────────────┐
        │                                                                          │
        ▼                                                                          │
   SOURCE ──▶ 1 PREPROCESS ──▶ 2-3 AST ──▶ 4 IR ──▶ 5 OPT(107) ──▶ 6 CODEGEN ──▶ 7 LINK ──▶ EXECUTABLE
        ▲            reads AST facts ──┘                                              │        │
        │                                                                            │        ▼
        │                                                              reads runtime profile  RUNS
        │                                                                            │        │
        └──────── proposes a SOURCE rewrite, VERIFIED correct+faster ◀───────────────┴────────┘
```

- **Reads from Stage 2–3 (AST):** structured facts about the code (loops, calls, types, containers, allocations).
- **Reads from post-Stage-7 execution (profile):** where time is actually spent.
- **Writes to Stage 0 (source):** a human-reviewable diff, which the *unchanged* normal compiler then processes.

Contrast with everything nearby, by the stage each one occupies:

| Tool | Operates at | Uses runtime? | Semantic-level changes? | Verifies its change? |
|---|---|---|---|---|
| `clang -O3` | Stage 5–6 | no (static) | **no** (meaning-preserving only) | n/a (trusted rules) |
| **MLGO** | Stage 5–6 | training-time | no (policy on trusted passes) | n/a |
| **PGO / BOLT** | Stage 5 / post-link | yes (profile) | no (layout/inlining only) | n/a |
| **clang-tidy** | Stage 2–3 (AST) | **no** | limited, pattern-based | **no** (just suggests) |
| **Copilot / LLM** | Stage 0 (text) | no | yes | **no** (unproven) |
| **VERTO** | **Stage 0, guided by 2–3 + runtime** | **yes** | **yes** | **yes** |

This *stage placement* — semantic, runtime-guided, and verified — is the right one.
But be honest: a **new class of AI optimizers now shares this cell** (Codeflash, CompilerGPT, Google's ECO — see §14).
VERTO is *not* alone here, and its differentiation lives in *how deeply* it verifies and *what* it targets, **not** in occupying the cell.

---

<a name="6-why-this-layer"></a>
## 6. Why source-level + profile-guided is the correct layer

Three layers were candidates.
We chose Stage 0 deliberately.

- **Why not operate on LLVM IR (Stage 5)?** Because the high-value information — that this is a `std::vector`, that the loop count is bounded, that a `map` could be an `unordered_map` — is *already destroyed* by Stage 4. IR sees loads, stores, and calls into libstdc++, not "a vector without a reserve." You would be reasoning with less information than the AST gives you for free. IR is also where the compiler already dominates.
- **Why not generate custom LLVM passes?** Because a pass must be *provably* semantics-preserving over all inputs, forever. Writing one is a specialist, multi-year discipline, and a wrong pass causes *silent miscompilation* — the worst failure class in computing. VERTO deliberately defers this (see §15) and lets LLVM's already-verified passes do the unsafe part.
- **Why source, then?** Because source is where the *recoverable* decisions live (algorithm, container, memory strategy), where the AI has the most context, where the change stays human-reviewable, and where being wrong is *caught cheaply* by re-running the program (Stage 0 output is just code; the correctness gate re-executes it). Source-level is the highest-information, lowest-blast-radius place to intervene.

---

<a name="7-the-core-invariant"></a>
## 7. The core invariant

Everything in VERTO is swappable — the language, the model, the specific transform — except one rule, which is the project's identity:

> **VERTO never keeps a change that is not both provably CORRECT and measurably FASTER.**

This rule is enforced *structurally*, by splitting the system into two halves with a hard trust boundary:

```
   UNTRUSTED (intelligence)              TRUSTED (verification)
   ┌───────────────────────┐            ┌────────────────────────────┐
   │  LLM Proposer         │  candidate │  Correctness Oracle        │
   │  - reads evidence     │ ─────────▶ │    (differential test)     │
   │  - suggests a rewrite │            │  Performance Oracle        │
   │  - may be WRONG       │            │    (real benchmark)        │
   │  - may be SWAPPED     │            │  ── accept ⟺ correct∧faster│
   └───────────────────────┘            └────────────────────────────┘
        proposes, never decides               decides, cannot be fooled
```

**The LLM never decides anything.
It only proposes a candidate.** A trusted checker the model cannot influence has the only vote that counts.
The consequences are the reason VERTO is trustworthy:

- LLM hallucinates a "10× speedup" → the Performance Oracle measures reality and **rejects**.
- LLM's rewrite subtly changes behavior (e.g. the NumPy-style integer-overflow trap in other languages) → the Correctness Oracle's differential test catches it and **rejects**.
- You swap the frontier model for a weaker local one → **the invariant still holds**; at worst you get fewer good proposals, never a bad accepted change.

In §3's experiment the gate is visible and real: `identical=true` (correctness passed) *and* `3.41x` faster (performance passed) → **ACCEPT**.
Either failing → REJECT.

The strength of the word "provably" in this invariant is not automatic — it depends entirely on *how deep* the correctness check goes.
That depth is the subject of §9, and it is what makes "proven" an honest word rather than a marketing one.

---

<a name="8-the-engine"></a>
## 8. The engine: the four-stage loop, in depth

Strip away language, domain, and model, and the irreducible engine is a closed four-stage loop:

```
   ① EVIDENCE ──▶ ② PROPOSAL ──▶ ③ VERIFICATION ──▶ ④ LEARNING
   (facts+profile) (one rewrite)  (correct ∧ faster? ) (record outcome,
        ▲                          else REJECT)         sharpen next)
        └──────────────── re-profile & loop ──────────────┘
```

### ① Evidence — reason from data, never guess
- **Static facts** from the Clang AST (Stage 2–3): loops, calls, container types, allocation sites, copies, lifetimes. Extracted via `libclang` (confirmed available on this machine).
- **Dynamic profile** from running the program: which functions/lines are hot. (Tooling: `perf`, Google Benchmark, VTune, LLVM XRay. **Note:** `perf` and `valgrind` are *not yet installed* on this machine — a real v0 setup dependency, recorded honestly in §13.)
- These are combined into a compact **annotated context** — the source plus facts like `// hot: 79% runtime; vector grown by push_back, 17 reallocations/call` — and handed to the Proposer. (Deliberately *not* a giant AST/IR JSON dump: LLMs reason better on source + concise facts.)

### ② Proposal — the AI decides *what to try* (untrusted)
The LLM receives the annotated context and emits **one** concrete candidate transform plus a human-readable rationale — e.g. *"insert `v.reserve(n)` before the loop; the vector reallocates 17× per call."* One transform at a time, never a tangled batch.

### ③ Verification — the trusted gate (this is the product)
Two independent trusted oracles, both of which must pass:
- **Correctness Oracle** — *differential testing*: run the original and the rewritten program on many (fuzzed) inputs; assert **byte-identical output**. In §3: `checksum_no == checksum_yes`, `identical=true`.
- **Performance Oracle** — a *statistically honest* benchmark: pinned core, many repetitions, report median and variance, require a *significant* improvement (not noise). In §3: 8.26 ms → 2.35 ms across two stable runs.
- `accept ⟺ Correctness.pass ∧ Performance.improved`. Fail either → **REJECT**.

> This stage is only as trustworthy as those two checks are deep. Both are stronger than "one test, one number" makes them sound — see **§9**, which turns the Correctness Oracle into a graded *ladder* backed by transform *contracts*, and the Performance Oracle into a multi-dimensional *vector*.

### ④ Learning — every outcome teaches
Each episode `(evidence, candidate, verdict, delta)` — **accept *and* reject** — is logged.
The log serves priors back to the Proposer so it proposes better next time.
Locally now; across projects later (the "Network" — §12).

Then **re-profile and loop**, because the last accepted change moved the hotspots (fixing #1 promotes a new #1; parallelizing a loop changes its memory pattern).
Re-profiling between accepts is what makes optimization *ordering* emerge correctly instead of applying stale, conflicting edits.
Stop when no hotspot remains, N rounds yield no accepted change, or a budget is hit.

---

<a name="9-verification-depth"></a>
## 9. Verification depth: contracts and the correctness ladder

The invariant (§7) is only as strong as the word *"proven."* Today's Correctness Oracle runs a differential test — same input → same output on **N fuzzed inputs**.
That is a **probabilistic** check wearing the costume of a proof: it says nothing about input N+1 — the empty vector, the integer overflow, the NaN, the aliased pointer, the exception thrown mid-loop, the data race.
For C++ this gap is the *norm*, not the exception: a rewrite can match on every input you tried and still be wrong because it relies on **undefined behavior**, changes **floating-point reassociation**, or breaks under **concurrency**.
Hardening this is the single most important thing beyond the trust split itself — it is the difference between "proven" as a fact and "proven" as marketing.

### 9.1 Transform contracts — legality *before* the fact

Every transform carries a **precondition** (when it is *legal*) and a **postcondition** (equivalence).
Legality is checked *structurally*, on the AST/CFG, **before** the transform is applied — exactly how a real compiler pass stays correct.

```
transform: insert reserve() before a push_back growth loop
  PRECONDITION  (must hold — checked on the AST/CFG, not by testing):
    • the loop's trip count is loop-invariant (computable before the loop runs)
    • `v` is not aliased or observed elsewhere during the loop
    • element construction has no order-dependent observable side effect
    • no exception between reserve() and the loop can be observed differently
  POSTCONDITION (checked after — the equivalence gate):
    • output is identical to the original on all admitted inputs
```

A transform whose precondition **provably holds** is known-safe *by construction*, not "safe because we tested it." And a verified `(transform, precondition)` pair is **reusable across codebases** — it is the unit the Network (§12, Axis E) actually shares.
Without contracts, "shared learning" is just log lines; with them, it is a growing library of *provably-conditioned* transforms.

### 9.2 The correctness ladder — grade the equivalence check

The postcondition check is not one thing; it is a ladder from weakest to strongest.
Every accepted change is **labelled with the rung it reached**, as a confidence grade.

| Rung | Check | Available on this machine? |
|---|---|---|
| 0 | single-run smoke test | yes |
| 1 | differential test on fuzzed inputs *(today's oracle)* | yes |
| 2 | coverage-guided fuzzing focused **on the changed region** + boundary/edge-case generation + property-based tests | yes |
| 3 | **sanitizers in the gate** — ASan / UBSan / TSan catch *introduced or exposed* undefined behavior & data races | **yes — ships with our Clang 19** |
| 4 | formal / translation validation where tractable — **Alive2** (IR peephole), symbolic execution / bounded model checking (source) | partial |

Two policies fall out of the ladder:
- **Autonomy gates on rung** (ties Axis B to Axis G): auto-apply only changes at **Rung ≥ 3**; merely *suggest* anything below. The human is only ever asked to trust what the machine could not fully prove.
- **Rung 3 is the C++ must-have.** UBSan catches the "equivalent under *this* compiler, but secretly relies on undefined behavior" trap that differential testing *structurally cannot* — the failure mode that makes C++ optimization dangerous.

### 9.3 The performance vector — the other gate is also under-specified

"Faster" is not one number either.
A change can win the median and **wreck p99 tail latency, double peak memory, bloat the binary, or lose on a different CPU.** So the Performance Oracle returns a **vector**, and the gate rejects **Pareto-losers**, not just median-losers:

```
PerformanceVector = { p50, p99_tail, peak_memory, allocations, binary_size, energy, cross_ISA }
accept(perf) ⟺ improves at least one dimension AND regresses none beyond its budget
```

Held-out workloads and a second machine defeat **benchmark-overfitting** (Goodhart's law: an optimizer scored on one benchmark will learn to cheat that benchmark).
Optimizing p50 while silently wrecking p99 is one of the most common ways real "optimizations" ship regressions to production.

### 9.4 Consequences for the architecture

This is a *refinement of the Verification stage and the Ledger*, not a new box bolted on:
- `CorrectnessOracle.equivalent()` returns `{ rung, witness }`, **not a bool**.
- `PerformanceOracle.compare()` returns a **vector + Pareto verdict**, not a scalar delta.
- The Invariant Gate's accept policy references the **rung**.
- The Ledger stores **contracts**, which become the Network's currency.
- **New security requirement:** verification *runs LLM-proposed code*, so it must execute in a **sandbox** — resource limits, no network — or a bad proposal can do more than merely be slow.
- **New capability — prevention:** the same contracts, run in CI, stop new code from *reintroducing* a pattern VERTO already fixed. The optimizer becomes a regression *preventer*, not just a fixer.

Verification depth is itself a growth dimension — you start at Rung 1 and climb — which is why it is elevated to its own extension axis (**Axis G: Rigor**, §12).

---

<a name="10-core-architecture"></a>
## 10. Core architecture: ports, adapters, and the trust split

Two decisions shape the code:

**(A) Thin engine, thick plugins (ports & adapters / hexagonal).** The engine knows only the four-stage loop.
Language, domain, and model are *adapters* behind fixed *ports*.
This is what lets one engine serve every language and every domain (§12) without the core changing.

**(B) The trust split of §7**, made physical: the only component that can return `ACCEPT` is the Invariant Gate, it takes only `(original, variant)`, and it consults no model.

```
┌──────────────────────────────────────────────────────────────────────┐
│ INTERFACE     CLI (verto analyze | optimize | report) · CI · IDE       │
├──────────────────────────────────────────────────────────────────────┤
│ ENGINE CORE   Orchestrator  ·  Invariant Gate  ·  Ledger              │  ← generic, thin
├──────────────────────────────────────────────────────────────────────┤
│ PORTS         Sensor · Proposer · Mutator ·                           │  ← interfaces
│               CorrectnessOracle · PerformanceOracle · Ledger          │
├──────────────────────────────────────────────────────────────────────┤
│ ADAPTERS      Language(C++,Py…) × Domain(Perf,DB…) × Model(API,local) │  ← thick, specific
├──────────────────────────────────────────────────────────────────────┤
│ EXTERNAL      Clang/libclang · perf/GoogleBench · sandbox · LLM       │
└──────────────────────────────────────────────────────────────────────┘
```

### The six ports (the entire contract between engine and plugins)
```
Sensor              collect(target)            → Evidence{ source, facts, profile, hotspots }
Proposer            propose(evidence, priors)  → Candidate{ transform, contract, rationale }  (UNTRUSTED)
Mutator             apply(target, transform)   → Variant                                      (source→source)
CorrectnessOracle   equivalent(orig, variant)  → { rung, witness }                            (TRUSTED, §9)
PerformanceOracle   compare(orig, variant)     → { vector, pareto_verdict, samples }          (TRUSTED, §9)
Ledger              record(episode); recall(evidence) → priors
```
- **Sensor / Mutator** — mostly *language*-specific (parsing, rewriting, building).
- **Oracles** — mostly *domain*-specific (what "equivalent" and "faster" mean).
- **Proposer** — *model*-backed, its prompt/knowledge shaped per language+domain.

### Engine core components
| Component | Responsibility |
|---|---|
| **Orchestrator** | Drives the loop: gather evidence → request proposal → apply → verify → record. Owns iteration, transform ordering, and stop conditions. Knows nothing domain-specific. |
| **Invariant Gate** | The single choke point. `accept ⟺ Correctness.rung ≥ policy ∧ Performance.pareto_pass`. No path around it. |
| **Ledger** | Append-only record of every episode `(evidence, candidate+contract, verdict, delta)`. Serves *priors*; seed of the Network. |

### Data model (what flows through the loop)
```
Target    code under optimization (file/function + build config)
Evidence  source + Clang facts + profile + ranked hotspots
Candidate one proposed transform + its contract (pre/post) + rationale
Variant   Target with the transform applied (a real, compilable artifact)
Verdict   { accepted, correctness_rung, correctness_witness, perf_vector, pareto }
Episode   (Evidence, Candidate, Verdict) → appended to Ledger
```

### Control flow (the corrected loop — profiler feeds reasoning, gate can reject, cycle closes)
```
1. Sensor.collect(target)              → Evidence          (profile is INPUT to reasoning)
2. Ledger.recall(evidence)             → priors
3. Proposer.propose(evidence, priors)  → Candidate + contract  ← UNTRUSTED, one transform
   3a. check contract PRECONDITION on the AST/CFG; if it can't be shown to hold → REJECT early
4. Mutator.apply(target, candidate)    → Variant
5. ─ INVARIANT GATE ─ (TRUSTED)
     CorrectnessOracle.equivalent → rung;  rung < policy      → REJECT
     PerformanceOracle.compare    → vector; not Pareto-better → REJECT
     both pass → ACCEPT: variant becomes the new target
6. Ledger.record(episode)              (accept OR reject — both teach)
7. loop to 1 (re-profile). stop: no hotspot / N rounds no-accept / budget hit
```

### Design rules that keep the architecture honest
1. The core never imports a concrete plugin — only port interfaces.
2. Exactly one place returns `ACCEPT` (the Gate). Nothing bypasses it.
3. The Proposer's output is always a *candidate + contract*, never an action.
4. One transform per candidate; re-profile between accepts.
5. Reject episodes are logged too — learn from failure.
6. Verification runs untrusted code in a sandbox (§9.4).
7. Don't build a second adapter until the first domain works end-to-end.

---

<a name="11-worked-example"></a>
## 11. End-to-end worked example (real numbers)

The `reserve()` case, traced through the loop with the actual measured data from §3:

| Stage | What happens | Real artifact |
|---|---|---|
| **① Evidence** | Clang AST shows `build()` grows a vector by `push_back` in a `ForStmt` with no prior `reserve`. Profile flags it hot. | `FunctionDecl build → ForStmt → CXXMemberCallExpr .push_back` |
| **② Proposal** | LLM: *"Insert `v.reserve(n)` before the loop; use `emplace_back`."* + contract (loop-invariant bound, no aliasing). | one candidate + contract |
| **3a Precondition** | `n` is loop-invariant; `v` not aliased in the loop → **legality holds**. | contract satisfied |
| **③ Correctness** | Differential test; then sanitizers (Rung 3). | `identical=true`, `checksum 3999998000000 == 3999998000000`, **Rung 3** ✓ |
| **③ Performance** | Pinned core, 50 reps, 2 runs; vector check. | `8.26→2.35` and `7.89→2.31` ms → **3.4–3.5×, −71%**, no memory/tail regression ✓ |
| **Gate** | rung ≥ policy ∧ Pareto-better → **ACCEPT**; write the diff. | — |
| **④ Learning** | Log `(vector-grow-no-reserve → reserve, −71%, Rung 3, accepted)`; store the contract. | priors + shareable contract |

For contrast, the same code through `-O3` alone (Stages 5–6, all 107 passes) leaves `_M_realloc_insert` in the final assembly — **0% recovered.** VERTO recovers 71%, verified.

---

<a name="12-extension-axes"></a>
## 12. How VERTO extends: the seven axes

The core loop stays fixed; the system grows along seven independent dimensions.
Each is visible as ambition, built later.

| Axis | Grows from → to |
|---|---|
| **A. Language** | C++ → Python → Rust / Java / Go / JS (new Language adapter each; core untouched) |
| **B. Autonomy** | suggest → auto-apply behind the gate → generate novel transforms *(gated on Axis G rung)* |
| **C. Evidence** | static facts → profiler → hardware counters → production telemetry |
| **D. Scope** | local transform → function → whole-program → cross-service |
| **E. Network** | one machine → **shared learning: every verified `(transform, contract, rung)` anywhere sharpens the next proposal** |
| **F. Domain** | Performance → Database / Network → Build / Test → Debugging / Security |
| **G. Rigor** | Rung 1 (differential test) → Rung 2 (coverage fuzzing) → Rung 3 (sanitizers) → Rung 4 (formal / translation validation); **grade every change** (§9) |

**Axis F — one engine, many domains.** Every "AI *X* Engineer" is the *same* four-stage engine with a different **sensor** (Evidence) and a different **success metric** (the Performance Oracle generalizes to "the domain's objective"):

| Domain | Evidence in | Success metric | Correctness check |
|---|---|---|---|
| **Performance** *(v0)* | profile | faster | same output |
| Database | query plans + stats | faster query | **same result set** |
| Network | pcaps + logs | fewer drops / more throughput | replay test |
| Build | build graph + logs | green / faster build | tests still pass |
| Debugging | logs + stack + git | bug gone | test red→green |
| Security | code + vuln patterns | vuln closed | exploit fails |

**Ordering rule — provability first, market second.** Vertical #0 is chosen by *how cheaply success can be proven × unfair edge*, not market size — because it must prove the engine works.
**Performance wins**: objective metric (time), cheap correctness gate (differential test), squarely on the systems/C++ edge.
Debugging/Security have the biggest markets but the *fuzziest* gates → they come last.

**Axis E is the moat, and Axis G is what makes it real.** A shared learning network is only trustworthy if what it shares is trustworthy; verified `(transform, contract, rung)` tuples are that trustworthy unit.
A verified-optimization data flywheel is something no static compiler can have — which is why "Network" is in the name, though it is built last.

---

<a name="13-v0"></a>
## 13. v0 scope, dependencies, and build order

**v0 = one point on every axis** — the smallest thing that exercises the entire engine:

| Slot | v0 choice |
|---|---|
| Language | **C++** — libclang for AST facts, source→source Mutator, `clang++` build |
| Domain | **Performance** |
| First transform | **`reserve()` before a `push_back` loop** (the §3 case: real, common, 71% win) |
| Sensor | Clang facts + benchmark hotspots |
| Proposer | frontier LLM (prove the idea; swap to local later) |
| Correctness Oracle | differential test **+ UBSan (Rung 3)** — N fuzzed inputs → identical output, no UB |
| Performance Oracle | Google Benchmark — pinned core, ≥30 reps, median + p99 + significance |
| Rigor (Axis G) | target **Rung 3** for auto-apply; Rung 1–2 → suggest only |
| Ledger | local append-only JSON, stores the contract |
| Interface | `verto analyze` / `verto optimize --apply` / `verto report` |

**Confirmed present on this machine:** Clang/LLVM 19 (`clang++`, `opt`, `llc`, `clang-tidy`), Python `libclang` bindings, CMake 3.26, Ninja, g++ 9.4. Sanitizers (ASan/UBSan/TSan) ship with Clang → **Rung 3 is reachable now.**

**Missing — install before v0** (stated honestly, not assumed):

- `perf` and `valgrind` — profiling (needed for Category B).
- Google Benchmark library.
- A modern Python for the orchestration layer (system Python is 3.8).

**Build order (each step ships something runnable):**
1. **Trusted gate first, no AI.** Wire the Correctness Oracle (differential test + UBSan) + Performance Oracle around a *hardcoded* `reserve()` rule. Prove the gate accepts the §3 win and rejects a deliberately-wrong rewrite. *The hard, novel part is the gate, not the model.*
2. **Add the contract check** (precondition on the AST/CFG) and the rung labelling.
3. **Add the Sensor** (libclang detector for grow-without-reserve) so detection is automatic.
4. **Add the Proposer** (LLM) behind the now-trusted gate.
5. **Add the Ledger** and close the loop (re-profile, iterate).
6. Only then: a second transform, a second domain, or a second language.

---

<a name="14-prior-art"></a>
## 14. Prior art — including the tools that already do the core loop

**Honest framing, up front.** VERTO's core loop — *an LLM proposes a rewrite, a trusted check verifies it is correct, a benchmark verifies it is faster, accept only if both hold* — is **not novel**.
As of 2026 it is an active research area **and** a shipping commercial product.
This cuts two ways: it is **validation** (the mechanism demonstrably works and has real value) and a **warning** (the mechanism is not a moat).
VERTO must differentiate on *how deeply* it verifies and *what* it optimizes — never on the loop itself.
Anyone reviewing this project will run the search below; better that we did it first.

### 14.1 Direct prior art — the "AI verified-optimizer" class (the real competition)

| System | Level / language | Correctness gate | Profile-guided? | What it leaves open for VERTO |
|---|---|---|---|---|
| **Codeflash** *(commercial: CLI, VS Code, GitHub Action)* | source; **Python/JS/TS/Java** | generated regression tests + existing tests — **no formal / no sanitizers** (≈ Rung 1–2) | **no** | not C++/systems; **explicitly does *not* change architecture** (no algorithm/data-structure swaps); no contracts/UBSan/Alive2; single-metric |
| **CompilerGPT** *(LLNL, 2025)* | **C++ source** | **user-provided test harness** (≈ Rung 1) | **no** — driven by compiler *static* optimization reports | up to 6.5× **but "not consistently"**; user selects regions; no contracts/formal; report-driven, not profile-driven |
| **ECO** *(Google, 2025)* | source, **hyperscale production** | verify + **human code review** + production success (>99.5%) | **yes** — fleet data + a mined **"anti-pattern dictionary"** | closest to VERTO's Learning + Network *at scale*, but internal, human-in-loop, pattern-dictionary rather than formal contracts |
| **"Verified Learning for Compiler Optimization"** *(2025)* | **LLVM IR** (lazification case study) | **untrusted generator + trusted Alive2 formal check** | no | this is essentially VERTO's *trust split + formal rung* — but at **IR level** and one narrow transform, not C++ source semantics |
| **LLM-Vectorizer** *(2024)* | C++ loops | **Alive2 formal** + repair loop | no | narrow (vectorization only); proves Alive2-in-the-loop is real and practical |
| **Meta LLM Compiler** *(2024)* | LLVM IR / compiler flags | — | — | IR & flag tuning, not source-level semantic reasoning |

The field even has its own **benchmark** (*PerfCodeBench*, for LLM system-level HPC optimization) and its own **skeptics** (*"Do AI Models Dream of Faster Code?"*, an empirical study finding many LLM-proposed "optimizations" don't hold up) — a sign of a maturing area, not a greenfield.

### 14.2 Adjacent / infrastructure prior art (different layer or not AI)

| Work | What it does | Different from VERTO because |
|---|---|---|
| **MLGO** (Google, in LLVM) | ML *policy* for inlining / register allocation, inside passes | Instruction-level (Stage 5–6), meaning-preserving; not source-semantic |
| **Meta, "LLMs for Compiler Optimization" (2023)** | LLM predicts *pass ordering* | Chooses among trusted passes; no source rewrite, no per-change verification |
| **Autotuners** (OpenTuner, TVM/Ansor) | Search transform *parameters* with measurement | Parameter search, not semantic reasoning; domain-narrow |
| **PGO / BOLT / Propeller** | Profile-guided layout/inlining; BOLT rewrites the binary | Layout only; no algorithm/data-structure change; no gate on a *proposed* rewrite |
| **clang-tidy / linters** | Pattern-match AST, *suggest* fixes | No runtime, no measurement, no verification |
| **AlphaDev** (DeepMind) | RL found faster tiny fixed sort/hash kernels at assembly | *Weak precedent.* Tiny fixed branchless routines, exhaustively verifiable, brute-force RL — opposite regime; method does not transfer |

### 14.3 Where VERTO honestly differs — and the risk

**No single system found combines all five of these:**

- **(A) C++/systems, source-level.**
- **(B) A first-class graded rigor ladder** — Transform Contracts (AST-level legality) + UBSan + Alive2 rungs, going *beyond "generated tests pass."*
- **(C) Profile-guided selection** of *what* to optimize.
- **(D) A multi-objective Performance Vector** — p99 / memory / cross-ISA, not one wall-clock number.
- **(E) A shared-verified-transform Network.**

**But the overlaps are real — each ingredient already exists somewhere:**

- **ECO** already pairs a production profile with a mined anti-pattern dictionary (≈ C + E, at Google scale, human-reviewed).
- **"Verified Learning"** already has the untrusted-generator + Alive2 split (≈ B, at IR level).
- **CompilerGPT** already does C++ source rewriting (≈ A, but report-driven and test-gated).

So VERTO's honest claim is **integration, not invention.**

**The bet:** making formal rigor (contracts + rungs) the product's spine — for C++ systems code, with profile-guided selection and a verified-transform network — beats the generic loop everyone already ships.

That bet is **defensible but unproven — explicitly not a first-mover claim.** The core loop is commoditized; VERTO lives or dies on the rigor and the layer.

### 14.4 Is VERTO's *architecture* different? Split the question honestly

**At the block-diagram level — no.** VERTO's fundamental shape — *untrusted LLM proposer → trusted "correct-and-faster" gate → loop* — is shared, not novel:

| Architectural element | VERTO | Codeflash | CompilerGPT | "Verified Learning" |
|---|---|---|---|---|
| Untrusted proposer + trusted gate + loop | ✅ | ✅ | ✅ | ✅ |
| **Trust split** (LLM proposes, external oracle decides) | ✅ | partial (tests) | partial | ✅ **exactly this** |

The "Verified Learning" paper describes *an untrusted generator + a trusted external formal verifier, correctness enforced as a runtime control layer* — VERTO's trust split, verbatim, as an architecture.
Claiming "my architecture is different" at this level does not survive scrutiny.

**At the *layering* level — yes, as a combination:**

| Distinctive layer | VERTO | The others |
|---|---|---|
| **Graded Correctness Ladder** (oracle returns `{rung, witness}`; autonomy gated on rung) | ✅ | binary pass/fail (VL has formal, not a *graded* ladder) |
| **Transform Contracts** (precondition legality on the AST *before* applying) | ✅ | ❌ none |
| **Profile fed into the proposer** (Evidence layer) | ✅ | Codeflash ❌, CompilerGPT ❌ (static reports), ECO ✅ |
| **Multi-objective Performance Vector** (p99 / memory / cross-ISA) | ✅ | mostly single wall-clock |
| **Ports & adapters** (one engine, many languages/domains) | ✅ | single-purpose tools |
| **Network layer** (shared verified `(transform, contract, rung)`) | ✅ | ECO has a mined dictionary (partial) |

No competitor assembles all of these — but every individual row has *someone* who does it, so the distinctiveness is the **stack, not any single layer**.

**The honest sentence:** *VERTO's core architecture (proposer + trusted gate) is shared with the field, including a paper with the exact trust split.
What's distinctive is the layering — contracts + a graded correctness ladder + profile-fed evidence + a multi-objective gate + a plugin engine + a verified-transform network — as a combination no one else has assembled, though each layer has prior art individually.* Architecture is never the moat; the two hardest-to-copy layers (**contracts** and the **graded rigor ladder**) are also the most work — that is where the daylight is, and it must be *earned* on the Wedge Test, not claimed in a diagram.

---

<a name="15-risks"></a>
## 15. Risks and how the design answers them

| Risk | Answer built into the design |
|---|---|
| **The LLM produces a wrong "optimization."** | It has no authority. The trusted Correctness Oracle rejects any change that alters output. (§7) |
| **"Correct" only means "correct on the inputs we tested."** | The **Correctness Ladder** (§9): coverage-guided fuzzing on the changed region, **UBSan/TSan** for undefined behavior & races, and formal/translation validation where tractable. Every change carries its **rung**; auto-apply is gated on it. |
| **A change is faster in a noisy benchmark but not really — or wins p50 and wrecks p99.** | The **Performance Vector** (§9.3): significance across pinned-core runs, and a Pareto check across p50/p99/memory/size, with held-out workloads to beat Goodhart. |
| **Generating LLVM passes risks silent miscompilation.** | Deferred entirely. Near-term VERTO does source→source and lets LLVM's *already-verified* passes run. Novel-pass generation waits until a formal verifier (Alive2) is in the loop. (§6, §9) |
| **VERTO executes LLM-proposed code to verify it.** | Verification runs in a **sandbox** — resource limits, no network. (§9.4, design rule 6) |
| **Optimizations interact / wrong order.** | One transform per candidate, re-profile between accepts, so ordering emerges from measurement. (§8) |
| **Scope explosion (10 "AI Engineers" at once).** | One domain, one language, one transform in v0; every extension is a new adapter, built only after the prior one works. (§12, §13) |
| **Weak local model caps quality.** | Prove the idea on a frontier model first; the invariant holds regardless of model, so swapping down is safe. (§7, §13) |
| **Dishonest "it works" claims.** | Every performance/correctness claim in this doc is a real command output; missing tools (`perf`, `valgrind`) are stated, not hidden. (§3, §13) |

---

<a name="16-glossary"></a>
## 16. Glossary

- **AST (Abstract Syntax Tree):** the typed, structured form of your program after parsing (Stage 2–3); VERTO's primary source of static facts.
- **LLVM IR:** the compiler's target-independent instruction language (Stage 4); where `-O2`/`-O3` operate.
- **Pass:** one transformation the optimizer applies to IR; `-O2` runs 107 of them.
- **`_M_realloc_insert`:** libstdc++'s vector-growth reallocation routine — the call that survives `-O3` in §3 and that `reserve()` eliminates.
- **Differential testing:** running two versions on the same inputs and asserting identical output — Rung 1 of VERTO's correctness proof.
- **Transform contract:** a transform's precondition (when it is legal) + postcondition (equivalence); legality is checked before applying. (§9.1)
- **Correctness ladder / rung:** the graded strength of the equivalence check, from smoke test (0) to formal validation (4); every accepted change is labelled with the rung it reached. (§9.2)
- **Performance vector:** the multi-dimensional success metric {p50, p99, memory, allocations, size, energy, cross-ISA}; the gate rejects Pareto-losers. (§9.3)
- **Undefined behavior (UB):** C++ constructs with no defined meaning; a rewrite can rely on UB and pass differential testing yet be wrong — caught at Rung 3 by UBSan.
- **Oracle:** a trusted checker that returns a verdict the untrusted model cannot influence.
- **Adapter / Port:** an implementation / an interface, in the hexagonal architecture that keeps the engine thin.
- **The invariant:** *never keep a change that is not both provably correct and measurably faster* — VERTO's identity.

---

*Every compiler-behavior claim here was generated by running Clang/LLVM 19 on `sample.cpp`/`bench.cpp`; the commands and outputs are shown inline so the document can be checked, not merely believed.*
