# BOOSTOPT — The Wedge Test

**A pre-registered, head-to-head benchmark that isolates where BOOSTOPT structurally beats the existing AI code optimizers — and, honestly, where it does not.**

Companion to [BOOSTOPT.md](BOOSTOPT.md) §14.
That section admits the core loop (LLM proposes → verify correct → verify faster → accept) is **not novel**: Codeflash ships it, Google's ECO runs it at scale, CompilerGPT does it for C++.
This document defines the experiment that turns BOOSTOPT's *claimed* differentiation into a *measured, falsifiable* one — or kills the claim.

> **The rule of this document:** a "win" must be **structural** — something a competitor cannot do *even in principle*, because of how it is built — not a lucky run. And the suite deliberately includes cases BOOSTOPT should **tie or lose**, so the result is credible to a hostile reviewer.

---

## 1. The hypothesis (pre-registered, falsifiable)

> On C++, BOOSTOPT wins **specifically and only** where a change requires **(A)** a structural/algorithmic swap, **(B)** knowing the *true* runtime hotspot, **(C)** rigor to be *safe*, or **(D)** trading off multiple objectives — because the competitors are structurally blind to exactly those four things. On everything else, BOOSTOPT ties or loses.

**Falsification conditions (state them before running):**
- If BOOSTOPT does **not** win **Category C (safety)**, the core thesis — *rigor is the differentiator* — is **disproven**. Category C is the make-or-break.
- If BOOSTOPT wins any **Control** case, the harness is **rigged** and every other result is void.
- If BOOSTOPT's wins in A/B/D vanish once the competitor is given its *best* configuration, the wedge is **narrower than claimed** and must be re-scoped.

---

## 2. The contestants (and an honest asymmetry)

| Tool | In the ring for C++? | Structural limits under test |
|---|---|---|
| **BOOSTOPT** (this project) | yes | — (system under test) |
| **CompilerGPT** (LLNL, open-source) | **yes — the real C++ rival** | driven by compiler **static reports**, not a runtime profile; correctness = **user test harness** (no sanitizers, no contracts) |
| **Codeflash** (commercial) | **no — Python/JS/TS/Java only** | tested *structurally* on Python equivalents: **refuses to change architecture**; correctness = generated/existing **tests only** |
| **`clang -O3`** | yes (control/baseline) | meaning-preserving; cannot make semantic changes |

**Honest note:** because Codeflash does not do C++, its column is *conceptual/structural*, demonstrated on Python twins (same optimization, showing it won't swap data structures and won't run a sanitizer).
The **runnable** head-to-head is **BOOSTOPT vs CompilerGPT vs `-O3`** on C++.

---

## 3. The judge — one independent harness grades everyone the same way

No tool grades its own homework.
Every tool emits an optimized variant; the **judge** — which is literally BOOSTOPT's Verification stage (§8–9 of BOOSTOPT.md), run neutrally — evaluates *all* variants identically:

```
JUDGE(original, variant):
  DETECTED   = tool attempted this case                         (bookkeeping)
  CORRECT    = differential test on a HELD-OUT hard input set    ← inputs no tool saw:
               { empty, size 1, max size, INT overflow boundary,   empty/NaN/boundary/huge
                 negative, NaN/inf (fp), duplicate-heavy, sorted, reverse-sorted }
  SAFE       = variant passes ASan + UBSan + TSan                ← run by the judge regardless
                                                                    of whether the tool checked
  FASTER     = benchmark, pinned core, ≥30 reps, report
               { p50, p99, peak_memory, binary_size } ; require
               ≥ significant p50 gain AND no dimension regressed
               beyond budget (Pareto-non-loser)
  VERDICT    = WIN  iff  CORRECT ∧ SAFE ∧ FASTER
               UNSAFE  if applied but fails CORRECT or SAFE       ← the key column
               MISS    if not detected / no change
               SLOWER  if correct+safe but not faster
```

The **`UNSAFE`** verdict is the whole point of Category C: a change a tests-only tool *accepted* that the judge's held-out inputs or sanitizers *fail*.
That is a demonstrated correctness win for BOOSTOPT's approach.

---

## 4. The pre-registered case suite

15 cases: 12 wedge (A–D) + 3 controls.
Each case is committed *before* any run.
Predicted verdicts are the pre-registration.

### Category A — requires a structural / algorithmic change

**W-A1 — wrong container (`map` → `unordered_map`)**
```cpp
std::map<int,int> freq;                 // ordered; order never observed below
for (int x : data)      freq[x]++;
long total = 0;
for (int q : queries)   total += freq.count(q) ? freq[q] : 0;
```
Optimal: `std::unordered_map`.
Contract precondition: *iteration order of `freq` is never observed* (only `count`/lookup) → holds.
Expect large speedup on big `data`.

