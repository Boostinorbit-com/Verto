# VERTO — State & Build Plan

**Where VERTO is today, and the complete, ordered list of everything to build to make it a real product — explained so you never have to ask "and then what?"**

Companion to `VERTO.md` (concept), `VERTO_Architecture.md` (blueprint), `VERTO_Surfaces.md` / `VERTO_Flags.md` (CLI), `WEDGE_TEST.md` (proof).

---

## 1. What VERTO is (one minute)

VERTO is a **verified C++ optimizer**. It has two parts:

- A **proposer** suggests a change to your source code (today: hand-coded rules; later: an LLM). It is **untrusted** — it's allowed to be wrong.
- A **trusted gate** accepts a change *only* if it **compiles, produces identical output on test inputs (differential test), passes sanitizers (no undefined behavior), and is measurably faster** — otherwise it rejects it.

**The moat:** the gate *runs* real code to *prove* the change. A tests-only tool accepts changes that pass its tests but secretly rely on undefined behavior or change output order — VERTO rejects those. The compiler, meanwhile, can't make the changes VERTO makes (it can't prove a container's final size, and it won't swap a data structure). **VERTO lives in the gap between "what tests catch" and "what the compiler does."**

---

## 2. Where it is today (honest, concrete)

**Done — Phase 1 complete (v0).** The gate is real (real `clang++`/`g++`, ASan/UBSan, benchmarks) and now works on **real projects**, not just self-contained toy files: it verifies a function that **calls into other translation units** (links against the real build), at the project's **actual compile flags**, **aimed by a real profiler**, checked on **~1000 seeded fuzzed inputs**, and optionally **re-confirmed by the project's own test suite**. It **parses real CMake projects** (the `-isystem`/header/`-fPIC` fixes), reports **skips with reasons**, **scales** with `--changed` + `--jobs`, and **applies transactionally** (atomic writes, all-or-nothing rollback). A warm **daemon** + caches keep it fast. Backed by **53 tests** and its falsifiable benchmark, **13/13**.

