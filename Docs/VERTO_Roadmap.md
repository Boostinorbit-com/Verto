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

> **Real-world validation & harness reach — measure-first, 2026-07-25.** Before committing to Phase 3, we ran the complete Phase-2 VERTO on **cloned real repos** — and it re-ranked the near-term work with evidence:
>
> - **jsoncpp** (a mature, well-tested library): parses cleanly (7 TUs, 0 parse errors) and finds **0 wins — *correctly*.** Every `reserve()` VERTO would propose is *already hand-written*; the rest are member containers it refuses to touch. **Soundness holds on real code (0 false positives)**, but the syntactic transforms are **exhausted on mature libraries** — which is itself *evidence for* the LLM (Phase 3): what's left on good code is the non-obvious/algorithmic wins only a smarter proposer finds.
> - **TheAlgorithms/C++** (un-optimized student code): candidates everywhere — and running it surfaced **two real harness *reach* bugs**, both now fixed:
>     - **✅ `main()` collision** — every real `.cpp` ships its own `int main()`, which collided with the harness driver. `harness/template.py — _neutralize_main` renames it (`int main(` → `int _verto_user_main(`). **Unblocks essentially every real single-file program** (a no-op on the header-style example files).
>     - **✅ namespace resolution** — a function inside `namespace ns { … }` didn't resolve from the driver's unqualified call. `analysis/types.py — qualified_name` walks the AST `semantic_parent` chain to emit `ns::fn`; `template.py` uses it in the call. No-op for global functions.
> - **Verified wins on real third-party code** (sanitizer-clean, Rung 3): `text_search.cpp — lower` −17.5%, `base64_encoding.cpp — base64_encode` −22…55%, `vigenere_cipher.cpp — encrypt` −16% (all `reserve_string`). The `pass_by_const_ref`-on-DP-function attempts **REJECT** — the gate correctly declining non-wins.
>
> **Harness-reach gaps — one fixed since, two open:**
> - **✅ range-based `for (x : container)` loops now detected** (2026-07-25) — the reserve detectors only saw counted `for(i=0;i<n;i++)` loops and *entirely missed* range-loops (a `CXX_FOR_RANGE_STMT` they didn't even collect). Now all three growth detectors collect both, and the bound is `container.size()` (only for a plain-name range — a call/subscript range is skipped to avoid double-evaluation; reserve is a capacity hint so any bound is behavior-preserving, and the gate verifies faster). **Unlocked 9+ new sites in a sample of TheAlgorithms + wins like `xor_cipher — encrypt` −37%, `range_reserve — map_doubled` −74%.** — `analysis/detect.py` (`_range_bound`/`_loop_bound`/`_loops`), `tests/test_range_reserve.py`.
> - ⏳ **`while` / manual-iterator loops** — still missed (harder: no obvious `container.size()` bound to derive);
> - ⏳ **nested-container param synthesis** (`vector<vector<int>>`) — currently unharnessable;
> - ⏳ **rewrite robustness** — the reserve rewrite occasionally emits invalid code on complex functions (e.g. `median_of_medians`'s variant build-failed).

→ **After Phase 2: VERTO produces verified, faster-and-correct patches on real third-party repos — proven on cloned code (jsoncpp: sound, 0 false positives; TheAlgorithms: real verified wins). This is the milestone that makes VERTO *useful* — and the real prerequisite for the LLM.**

### Phase 3 — The AI / LLM  *(needs Phase 2 first)*  ✅ **DONE (v0) — 2026-07-25. All four items shipped: #13 sandbox, #12 cost cap, #10 LLM proposer, #11 multi-candidate. The "AI optimizer" runs end to end on a local Qwen. 105 tests, wedge 14/14.**

**Thesis: the gate makes the LLM safe.** An LLM proposer is normally *dangerous* (hallucinated "optimizations"); here it's safe because the trusted gate rejects any wrong-or-slower change **for free** — so the model becomes a pure **idea generator** whose mistakes are no-ops. `frontier.py` already declares itself UNTRUSTED, and the proposer port is swappable (`--offline` rules vs frontier), so #10 is "fill the stub," not a rebuild. *This is the moment VERTO's whole architecture pays off.*

**Recommended order (revised):** **#13** (sandbox — a hard edge, must land before any generated code runs) → **#12** (cost cap — moved **early**: real API spend needs a hard ceiling from the *first* live call) → **#10** (LLM proposer) → **#11** (multi-candidate).

10. **The LLM proposer** ✅ **done (v0) — 2026-07-25. The "AI optimizer," end to end, running locally.** `frontier.py` is filled: it sends the hot function's **source** (not an AST dump) to a model, gets a whole **rewritten function**, and wraps it as a `VerbatimRewrite` the gate verifies exactly like a hand-coded transform. **`--model local` → a local Ollama** (free, private — *source never leaves the box*, resolving the §7 frontier-API blocker); `--model frontier` → an OpenAI-compatible host. The sensor now offers **any** function as a candidate in LLM mode (not just rule-matched sites). Every call is bounded by the #12 budget (`can_spend`/`charge`). **PROVEN end to end:** on `examples/llm_demo.cpp`, a local **qwen3:1.7b** (a 2B CPU model) rewrote a `push_back` loop → `vector(n)` + indexing — a win the 7 transforms *don't have* — and the gate **ACCEPTED it: Rung 3 (clean), −85.5%, in ~10s.** A cosmetic-only rewrite was correctly **REJECTED** (not faster). Untrusted-by-design: a wrong/slower reply just fails the gate. `tests/test_llm_proposer.py` (mechanism + a live-Qwen smoke test that skips without Ollama). — `runtime/llm.py`, `frontier.py`, `transforms/verbatim.py`, `analysis/detect.py` (`func_span`/`all_functions`), `sensor.py`, `config.py`, `cli/`
    - **Output-shape decision (OPEN):**
        - **(a) free-form rewrite** — the model returns a whole rewritten function, wrapped in a trivial "verbatim" Transform whose `rewrite()` splices it in; the gate verifies it exactly like any `Variant`. → **recommended** (minimal change, unlocks arbitrary wins).
        - **(b) transform-selector** — the model picks + parameterizes one of the existing transforms. Safer/cheaper, but can't exceed the catalog.
    - **Local-model + redaction from day one:** sending proprietary source to a frontier API is a hard blocker for many users (§7). Make `frontier.py` one backend and a **local model** (`ollama`/`llama.cpp`) a drop-in via `--model local`. Cheap now, expensive to retrofit.
    - **Never spend the API key silently** — gate live calls behind an explicit opt-in.
11. **Try several, keep the best verified** ✅ **done (v0) — 2026-07-25.** `--candidates N` draws N rewrites per hotspot (a higher temperature makes them **diverse**; identical variants are deduped), gates each, and **keeps the accepted one with the largest speedup** — so the model can be hit-or-miss and the gate still yields the best hit. Bounded by the #12 per-hotspot budget (`start_hotspot` once, `can_spend` per draw). Rule proposers are deterministic → always 1 draw (no cost). **Proven:** `--model local --candidates 3` on `llm_demo.cpp` → ACCEPT −86%; `tests/test_multicandidate.py` (best-of-N picks the largest Δ, dedups identical, rules stay at N=1). — `orchestrator.py` (`_best_of_n`/`_n_candidates`), `config.py`, `frontier.py`, `cli/`
12. **Cost cap** ◑ **done (v0) — 2026-07-25.** The **budget meter is built and wired** (ahead of the LLM, so #10's first live call is born capped). **Two ceilings** — per-run `--budget` + per-hotspot `--budget-per-hotspot` — each a spec in **tokens** (`500k`/`1M`), **money** (`$2`), or **time** (`90s`/`2min`); prices in config. **The budget is to cost what the gate is to correctness:** a trusted, thread-safe meter (`runtime/budget.py — Budget`) the untrusted proposer consults (`can_spend()`) and charges (`charge(in,out)`). Injected into the proposer + `AdapterSet` via the registry; the `frontier.py` stub already gates its (future) call on it. Inert offline (rules are free). `tests/test_budget.py` (parse units, run cap, per-hotspot reset, money+pricing). *⏳ remaining, lands with #10: the actual `charge()` after each real API call + a per-run spend line in the summary.* — `runtime/budget.py`, `config.py`, `registry.py`, `frontier.py`, `cli/`
13. **⚠ Harden the sandbox — REQUIRED here** ✅ **done (v0) — first Phase-3 task, landed 2026-07-25.**
    - ✅ **network + filesystem:** every untrusted-binary run funnels through `sandbox.run` — correctness check, sanitizers, benchmark, profiler, **and the metamorphic (2D) driver** — now wrapped in **bubblewrap** with **no network** (`--unshare-all`) + a **read-only host filesystem** (only the binary's dir + a writable scratch `cwd` bound).
    - ✅ **memory cap (ASan-safe):** isolated runs get a **hard cgroup memory cap** via `systemd-run --user --scope -p MemoryMax` (default 2 GB). It's **RSS-based, so ASan-safe** — unlike `RLIMIT_AS`, which blocks ASan's huge shadow mmap (and proved unreliable at stopping a bomb anyway). A memory-bomb variant is **OOM-killed inside its cgroup**, sparing the host.
    - ✅ **verify-or-degrade** — without `bwrap`, isolation → rlimits-only; without a `systemd --user` session, the memory cap is skipped. Both surfaced by `verto verify-setup` (`sandbox isolation`, `sandbox memory cap` rows). CPU limit + wall-timeout always on.
    - ✅ **proven:** `tests/test_sandbox_isolation.py` — a variant's `connect()` is **blocked**, a host write **denied**, a ~12 GB **memory bomb OOM-killed** at the cap, benign compute runs; full suite green (**90 tests**) *under* isolation, no delta distortion (the bench times internally).
    - *v0 boundary: the memory cap needs a working `systemd --user` session (present on dev/desktop; a headless-CI path would want a direct cgroup-v2 write). — `runtime/sandbox.py` (`_isolate_prefix`/`_memcap_prefix`/`isolate=`), `correctness.py`, `sanitizers.py`, `bench_runner.py`, `profiler.py`, `metamorphic.py`, `cli/`*

> **Prove it — a "wedge for the LLM" (like Phase 1/2 had).** Phase 3's falsifiable claim is **both**:
>
> - **(a)** the LLM finds a real win the 7 transforms **miss** and the gate verifies it, **and**
> - **(b)** the gate **rejects** the LLM's deliberately-broken proposals.
>
> Without (b) you can't tell "the model is good" from "the gate is quietly catching its garbage." Build this before trusting any accepted LLM change.

> **Strategic fork (§6 — OPEN decision).**
>
> - **Path A** — ship the no-LLM product first: VERTO already produces verified wins, so do a slice of **Phase 4** (CI action + packaging) to get users, *then* the LLM. Lower risk, value now.
> - **Path B** — the LLM now (this phase): the marquee differentiator and the actual "AI optimizer" thesis, but the hardest/longest path.
>
> *Recommendation: the LLM is the differentiator but **not** the bottleneck to value — lean Path A (a Phase-4 slice) first, unless the goal is specifically the research thesis.*

→ **After Phase 3: VERTO proposes optimizations beyond the hand-coded set — the actual "AI optimizer."**

### Milestone — `verto init`: the local performance workspace  *("git for performance")*  ✅ **done (v0) — 2026-07-25**

> **Shipped (v0):** `verto init` creates the `.verto/` workspace (`ledger.jsonl`, `baselines/`, `cache/`, a `model` pointer — **weights never copied in**, they stay in Ollama's global store), auto-adds `.verto/` to `.gitignore`, and writes a committed starter `.verto.toml` (local-first: `model = "local"`). Idempotent — re-running never clobbers the ledger or pointer. It **detects** the local model (Ollama probe) and reports readiness without blocking on a multi-GB download (`--pull` opts in). The **Engine now reads its ledger from `.verto/ledger.jsonl`** when a workspace exists (legacy root `ledger.jsonl` otherwise — nothing breaks pre-init). `engine/workspace.py`, `runtime/llm.py` (`ollama_status`), `cli/` (`init`), `_help.py`; `tests/test_init_workspace.py` (9). **Design fork resolved for v0:** `.verto/` is **local + git-ignored**; the committable-baselines slice ships later *with* prevent-mode (baselines/ is scaffolded now, populated then).

**The idea.** `git init` starts tracking your *source history*; `verto init` starts tracking your **verified performance state** — baselines, accepted optimizations, and the ledger of what's been tried and proven — in a `.verto/` folder that lives in the repo exactly like `.git/`. This turns VERTO from *a command you remember to run* into *a layer that lives in your project*: local, private, inspectable — a product identity a cloud-based optimizer structurally **can't** have, because their model runs in the cloud and your code is uploaded to it.

**Global vs per-project — the load-bearing distinction.** A local model is **gigabytes**, so it must **not** live per-repo:

- **Global** (**not** `~/.verto/`): the model **weights** live once in **Ollama's own store** (`~/.ollama`), shared by every project — `verto init` *ensures availability*, never copies them in. Machine-wide **user defaults** live at **`~/.config/verto/config.toml`** (XDG) — ✅ **built (v0):** `Config.load` layers it *under* the project `.verto.toml` (precedence: project > global > code defaults, the git model); `verto init --global` scaffolds it. XDG-idiomatic and collision-free with the per-project `.verto/` that discovery walks up to find. *(A cross-project shared ledger / transform-library "flywheel" — roadmap Later #23 — is the future global-data tier; deferred.)*
- **Per-project** (`.verto/`, like `.git/`): the ledger, baselines, cache, and a small **pointer** to *which* global model to use. `.verto/` **references** the model; it never contains it.

**`verto init` — idempotent (re-running is safe, like `git init`):**

1. Create `.verto/` → `ledger.jsonl`, `cache/`, `baselines/`, a local `config` (or a pointer to the committed root `.verto.toml`).
2. **Prepare the model** — detect Ollama → `ollama pull <default>` once (global); if absent, print the one-liner, or fall back to the `--model frontier` / env path.
3. Auto-add `.verto/` to `.gitignore`.
4. Optionally **warm the daemon** (`verto serve`) so the *first* `verto optimize` is instant — zero cold start.
5. Print: *"ready → try `verto optimize <file>`."*

**`.verto/` layout (proposed):**

```
.verto/
  config          # local overrides (or a pointer to the root .verto.toml)
  ledger.jsonl    # every accept/reject: transform, rung, measured Δ
  baselines/      # per-function perf baselines — the regression floor
  cache/          # VerifyCtx build cache + ccache dir
  model           # pointer to the GLOBAL model (name + host); not the weights
```

**What it unlocks (why it's more than a convenience):**

- **`verto log` / `verto report` over the ledger** — your optimization history, like `git log`: every verified win, its measured Δ, its rung.
- **Regression prevention (the substrate for prevent-mode).** Baselines in `.verto/baselines/` let VERTO catch *"this PR made `parse()` 20 % slower"* — this is the storage layer that makes the planned **`--mode prevent`** (Surfaces / CI) real.
- **Warm, private, always-ready** — the local model + daemon is there the moment you need it, and nothing leaves the box.

> **Design fork (RESOLVED for v0):** `.verto/` is **purely local & git-ignored** (like `.git/`) — cache and ledger are machine-specific. The **committable slice is deferred**: when prevent-mode lands, a team can share the **regression floor** via one opt-in tracked `verto-baselines.toml` (or an un-ignored `.verto/baselines.toml`) — without committing the whole workspace. Local by default; shared exactly where it matters, later.

**Honest cautions.** Don't block `init` on loading GBs into RAM — *ensure availability* + optionally warm; warm lazily (first optimize) or via the opt-in daemon. And `.verto/` is local state → git-ignore it (mirror `.git/` / `.terraform/`); the *committed* team config stays as the root `.verto.toml`.

**Scope & placement.** Mostly **additive** — it consolidates the ledger / config / cache VERTO already has and adds one `init` command + global-model management. A natural **v0.5 polish**, not a rebuild, and the right **first-run experience** for Phase-4 packaging to build on (so it slots just before it). — `surfaces/cli/` (`init`), `runtime/` (workspace + model mgmt), `engine/config.py`, ledger.

### Phase 4 — Product hardening  *(to ship it, free)*

**Recommended order:** **#15** (tests + CI — protects everything after it) → **#16** (packaging) → **#17** (launch). *(#14 deferred — see below.)*

14. **More transforms** ⏸ **deferred to post-launch (re-scoped) — 2026-07-25.** The "5 → 10–12" *count* was a **pre-LLM** goal; the LLM now covers the long tail, so hand-coding transform #9 is low-ROI vs LLM quality + gate reach. **The existing ~7 rules stay** — they're the reliable, deterministic, **offline floor of the free tier** (they fire correctly every run, where a weak local LLM is hit-or-miss). Post-launch, add a rule *only* when it's a **common** pattern worth a free fast-path or one the **LLM handles poorly** — and the higher-value form is a **tiered proposer** (cheap rules first, LLM on what's left), not a bigger library.
15. **Tests + CI** ✅ **DONE (v0) — GREEN on GitHub Actions, 2026-07-26.** The **test suite already existed** (125 tests + the 14-case wedge); this item was really *CI*. `.github/workflows/ci.yml` runs `pytest` + `wedge` on every push/PR, matrix **Python 3.11 / 3.12**, installs `clang`+sanitizers+`ccache` (cached), live-LLM tests opt-in (no Ollama in CI). **Getting it green surfaced 3 real environment gaps + 2 toolchain-sensitivities — each a genuine robustness fix, all now shipped:** ① **bwrap present-but-broken on runners** (`--unshare-all` net-namespace denied) → `sandbox.isolation_available()` now *probes* (not just presence) → degrades to rlimits; ② **`taskset -c 2` on a 2-core runner** → core-pinning is now affinity-aware (`os.sched_getaffinity`) with an unpinned fallback; ③ **a data race in VERTO's OWN TSan harness** (4 threads accumulating into one shared `sink`) — hidden all along because dev has no TSan runtime — → per-thread `sinks[NT]`; ④ **D1 wedge** memo table `static`→`thread_local` (the memory gate rejects it, not a self-inflicted race); ⑤ **A2 string-reserve** is toolchain-borderline (30% on dev clang-19 vs ~2% on runner clang-18 + `-march=native`). Noise handled by `pytest-rerunfailures` + a wedge retry loop. **⚠ Watch:** A2 passing means its runner delta is *just* over 2% → could flake; if so, heavier workload or reconsider that wedge case. Deeper perf-robustness fix already shipped opportunistically: **interleaved A/B measurement** in `bench_runner.measure_ab`. — `.github/workflows/ci.yml`, `runtime/sandbox.py`, `runtime/bench_runner.py`, `harness/template.py`, `wedge/cases.py`, `pyproject.toml`
16. **Packaging** ✅ **done (v0) — 2026-07-26.** Publishes as **`verto-optimizer`** on PyPI (`verto` was taken; import + CLI stay `verto`), **Apache-2.0** licensed. Full `pyproject.toml` metadata (classifiers, keywords, URLs, extras: `dev`/`llm-openai`/`llm-anthropic`/`keychain`) + `LICENSE` + `NOTICE`. **Wheel builds cleanly** (`verto_optimizer-0.1.0-py3-none-any.whl`, entry point verified). Zero-setup **`Dockerfile`** (bundles clang+sanitizers) + `.dockerignore`. `verto analyze --verify-setup` reports missing tools. `RELEASING.md` documents the build→TestPyPI→PyPI→tag flow. *⏳ remaining (user action): actually publish to PyPI + push the Docker image.* — `pyproject.toml`, `LICENSE`, `NOTICE`, `Dockerfile`, `RELEASING.md`
17. **README + demo + public launch** ◑ **README + demo done (v0) — 2026-07-26.** `README.md` rewritten launch-ready + current (invariant, a "what you get" section, 60-sec quickstart, install via pip/source/Docker, how-it-works, honest beta status). The **demo** is the reproducible quickstart (`verto optimize packet_stats.cpp --offline` → verified −68%) + the wedge as the proof artifact. *⏳ remaining (user action): publish, then **launch** — Show HN / r/cpp with the hook "proves your code correct-and-faster, on your machine."*

### Phase 5 — Commercial  *(to sell it)*

**Recommended order:** **#18** (CI / GitHub Action — the paid surface) → **#19** (hosted) → **#20** (billing) → **#21** (legal + security, running in parallel throughout).

18. **CI / GitHub Action** ◕ **built end-to-end (v0) — 2026-07-27; needs a live PR to fully verify.** Runs on every pull request and comments the verified findings. *The paid surface.* **Explained from scratch (every concept) in [`VERTO_CI_Action.md`](VERTO_CI_Action.md) · [html](VERTO_CI_Action.html).** All four build steps (below) are done; the only thing left is publishing the image once and exercising it against a real PR (needs a GitHub repo + token this machine doesn't have).
    - **✅ Foundation (the hard part):** full interface — `examples/github-action/action.yml` (21 inputs / 6 outputs), `verto.yml` sample, `pr-comment.md` layout, GitLab CI/CD-component twin — **and the CLI already exposes every primitive the Action needs:** `--changed [REF]` (PR-scoped), `--json` (machine-readable findings), `--emit-patches`/`--diff` (suggestion payload), exit codes `0/1/2`. The engine side is done.
    - **✅ Step 1 done (2026-07-27): `--fail-on {none,any}`** — the "prevent mode" (Dial B) exit gate. `none` = always exit 0 (findings advisory); `any` = exit 1 iff a verified optimization was found (a proven speedup left unapplied). Absent flag = legacy codes preserved (0=found/1=none/3=rejected). Restricted `choices` (argparse rejects typos). `regression` (PR-vs-baseline) deferred — needs the baseline-diff feature, so it's **not** an accepted value. Docs/examples/action.yml/GitLab-template all reconciled to `none|any` (was the mislabeled `regression|left-on-table`). — `parser.py`, `render.py` (`_fail_on_exit`), `main.py`, `tests/test_render.py` (10 assertions, green)
    - **✅ Step 2 done (2026-07-27): the `entrypoint` bridge** — `examples/github-action/entrypoint.py` maps the Action's `INPUT_*` env vars → `verto optimize -p <db> --changed <base-ref> --json --fail-on … --model …` (+ min-speedup/min-rung/objectives/jobs/budget/llm-*/metamorphic/config-file/extra-args; `suggest`/`pr` also `--emit-patches`), runs it, reduces the JSON verdict report to the Action outputs (`status`/`findings`/`applied`/`regressions`/`report-json`/`patches`) written to `$GITHUB_OUTPUT`, and **re-emits verto's exit code verbatim so `--fail-on` drives the check.** Network-free (posting is step 3). Off-CI-testable via `VERTO_BIN`. Also fixed: `--emit-patches` notice now prints to **stderr** so it can't corrupt the `--json` stdout the bridge parses. — `entrypoint.py`, `main.py` (`_emit_patches`), `tests/test_action_entrypoint.py` (6 tests incl. a real end-to-end on `examples/linked`: 2 wins → exit 1, green)
    - **✅ Step 3 done (2026-07-27): the PR-comment poster** — split pure/network. `comment.py` (pure, unit-tested) renders the report → the trust-first summary comment (marker-tagged for edit-in-place, findings table, per-finding `<details>` with the "why-safe / why-faster / measured" triplet + ` ```diff `, honest skip footer, and the red `fail-on: any` "left unapplied" header) and extracts one GitHub ` ```suggestion ` per diff hunk (new-side content, anchored to the old-line range). `gh.py` (stdlib `urllib` only — keeps the image minimal) posts/updates the summary and inline suggestions; **fully self-guarding** — no token / not a PR → logs and no-ops, every HTTP error caught, so **delivery can never change the check result** (that's `--fail-on`'s job). Wired into `entrypoint.py` (`_post`, isolated in try/except). *The posting half needs a real repo+token to exercise end-to-end — deliberately kept thin; the rendering it posts is unit-tested.* — `comment.py`, `gh.py`, `entrypoint.py`, `tests/test_action_comment.py` (5 tests, green)
    - **✅ Step 4 done (2026-07-27): `Dockerfile` + GHCR publish pipeline** — `examples/github-action/Dockerfile` (builds from repo root: `python:3.12-slim` + clang/sanitizers + **git** for `--changed` + `pip install .`, then bundles `entrypoint.py`/`comment.py`/`gh.py`, `ENTRYPOINT` = the entrypoint). `.github/workflows/publish-action.yml` builds it and pushes `:vX.Y.Z`/`:vX`/`:latest` to `ghcr.io/<owner>/action` on every version tag (matches `action.yml`'s `runs.image`). *Statically validated (YAML parses, every `COPY` source exists, `verto` console-script resolves); the actual `docker build`/push + `uses:` resolution only prove out on a real runner — no Docker daemon here.* — `Dockerfile`, `publish-action.yml`, `README.md`
    - **Build order:** ✅ (1) `--fail-on` → ✅ (2) `entrypoint` bridge → ✅ (3) PR-comment poster → ✅ (4) `Dockerfile` + GHCR publish. **All four steps built.**
    - **Remaining to ship:** ① **end-to-end proof on a real PR** — publish the image once, run the Action against a live PR (the one thing this machine can't do: needs a GitHub repo + token + a published image); ② deferred features — `mode: pr` auto-PR (logs + falls back to summary+suggestions today) and `fail-on: regression` (needs the baseline-diff feature).
19. **Hosted / cloud** — no local setup for the user; needs a build farm + a shared cache of verified results. **Explained from scratch (every concept) in [`VERTO_Hosted.md`](VERTO_Hosted.md) · [html](VERTO_Hosted.html)** — incl. the privacy trade-off, clean-room benchmarking (the killer value), on-prem-first, and "does it even beat #18?".
20. **Billing, accounts, dashboard** — open-core: the tool is free, the paid tier is CI + cloud + the AI proposer.
21. **Legal + security review** — handling customers' private code (data policy, on-prem option).

> **Model tiering (open-core — decided 2026-07-25).** Capability scales with the model; the **gate keeps every tier safe** (a better model raises the *hit rate*, never affects *correctness* — it re-verifies whatever any model proposes).
>
> - **Free:** deterministic **rules + a local CPU LLM** (Ollama) — 100 % on-box, private, free. The rules are the reliable floor; the local LLM is best-effort extra.
> - **Premium (companies): rules + a strong GPU LLM**, offered as **both** deployment options —
>   - **self-hosted** — their GPU, `--llm-url` → vLLM / TGI / Ollama-on-GPU; **code never leaves the company.** *Ship this first:* ~90 % done (the `--llm-url` plumbing exists), no infra for us, preserves the privacy moat. And
>   - **VERTO-hosted managed** (#19) — our GPU service; **later**, once demand proves out — it carries the infra / uptime / security / legal lift and processes code off-box.
>
> Messaging: *"run it on your infra or ours — either way the gate verifies every change."* **Caution:** the model alone is thin premium value (a company can point `--llm-url` at their own GPU for free). The **moat is the team layer** — the cross-project verified-optimization **flywheel** (shared ledger, Later #23), the **CI action** (#18), dashboard / governance, support. The GPU model is the hook; the verification + team infrastructure is what companies pay for.

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