**W-A2 — O(n²) → O(n) (nested-loop dedup → hash set)**
```cpp
for (std::size_t i = 0; i < v.size(); ++i)          // O(n^2)
  for (std::size_t j = i+1; j < v.size(); ++j)
    if (v[i] == v[j]) { dups++; break; }
```
Optimal: one pass with `std::unordered_set`.
Algorithmic — not a within-structure tweak.

**W-A3 — linear scan on sorted data → binary search**
```cpp
for (int q : queries)                                // v is sorted; O(n) each
  if (std::find(v.begin(), v.end(), q) != v.end()) hits++;
```
Optimal: `std::binary_search` / `lower_bound`.
Contract: `v` provably sorted at this point.

### Category B — requires the *true* hotspot (profile beats static report)

**W-B1 — hidden hotspot among report-flagged loops**
A file with ~20 loops. `clang -Rpass-missed=loop-vectorize` flags several as "not vectorized." But 80% of runtime is a single `reserve`-less `push_back` loop the report does **not** emphasize.
```cpp
std::vector<int> out;                    // THE hotspot: reallocates ~log2(N) times
for (std::size_t i = 0; i < N; ++i) out.push_back(f(i));
// ...19 other cold loops the vectorization report loves to mention...
```
Optimal: fix the hot one (`reserve`).
CompilerGPT chases report-flagged (cold) loops; BOOSTOPT's profiler goes straight to the 80%.

**W-B2 — hot tiny helper the static report ignores**
A 3-line helper called 50M times dominates; no optimization report fires on it.
Profile-guided selection finds it; report-driven does not.

### Category C — requires rigor to be SAFE (the crown jewel)

Each C-case ships a **plausible-but-wrong "optimization"** — the kind an LLM confidently proposes and a tests-only gate waves through.
BOOSTOPT must **reject** it (and, ideally, find a safe alternative).

**W-C1 — signed-overflow UB (passes small-input tests)**
```cpp
// original (correct):
long sum = 0; for (std::size_t i = 0; i < n; ++i) sum += a[i];
// tempting "faster" rewrite:
int sum = 0;  for (int i = 0; i < (int)n; ++i)     sum += a[i];   // UB when sum > INT_MAX
```
Small test arrays pass.
Judge's max-size input overflows → **UBSan fires**.
BOOSTOPT rejects (Rung 3); CompilerGPT/Codeflash-class → `UNSAFE`.

**W-C2 — off-by-one out-of-bounds read (benign on test inputs)**
```cpp
for (std::size_t i = 0; i <= n; ++i) acc += a[i];   // reads a[n]; "clever" bound
```
Happens not to crash on small tests.
Judge's **ASan** catches the OOB read → `UNSAFE` for tests-only tools.

**W-C3 — illegal loop-invariant hoist (contract precondition fails)**
```cpp
for (int i = 0; i < n; ++i)
  out[i] = data[i] * scale(cfg);          // LLM hoists scale(cfg) out of the loop
```
Legal *only if* `scale` is pure and `cfg` is not mutated in the loop.
If `scale` has observable side effects (or `cfg` changes), hoisting changes behavior.
BOOSTOPT's contract precondition **fails → reject**; a naive tool hoists and is wrong on inputs where `cfg` mutates.

**W-C4 — data race from naive parallelization**
```cpp
#pragma omp parallel for                  // proposed "speedup"
for (int i = 0; i < n; ++i) hist[data[i]]++;   // races on shared buckets
```
Judge's **TSan** fires.
Tests-only may pass on a lucky schedule and ship a race.
BOOSTOPT rejects (or requires an atomic/privatized reduction that passes TSan).

**W-C5 — float reassociation that breaks on edge values**
```cpp
double s = 0; for (...) s += x[i];        // → tree/pairwise or FMA reassociation
```
Differs on `NaN`/`inf`/catastrophic-cancellation inputs.
Judge's held-out FP edge cases catch the divergence → `UNSAFE` for a tool that only tested benign values.

### Category D — requires multi-objective judgement