**Not done — the honest boundary:**
- **Only 5 hand-coded transforms**, all targeting `std::` containers (`reserve`, string `reserve`, `map→unordered`, `unordered_map reserve`, pass-by-`const&`). On code that uses *other* container types (e.g. Qt's `QString`/`QVector`), VERTO finds **0 opportunities** — **transform / container-type coverage is the top gap**, ahead of everything else. *Phase 2 closes this together with the oracle-reach gap.*
- The **LLM proposer is still a stub** — `frontier.py` raises `NotImplementedError`. The "AI" does not exist yet.
- Input coverage for custom types is **synthesis only** (aggregate structs of primitive fields); **capturing real argument values** from a run is future work (#2-B2).
- A real **test suite** exists (53 tests + the wedge), but there is **no CI** yet.

**In one line: a real verification engine that works on real projects *mechanically* — but its 5 hand-coded transforms still only match `std::` containers, it can only harness simple signatures, so it finds 0 verified wins on real repos. Closing that is Phase 2.**

---

## 3. The one idea that makes the whole plan obvious: two axes

Almost every question about VERTO dissolves once you separate two **independent** things:

| Axis | Question it answers | Today | The upgrade |
|---|---|---|---|
| **VERIFY** | can the gate *check* a change on real code? | **mechanically** on real projects (Phase 1 ✅), but only *simple signatures* | **real reach: the project's own tests as oracle → Phase 2** |
| **PROPOSE** | *what* change should we try? | 5 hand-coded rules (`std::` only) | more transforms (**Phase 2**), then the LLM → **Phase 3** |

Think of it as an **idea generator** (PROPOSE — the LLM) and a **fact-checker** (VERIFY — the gate).

**The consequence — and the reason the plan is ordered the way it is:** a better idea generator is worthless if the fact-checker can't check ideas about real code. So **making VERIFY work on real projects comes first.** The LLM (a better PROPOSE) is only useful *after* that — otherwise it proposes changes the gate can't verify, and they're all thrown away. **The LLM is not what makes VERTO work on real projects; the harness is.**

---

## 4. The complete build plan

Everything to build, grouped into phases. Each item: what it is (plain English), why, and the file(s) it touches.

**How to read the numbers:** they are **grouping + rough priority, not a strict must-follow chain.**

Only a few orderings are truly load-bearing:

- **#1 is the sole hard prerequisite** — you can't verify real code without it.
- **All of Phase 1 must precede Phase 2** (real-world reach), and **all of Phase 2 must precede the LLM (Phase 3)** — a better proposer is useless if the gate can't *reach* real functions.
- **Sandbox hardening (#13) must land before running LLM-generated code (#10).**

**Phase-2 item IDs are letters (2A–2D)** so the original stable integer IDs (#1–#23) are untouched; only the later *phase labels* shifted (LLM → Phase 3, hardening → Phase 4, commercial → Phase 5).

Those hard edges are drawn in §5.

**Everything else inside a phase is a menu you order by impact** — e.g. #4 (log skips) is worth doing before #2 (capture & replay, POD/aggregate slice) not because #2 depends on it, but because it cheaply tells you whether #2 is the biggest lever on *your* repo. Reorder freely within a phase; respect the §5 edges.

### Phase 1 — Make it work on real C++  *(the foundation — nothing else matters without this)*

**Recommended order:** #1 ✅ → #4 ✅ (skip log) → #6 ✅ (real build flags) → #5 ✅ (aim at hot code) → #3 ✅ (test-reuse oracle) → #2 ⏳ (capture & replay — aggregate synthesis done; real-value capture remaining) → #7 ✅ (seeded fuzzed inputs) → #8 ✅ (scale: --changed + --jobs) → #9 ✅ (safe apply). **All Phase-1 items are done (v0).** *Next real lever is transform/container coverage (per the measure-first finding), then Phase 2.*

The blocker: today VERTO can only build a test program for a **self-contained** function. Real functions call other code and use real types, so it skips them. Fix that:

1. **Link-against-the-build** ✅ **done (v0)** — instead of copying a function into a standalone test, compile the test and **link it with the project's real compiled code** (a cached static archive of the other TUs), so the function can call its real dependencies. *Unblocks the biggest chunk of real functions.* Proven on `examples/linked/` (a function calling into another TU → reserve accepted, −55.8%). — `link.py`, `build.py`, `_verify.py`, `correctness.py`. *v0 scope: builds the other TUs at their `-I/-D/-std` + `-O2` (exact `-O`/PCH parity is item #6).*
2. **Capture & replay** ⏳ **v0 slice done (aggregate synthesis)** — VERTO now **synthesizes inputs for functions taking a simple aggregate struct** (all public primitive fields; no user ctor / base / virtual) by brace-initializing it field-by-field. Sound for the differential test (the *same* synthesized input feeds orig + variant), with a size-vs-value heuristic so count fields stay large (reserve win stays measurable) and signed fields stay small (no overflow UB — which UBSan would rightly reject). Proven: `scaled_series(const Config&)` flipped **SKIP → ACCEPT (−68%)**; a raw-pointer param stays an honest skip. *Remaining — the "record real values" half: capture actual argument values from a real workload run, for types synthesis can't safely build (pointers / handles / class invariants) and for representative perf.* — `_ast.py` (`aggregate_fields`), `harness_gen.py` (`_classify_param`); example `examples/linked/report.cpp`
3. **Test-reuse oracle** ✅ **done (v0)** — `--test-command` runs the project's **own test suite** to re-confirm each accepted change (build the variant into the real source → run the tests → restore); honest verify-or-skip — if the original already fails its tests, the oracle stands down rather than blame the change. *The project's real acceptance criteria catch what the synthetic harness's fixed inputs miss.* — `reuse.py` (`TestReuseOracle`), `gate.py`, `registry.py`, `config.py`, `cli.py`; example `examples/tested/`. *v0 scope: a confirmatory gate on changes the harness already verifies; using tests to verify functions the harness CAN'T (the coverage-widening case) additionally needs a project-level perf signal — a follow-on that pairs with #2.*

> **#2 / #3 are the big coverage lever — and the largest Phase-1 work.** Everything else in Phase 1 makes verification *real, honest, and targeted* on the functions VERTO can **already** harness. #2/#3 widen **what can be harnessed at all**. The crux: **C++ has no reflection**, so "capture the real arguments and replay them" means solving serialization for arbitrary types.
>
> - **A — Test-reuse oracle (#3) ✅ done (v0).** Runs the project's *own* tests against the variant. No serialization needed. Shipped as a **confirmatory** gate on harnessed changes; using it to verify *un-harnessable* functions still needs a project-level perf signal.
> - **B1 — Aggregate synthesis (#2) ✅ done (v0).** Synthesize inputs for functions taking a simple aggregate struct (public primitive fields) by brace-initializing it — no run needed, sound for the differential test. Unblocks the custom-*data*-type skips.
> - **B2 — Capture real values from a run (#2) — next.** Codegen a recorder that logs the actual argument bytes a function receives during a real workload run, and replay them. Needed for types synthesis can't safely build (pointers/handles/invariants) and for representative perf.
> - **C — Capture & replay, full (#2).** Recorders for arbitrary types (pointer graphs, resources). The real prize, and a multi-week research effort on its own.
>
> **Measure-first check — done, and it re-ranked the plan.** Running the item-#4 skip breakdown on real CMake/Qt repos showed VERTO couldn't even *parse* them: a `_dedup` bug orphaned every repeated `-isystem` path, quoted project headers weren't on the search path, and Qt's `-fPIC` guard tripped. **Fixed all three (12/12 TUs now parse).** After that, those GUI TUs yielded **0 candidate sites** — they use `QString`/`QVector`, not `std::` containers. **Conclusion: B2 is *not* the next lever.** The real levers are (1) parse robustness ✅ just fixed, and (2) **transform/container coverage** — recognizing the project's actual container types. B2 waits for a corpus where synthesis-blocked custom-type inputs actually dominate the skips (e.g. a std-heavy systems/DPDK repo, not GUI code).
4. **See what's skipped** ✅ **done (v0)** — a candidate site VERTO can't verify is now reported as a **SKIP with a reason** (unharnessable signature → *which parameter/return type*; TU parse errors) instead of being silently dropped; codebase mode prints a **scan summary + skipped-reason breakdown**. *On a real repo you must know why 90% of files were skipped.* — `models.py` (`Skip`), `sensor.py`, `harness_gen.py` (`unsupported_reason`), `_ast.py` (`parse_errors`), `orchestrator.py`, `api.py`, `cli.py`
5. **Aim at the hot code** ✅ **done (v0)** — `--profile FILE` now **consumes a real profile** (`perf report --stdio` / `gprof` flat / JSON / `symbol cost`), reduces each symbol to its leaf name, and selects the candidate that's actually hot in the user's workload — overriding the synthetic micro-benchmark. Proven: a profile that says the micro-bench's *cold* function dominates flips the selection. *A real repo has thousands of functions; you can't try them all.* — `profile.py` (parser), `sensor.py`, `config.py`, `cli.py`. *v0 scope: used for SELECTION among detected candidates; cold-function pruning + auto-running the profiler are follow-ons.*
6. **Build like the real project** ✅ **done (v0)** — the timed build now reuses the project's **actual codegen flags** (`-O` level, `-march`/SIMD, safe `-f…`, `-pthread`) from `compile_commands.json`, appended so they override VERTO's `-O2` default; defines/`-std` were already threaded. *The measured speedup now reflects the real build.* — `compile_db.py` (`_extract_opt_flags`), `_verify.py`, `gate.py`. *v0 scope: debug levels (`-O0`/`-Og`) fall back to `-O2` (benchmarking at `-O0` measures nothing); LTO/PCH/sanitizer/profile plumbing deliberately dropped.*
7. **Stronger correctness** ✅ **done (v0)** — the differential test keeps its hand-picked edge cases and adds `--fuzz N` (default 1000) **seeded** random sizes (the previously-dead `fuzz_inputs`/`seed` are wired), so it checks ~1000 points instead of 10. **Deterministic** (fixed seed → same inputs → reproducible verdict + stable learning log); **bounded** (mostly small where off-by-one bugs live, some medium — negligible runtime, compilation dominates). *"Correct on 10 inputs" is thin for real code.* — `inputs.py`, `config.py`, `cli.py` (`--fuzz`/`--seed`). *Note: the wedge's sanitizer-demo (Category-C) cases pin fuzz off so the "diff-test passes → sanitizer catches" scenario stays deterministic.*
8. **Scale** ✅ **done (v0)** — make VERTO fast enough to run on a *whole* real repo, not just a handful of files. Verifying one function is inherently slow (compile original + variant, sanitize, benchmark ≈ a few seconds); a real codebase has **thousands** of functions, so a naive full scan takes **hours**. Two parts, both shipped:
   - **(a) `--changed [REF]`** — restrict the run to the TUs git reports as modified vs REF (default: the working tree; plus untracked files). A 5-file PR checks 5 files, not 5,000 — also the natural shape for CI (item #18).
   - **(b) `--jobs N`** — process N translation units in parallel. Verification is subprocess-bound (clang/benchmark), so threads give real speedup — **measured 2.3× on a 3-TU example, identical results to sequential.** Required three thread-safety fixes: thread-local libclang parse flags (was a module global), thread-unique temp names (were pid-only → collided), and a locked ledger.

   *Default is `--jobs 1` (sequential, precise); parallelism is opt-in because benchmarking under load is noisier. This is a **throughput** item, not a capability one — on current evidence (parsing fixed, but 0 `std::`-container sites on the sampled GUI code) transform/container coverage still ranks ahead of more scale work.* — `cli.py` (`--changed`/`--jobs`), `api.py` (`_git_changed`, parallel `optimize_codebase`), `_ast.py`/`link.py`/`build.py`/`ledger.py` (thread-safety)
9. **Safe apply** ✅ **done (v0)** — make writing changes to a *whole codebase* trustworthy. Verifying a change proves it's correct; **applying** it across many files is a separate risk — a crash, a write error, or a file that drifted since it was verified can leave the tree half- or mis-edited. Shipped as an `ApplyTransaction`:
   - **(a) transactional / all-or-nothing** — one transaction wraps a whole codebase `--apply`; every write is snapshotted and **atomic** (temp file + `os.replace`, so a reader never sees a half-written source). Any failure mid-run rolls back *all* files to their originals; clean completion commits. Thread-safe, so it holds under `--jobs` (item #8).
   - **(b) anchored, refuse-to-mis-apply** — the mutator already splices at the exact AST byte offset, and the gate recompiles + re-runs every splice (a broken one is already rejected). Added on top: a **stale-file guard** that refuses to write when the file on disk no longer matches the exact source that was verified — *a correct transform applied to changed text is still a bug*.

   *Never leave a half-edited or mis-edited codebase — the moment a user can't trust `--apply`, they stop using it.* — `apply_txn.py` (`ApplyTransaction`), `orchestrator.py`, `api.py`. *v0 scope: the remaining ambiguity case (a splice that mis-lands but still compiles *and* passes — e.g. inside an inactive `#ifdef`) is backstopped by the gate's recompile; a dedicated macro/`#ifdef`-site refusal is a follow-on.*

→ **After Phase 1: VERTO can find and verify real optimizations in a real repo with its 5 rule transforms — but *only* on functions with simple signatures and `std::` containers, which is why it finds 0 wins on most real code. Phase 2 widens both.**

#### Phase 1 must also close these — correctness & coverage completeness ✅ **done (v0)** *(gaps in the safety guarantee, not polish)*

These closed the holes where the gate proved less than "same behavior":

- **1a. Thread-safety rung (TSan) ✅.** A data race is UB that ASan+UBSan can't see, and it only surfaces under concurrency — so the harness gained a **concurrent "race" mode** (calls the function from 4 threads) and the gate runs a **ThreadSanitizer** build of it. Gated on a `static` local in the variant (only a transform that adds shared mutable state can introduce a race), so pure functions pay nothing; TSan can only *downgrade* a clean result. Verify-or-skip when the toolchain has no working TSan. MSan probed too (clang-only + instrumented-libc++ → usually unavailable, skipped cleanly). — `correctness.py`, `build.py` (`tsan_toolchain`/`msan_toolchain`), `harness_gen.py` (race mode)
- **1b. Floating-point tolerance oracle ✅.** `--fp-tolerance REL` compares output **numerically within a relative tolerance** instead of byte-for-byte, so a legit FP-reordering transform (reassociation/SIMD/`fma`) is accepted; default 0 keeps the strict diff-test. Also **un-blocked `vector<float/double>` returns** (the harness now prints values, which is both tolerance-comparable and more reliable than hashing FP bits). — `correctness.py` (`_outputs_match`), `harness_gen.py`, `config.py`, `cli.py`
- **1c. Side-effect refusal ✅.** VERTO now **refuses** (honest skip-with-reason) a function that touches a non-const **file-scope global** or does **I/O** — behaviour the stdout-only diff-test can't compare — rather than falsely calling it equivalent. Function-local statics are intentionally left to 1a/D. — `_ast.py` (`side_effect_reason`), `sensor.py`
- **1d. Templates named ✅.** Optimizable function **templates** (which can't be harnessed without a concrete instantiation) are now reported as **skips with a reason** instead of silently ignored. — `_ast.py` (`template_candidates`), `sensor.py`

*Honest v0 boundary: on this machine TSan/MSan aren't installed, so 1a is wired + probed but skips (verify-or-skip) — same as ASan falling back to g++; the mechanism is tested where a working TSan exists. 1c refuses (doesn't yet capture/compare) side effects; full effect-diffing is a follow-on.*

### Phase 2 — Real-world reach: a verified win on YOUR code  *(the bridge the measure-first check exposed — must precede the LLM)*

**✅ DONE (v0) — all four items (2A–2D) shipped and proven, including all three 2A sub-parts (2A-1 TU-targeting, 2A-2 primary oracle, 2A-3 full Pareto gate). Verified green (81 tests + 1 skip, wedge 14/14, transform library 5 → 7).** Phase 1 made the gate *mechanically* real on real projects (it links against the build, uses the project's flags, follows a profiler, fuzzes ~1000 inputs, applies transactionally). But the Phase-1 measure-first check had exposed the uncomfortable truth: on real third-party repos VERTO found **0 verified wins** — for two *structural* reasons, not bugs:

1. **Oracle-reach ceiling** — the synth harness can only build an oracle for `f(size_t)`, `std::vector<primitive>`, `std::string`, and simple aggregates. Real functions are **methods on classes, multi-param, user types** → honest SKIP.
2. **Coverage ceiling** — the 5 transforms match only `std::`-container idioms; real hotspots (`std::list`, lookup patterns, needless copies) aren't recognized.

A trustworthy gate that never fires on real code has no value *yet*. **Phase 2 closes exactly these two ceilings and proves it with one real accepted-correct-and-faster patch on an actual repo.** This is also the true prerequisite for the LLM: the roadmap's own §3 rule ("VERIFY on real code before PROPOSE") applies here — the LLM (Phase 3) would just propose changes that Phase 2's reach is needed to verify.

**North-star proof-point (locked):** *VERTO ingests a real third-party C++ project, uses the project's **own tests** as the oracle (2A), and produces at least one verified faster-and-correct patch — end to end.* **Target repo: the local `cList` project** (known, has the `std::list` pattern 2B-1 targets, and is self-verifiable), with a **small well-tested OSS lib** as fallback if cList lacks a usable `ctest`/test suite for 2A. **First task: 2A** (the test-reuse primary oracle) — nothing else in Phase 2 can produce a real win without it.

**Recommended order:** **2A** (oracle reach — the keystone) → **2B** (coverage for real patterns) → **2C** (repo-scale patch series) → **2D** (stretch: metamorphic rung). *2A is first because 2B and 2C still hit the signature ceiling without it.*

> **Item IDs:** Phase-2 items use letter IDs (**2A–2D**) so the original stable integer IDs (#1–#23) stay untouched. Inserting this phase shifts the *labels* of the later phases (LLM → **Phase 3**, hardening → **Phase 4**, commercial → **Phase 5**) but **not** their item numbers.

**2A. Oracle reach via test-reuse** ✅ **done (v0)** — *the keystone; removes the signature ceiling.* **All three sub-parts built and proven** (2A-1 TU-targeting, 2A-2 primary mode, 2A-3 full Pareto gate). **Proven two ways:** (1) manual — `scaled(const std::map<int,long>&, int)` (unharnessable) flips **SKIP → ACCEPT (−20%)** via `--test-command` + `--bench-command` (`examples/reach/`); (2) **auto-discovered** — pointing `--ctest-dir` at a real **CMake build** flips the same function **SKIP → ACCEPT (−39%)** with **zero hand-written commands** (`tests/fixtures/cmake_project/`).
Promote `reuse.py` from a **confirmatory** gate to a **primary** oracle: verify a function VERTO **cannot** synth-harness by using the project's own test suite as ground truth + a project-level perf signal. *This is the single change that makes "your code" verifiable at all.*
- **2A-1 Test-target discovery** ✅ **done** — `--ctest-dir DIR` enumerates the project's ctest tests **and finds which ones exercise the target TU**: it reads the TU's compiled object for its strong function symbols (`nm`) and keeps only the tests whose executable references them. Optimizing `stats.cpp` runs `stats_correctness` + its bench and **excludes** the unrelated `other_correctness` (proven in `tests/test_2a1_ctest_discovery.py`). Derives the targeted **test_command** (`cmake --build … && ctest -R '^(targeted…)$'`) + the bench's **direct executable** (for 2A-3). **Sound fallback:** if nm/symbols can't resolve, it runs the whole suite — narrowing can only drop tests that *cannot* touch the change, never one that could catch it. — `cmake_ctest.py` (`discover_ctest`/`_tu_symbols`/`_exercises`), `config.py`, `cli/`. *v0: symbol-reference targeting (assumes the test calls the changed code directly; indirect/dlopen refs fall back to the whole suite); single-file mode (codebase mode runs the whole suite).*
- **2A-2 Primary-oracle mode** ✅ **done** — every clause matches: the sensor routes an unharnessable-signature function to test-mode; the gate builds the variant into the real source → runs the tests → restores; ACCEPT only if tests still pass **and** the project bench improves. `sensor.py`, `gate.py` (`_decide_via_tests`), `reuse.py` (`confirm`).
- **2A-3 Project-level perf signal** ✅ **done** — the project bench is now gated by the **full Pareto vector** — the same rule the micro-harness uses: a **p50** win beyond `--min-speedup` **and** no regression past budget on **p99** (tail latency) or **peak_memory**. When 2A-1 discovers the bench's **direct executable**, VERTO builds once (`build_command`) then times the run-only binary N times via `os.wait4` → clean p50/p99 **and** the bench's own peak RSS (not the compiler's); a manual `--bench-command` (shell build+run) gates on p50+p99 (peak is build-masked → omitted). **Proven:** ctest fixture → ACCEPT **−69% p50** with a full `{p50, p99, peak_memory}` vector, and a synthetic p99/peak regression is **rejected** (`tests/test_2a_reach.py::test_pareto_gate_rejects…`). — `reuse.py` (`bench`/`_measure`/`_pareto`), `cmake_ctest.py` (direct bench exe + `build_command`), `config.py` (`bench_argv`/`build_command`). *One clause stays intentionally NOT done: timing an arbitrary **"test binary"** — a trivial unit test is noise-dominated → could falsely accept, so no bench → honest `perf_unproven`. Not core-pinned.*

  *Acceptance (met both manually and via `--ctest-dir`):* a non-synthesizable-signature function flips **SKIP → ACCEPT**, confirmed by the project's tests + a measured project-level speedup. `tests/test_2a_reach.py`, `tests/test_2a1_ctest_discovery.py`. — `reuse.py`, `gate.py`, `sensor.py`, `cmake_ctest.py`, `config.py`, `cli/`

**2B. Coverage for the patterns real code actually has** ✅ **done (v0)** — *measure-first each (the `pow(x,2)→x*x` lesson: clang already recovered it, so it was dead).* **Two flagship transforms shipped; 2B-3/2B-4 measured and queued.**
- **2B-1 `std::list → std::vector`** ✅ — the `cList` case. Precondition (checked structurally + gate-backstopped): the list is only grown at the back and iterated — **no `push_front`/`splice`/middle-insert/erase/list-only-reorder**. **Proven:** `list_sum` (build+iterate a `std::list`) → **ACCEPT −72%**, Rung 3; measure-first showed ~20× on build+iterate. `push_front`/`splice` correctly **refused**. `examples/list_build.cpp`, wedge **A5-list-vector**, `tests/test_list_to_vector.py`. — `transforms/list_to_vector.py`, `analysis/detect.py` (`all_list`)
- **2B-2 Map-lookup fusion** ✅ — `if (m.count(k)) … m.at(k)/m[k]` → one `find(k)`. **Measure-first re-ranked the niche:** ~31–45% on **`std::map`** (tree walks), but only ~4% on `unordered_map` (cheap hashes) — and where a map's order isn't observed, `map→unordered_map` is the bigger win VERTO **correctly prefers**, so fusion's niche is **order-constrained `std::map`**. **Proven:** `count_hits` → **ACCEPT −45%** (fusion isolated), Rung 3. A control-flow rewrite (not a type-swap): matched narrowly (exact `count(k)` cond, single-token key, same-key access) for soundness. `examples/map_lookup.cpp`, `tests/test_fuse_map_lookup.py`. — `transforms/fuse_map_lookup.py`, `analysis/detect.py` (`all_fuse`)
- **2B-3 Copy → move / `emplace`** ⏳ **measured, queued** — `push_back(lvalue)` → `push_back(std::move(lvalue))`. Measure-first: **~26%** for a heavy dead element (`std::string`). *Deferred because soundness needs **last-use/liveness analysis** (moving a still-used lvalue is a use-after-move bug) and the gate is a **weak** backstop here — a moved-from value is "valid but unspecified", so a bad move may not change observable output. Ship only with a sound last-use check (loop-local var whose last use is the push_back).*
- **2B-4 (opportunistic)** ⏳ **deferred** — `string +=` concat batching, `std::endl → '\n'`.

  *Recipe proven twice more (a transform ≈ detector + subclass + example + test, **sensor untouched** — the generic-sensor payoff): the transform library grew 5 → **7**. Acceptance: each ships with an example + tests + a measured win; measure-first kills/curbs any the compiler already recovers (2B-2's unordered_map case) or that isn't soundly gateable yet (2B-3).* — `transforms/<name>.py`, `analysis/detect.py`, `transforms/__init__.py`

**2C. Repo-scale workflow — one-file demo → reviewable patch series.** ✅ **done (v0)** — **Proven:** `--emit-patches DIR` writes a **ranked** `REPORT.md` (verified wins, biggest speedup first, with the correctness basis per row) + one numbered `.patch` per accepted change; the patches are real unified diffs that pass **`git apply --check`** (verified in `tests/test_2c_patches.py`). Works in both single-file and whole-repo (`compile_commands.json`) mode; the consolidated ledger is the machine-readable companion. — `orchestrator.py` (`_unified_diff`, `Verdict.udiff`), `surfaces/patches.py`, `cli/` (`--emit-patches`). *v0 scope: ranked by measured p50 delta (profile-weight ranking is a follow-on); `--pr` auto-open is deferred.*
Turn the whole-repo sweep (already `--changed`/`--jobs` capable) into a *deliverable*: sweep all `compile_commands.json` TUs, **rank** findings by measured delta × profile weight, and **emit a patch series / PR** with one consolidated ledger and a human-readable report of each verified win (before/after, delta, rung).
- **2C-1 Ranked findings report** — ordered by impact, honest about what was skipped and why.
- **2C-2 Patch-series / PR emission** — `--emit-patches DIR` (or `--pr`); each commit = one verified transform with its evidence in the message.
- **2C-3 One consolidated ledger + run summary.**

  *Acceptance:* `verto optimize <repo> --emit-patches` produces N individually-verified, applyable patches on a real project, each carrying its evidence. — `orchestrator.py`, `api.py`, new `surfaces/patches.py`, `ledger.py`, `cli.py`

**2D. (stretch) Metamorphic / property rung — reach where no tests exist** ✅ **done (v0)** — *Rung 2 in the ladder.* **Proven:** an opt-in (`--metamorphic`) property oracle checks **permutation invariance** (`f(v) == f(shuffle(v))` for a `std::vector<int>→int` reduction) and **rejects a change that broke a property the original had**, even when the fixed-input differential test passed. **Sound — rejects only:** stands down (no effect) when the signature is wrong or the original isn't invariant; catches an invariance-breaking variant (both proven in `tests/test_2d_metamorphic.py`). `byval_sum` → still ACCEPT, verdict annotated `permutation-invariance`. — `metamorphic.py` (`MetamorphicOracle`), `gate.py`, `registry.py`, `config.py`, `cli/`. *v0 scope: one property (permutation invariance) for integer vector reductions; more properties (idempotence, additivity) and using the rung to ACCEPT otherwise-unverifiable functions are follow-ons.*
For functions with neither a synth-harness nor a covering test, add **metamorphic checks** — properties that must survive the transform (permutation-invariance for order-independent reductions, idempotence, output-size relations) — as a real-but-weaker correctness rung **between** the differential test (Rung 1) and sanitizers (Rung 3). Extends verified reach to untested, unharnessable code without needing an exact-output oracle.

  *Acceptance:* a function that's currently an honest skip gets a **conditional** verdict under a stated property, flagged in the verdict as weaker than Rung 1/3; opt-in. — `correctness.py` (Rung 2), new `metamorphic.py`, `config.py`

→ **After Phase 2: VERTO produces verified, faster-and-correct patches on real third-party repos — using the project's own tests as oracle and a coverage set that matches real code. This is the milestone that makes VERTO *useful* — and the real prerequisite for the LLM.**

### Phase 3 — The AI / LLM  *(needs Phase 2 first)*

**Recommended order:** **#13** (sandbox hardening — a hard edge: it must land before any generated code runs) → **#10** (LLM proposer) → **#11** (multi-candidate) → **#12** (cost cap).

Now that the gate can verify *and reach* real functions, add a proposer that suggests far more than the hand-coded rules:

10. **The LLM proposer** — implement `frontier.py` (a stub today): send the model the source + a compact summary of the code, and parse its reply into a change. *Proposes arbitrary optimizations, not just the hand-coded ones.* — `frontier.py`
11. **Try several, keep the best verified** — ask the model for N proposals per hotspot, run each through the gate, keep the winner. *The model is hit-or-miss; the gate is the filter.* — `orchestrator.py`, `config.py`
12. **Cost cap** — a `--budget` limit per hotspot. *LLM calls cost money.* — `config.py`, `cli.py`
13. **⚠ Harden the sandbox — REQUIRED here** — you are now running **code the LLM wrote**. Today the sandbox is only a CPU limit (`sandbox.py`). Add **filesystem + network isolation and a memory cap**. *Untrusted generated code must not touch your machine or network.* — `sandbox.py`

→ **After Phase 3: VERTO proposes optimizations beyond the hand-coded set — the actual "AI optimizer."**

### Phase 4 — Product hardening  *(to ship it, free)*

**Recommended order:** **#15** (tests + CI — protects everything after it) → **#14** (more transforms, ongoing) → **#16** (packaging) → **#17** (launch).

14. **More transforms** — 5 → ~10–12 hand-coded ones (the Phase-2 2B set — `list→vector`, lookup fusion — continues here). *Runs in parallel with Phase 3.*
15. **Tests + CI** — a real test suite + GitHub Actions so a change can't silently break the tool.
16. **Packaging** — installs cleanly on a fresh machine; clear errors when a tool (clang, sanitizers) is missing.
17. **README + demo + public launch.**

### Phase 5 — Commercial  *(to sell it)*

**Recommended order:** **#18** (CI / GitHub Action — the paid surface) → **#19** (hosted) → **#20** (billing) → **#21** (legal + security, running in parallel throughout).

18. **CI / GitHub Action** — runs on every pull request and comments the verified findings. *The paid surface.*
19. **Hosted / cloud** — no local setup for the user; needs a build farm + a shared cache of verified results.
20. **Billing, accounts, dashboard** — open-core: the tool is free, the paid tier is CI + cloud + the AI proposer.
21. **Legal + security review** — handling customers' private code (data policy, on-prem option).

### Later
22. **Formal verification (Alive2)** — the strongest correctness rung.
23. **Shared transform library** — the ledger becomes a growing library of proven optimizations (the flywheel).

---

## 5. The dependency picture (why the order is fixed)

```
Phase 1   Verify on real code (mechanically)   ──►  MUST come first  ✅
               │
               ▼
Phase 2   Real-world reach                       the bridge: tests-as-oracle (2A) + coverage (2B)
          (a verified win on YOUR code)          + repo-scale patches (2C) — closes the reach gap
               │
               ▼
Phase 3   LLM proposes                           (useless before the gate can REACH real functions)
   +      Sandbox hardening                      (mandatory once running untrusted generated code)
               │
               ▼
Phase 4   Harden + ship (free)
               │
               ▼
Phase 5   Commercial surfaces + business
```

---

## 6. Two paths, and the one thing to do first

- **Path A — verified-transform product (no LLM):** Phases 1 + **2** + 4 + 5. Sell *"the performance tool that never ships a regression or a UB bug."* ~4–6 months, low risk, plays to the moat. **Phase 2 is what makes this path real** — without it there are no wins to sell.
- **Path B — AI optimizer:** add **Phase 3** (the LLM). The marquee feature, but the hardest and longest. ~8–12 months.
- **Either way, Phases 1 and 2 are identical and come first.**

> **Task one is now Phase-2 item 2A: the test-reuse *primary* oracle.** Phase 1 is done, but it turns "0 verified wins on a real repo" into "N" only once the gate can *reach* real functions — and 2A (verify via the project's own tests) is what removes the signature ceiling. The **LLM is item #10 (Phase 3)** — a multiplier that only pays off *after* Phase 2 makes the gate able to reach and win on real code.

---

## 7. Known boundaries (documented, not yet scheduled)

Things a real user will hit that are deliberately out of scope for now — named here so they're conscious choices, not surprises:

- **Function-local, not whole-program.** The gate proves the *harnessed function* is equivalent on its own I/O — it does **not** see effects observed elsewhere. Swapping a *member/global* `std::map` for `unordered_map` is only sound if **no other function relies on its order**; the same holds for any change to shared state. This **bounds the transform catalog**: only transforms whose entire effect is contained in the function's observed behavior are safe to auto-apply. A locally-green change can still be globally wrong.
- **Verdicts are only as representative as the inputs.** "Measurably faster" means *faster on the inputs tested* (today 10 fixed sizes); an optimization can win on those yet lose on the real production distribution or asymptotically. Capture-&-replay (item 2) narrows this, but it never fully disappears.
- **Build systems.** Verification needs a `compile_commands.json` (CMake/Ninja emit it; Bazel via a converter). Plain Make and MSVC projects aren't supported without one.
- **Benchmark noise on shared/cloud hardware.** Wall-clock variance in CI can swamp a small win; the hosted tier (item 19) will need a deterministic proxy — `perf stat` instruction count / cachegrind — alongside wall-clock, or verdicts will flap.
- **Sending source to a frontier LLM.** Many enterprises won't allow proprietary code to leave their network, so the LLM tier (Phase 2) needs a **local-model or redaction path** — a technical requirement, not just the legal review in item 21.
- **Post-apply reality check.** Nothing yet confirms the promised speedup held in the customer's production build/hardware; a "did the win stick?" telemetry loop is what compounds trust over time.