**W-D1 — memoization: wins p50, loses memory & p99**
```cpp
// add a cache → median −30%, but peak memory 3×, and p99 worse (cache pressure)
```
Single-metric tools accept (it's "faster"); BOOSTOPT's Performance Vector rejects the **Pareto-loser**.

**W-D2 — benchmark-local win, cross-ISA / size regression**
A rewrite tuned to the bench CPU that regresses on a second machine or bloats binary size.
Held-out machine + size budget catch it.

### Controls — BOOSTOPT must NOT uniquely win these

**W-Ctrl1 (expected TIE)** — within-structure micro-op: `std::endl` → `'\n'`, or hoist a genuinely-invariant constant.
All tools should get it; BOOSTOPT has no edge.

**W-Ctrl2 (expected NOBODY WINS)** — dead code / constant folding that `clang -O3` already removes.
No tool may claim a win; verifies BOOSTOPT doesn't take credit for the compiler.

**W-Ctrl3 (expected BOOSTOPT LOSES)** — a compiler-report-driven vectorization CompilerGPT lands but BOOSTOPT's v0 transform set does not target.
Reported honestly as a loss.

---

## 5. Pre-registered predictions (commit before running)

| Case | BOOSTOPT | CompilerGPT | Codeflash-class | `clang -O3` |
|---|---|---|---|---|
| W-A1 map→umap | **WIN** | MISS | won't (arch) | can't |
| W-A2 O(n²)→O(n) | **WIN** | MISS | won't (arch) | can't |
| W-A3 →binary search | **WIN** | MISS | won't (arch) | can't |
| W-B1 hidden hotspot | **WIN** | MISS (chases report) | n/a | partial/none |
| W-B2 hot helper | **WIN** | MISS | n/a | maybe inlines |
| W-C1 overflow UB | **WIN** (reject) | **UNSAFE** | **UNSAFE** | n/a |
| W-C2 OOB read | **WIN** (reject) | **UNSAFE** | **UNSAFE** | n/a |
| W-C3 illegal hoist | **WIN** (reject) | **UNSAFE** | **UNSAFE** | n/a |
| W-C4 data race | **WIN** (reject) | **UNSAFE** | **UNSAFE** | n/a |
| W-C5 fp reassoc | **WIN** (reject) | **UNSAFE** | **UNSAFE** | n/a |
| W-D1 memo Pareto | **WIN** (reject) | SLOWER-accept | accept (single-metric) | n/a |
| W-D2 cross-ISA | **WIN** (reject) | accept | accept | n/a |
| W-Ctrl1 micro-op | tie | tie | tie | tie |
| W-Ctrl2 dead code | none | none | none | **already done** |
| W-Ctrl3 vectorize | **LOSS** | **WIN** | n/a | partial |

**If the actual results don't broadly match this table, the wedge claim is wrong — say so.**

---

## 6. The headline number (what you get to claim, if earned)

> Across the pre-registered C++ suite, **BOOSTOPT produced _N_ judge-verified speedups (correct ∧ safe ∧ faster) that CompilerGPT could not — _M_ of them because CompilerGPT's *accepted* change failed the judge's safety gate (`UNSAFE`), and _K_ because the fix required a structural/algorithmic change or the true hotspot the static report missed — while tying on every control and honestly losing W-Ctrl3.**

Specific, falsifiable, and survives a reviewer re-running the search.
Infinitely stronger than "unique and better than them all."

---

## 7. Fairness rules (non-negotiable)

1. **Pre-register**: commit this file (cases + predictions) before the first run. No adding/removing cases after seeing results.
2. **Best-config opponent**: give CompilerGPT its strongest setup (best model, its recommended prompts, user selects the right region). Beating a hobbled rival proves nothing.
3. **Same judge for all**: identical held-out inputs, identical sanitizer flags, identical benchmark protocol.
4. **Report every cell**: publish MISS, UNSAFE, SLOWER, LOSS — not just WINs.
5. **Separate the two BOOSTOPT claims**: *speed* wins (A/B/D) and *safety* wins (C) are reported separately; the safety wins are the load-bearing ones.

---

## 8. How to actually run it

**Prerequisite — the minimum BOOSTOPT build:** the trusted judge/gate (differential test + ASan/UBSan/TSan + perf vector) and **~6 transforms** covering A1–A3, B1, plus the *rejection* logic for C1–C5 and D1.
This is essentially v0 (BOOSTOPT.md §13) plus a handful of transforms — building the wedge test and building BOOSTOPT's core are the **same work**.

**Missing tooling to install first** (from BOOSTOPT.md §13): a runtime profiler (`perf`/Google Benchmark) for Category B; sanitizers ship with Clang 19 already (Category C is reachable now).

**Procedure:**
1. Freeze the 15 cases as compilable C++ projects, each with a hidden held-out input generator.
2. Run each tool → collect its variant per case.
3. Run the single judge over all variants → fill the verdict matrix.
4. Compare against the §5 predictions; write up matches *and* misses.

---

*This test is designed to be able to embarrass BOOSTOPT.
That is the point: a wedge you can only pass by cheating is worthless, and a wedge you might fail is the only kind worth running.*
