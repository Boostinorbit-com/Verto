# BOOSTOPT — Low-Level Design (LLD)

**A code-mapped walkthrough of how BOOSTOPT is actually built — read this alongside the source to navigate the ~5,250-LOC `boostopt/` package.**

Companion to `BOOSTOPT.md` (concept — *why*), `BOOSTOPT_Architecture.md` (blueprint — *what*), `BOOSTOPT_Surfaces.md`/`BOOSTOPT_Flags.md` (the CLI), `BOOSTOPT_Roadmap.md` (state & plan). **This doc is the *how* — the file/class/function map.** Every reference is `path — symbol`, so you can jump straight to the code.

---

## 1. The 60-second mental model

BOOSTOPT takes one function, proposes a change, and **accepts it only if a trusted gate proves it is byte-identical in behavior AND measurably faster.** Everything is organized around one invariant, enforced in exactly one place (`engine/gate.py — InvariantGate.decide`):

```
accept  ⟺  correctness.rung ≥ policy.min_rung   AND   performance.pareto_pass
```

The whole system is a **four-stage loop** driven by `engine/orchestrator.py — Orchestrator.run`:

```
  ┌─────────── one round, per function ───────────────────────────────────┐
  │  1. EVIDENCE   sensor.collect(target) → Evidence   (facts + hotspot)   │
  │  2. PROPOSAL   proposer.propose(ev)   → Candidate  (UNTRUSTED)         │
  │  3. MUTATE     mutator.apply(...)     → Variant    (real source diff)  │
  │  4. VERIFY     gate.decide(...)       → Verdict    (TRUSTED: the gate) │
  │     └─ learn:  ledger.record(episode)                                  │
  └───────────────────────────────────────────────────────────────────────┘
```

**The one idea that makes it safe:** stages 1–3 are **untrusted** (a rule set today, an LLM later — they're allowed to be wrong); stage 4 is the **trusted gate** that re-runs real code to catch every mistake. Get the gate right once and the proposer can be as dumb or as clever as you like.

---

## 2. Layered architecture & the dependency rule

Four layers, **strict inward dependency** — `engine` knows nothing about C++, clang, or the CLI:

```
  surfaces/   CLI · daemon · patch-emitter        (talk to engine.api only)
      │  depends on
      ▼
  engine/     Orchestrator · Gate · Ports · Models · Ledger   ← the trusted core
      ▲  implements the Ports (Protocols)
      │
  adapters/   language/cpp · domain/performance · proposer     (the pluggable parts)
      │  uses
      ▼
  runtime/    sandbox · bench_runner · fs         (OS-level primitives)
```

- **`engine/`** defines *interfaces* (`engine/ports.py`, Python `Protocol`s) and owns the loop + the gate. It imports **no** adapter.
- **`adapters/`** *implement* those interfaces (a `CppSensor`, a `PerfCorrectnessOracle`, …). This is where all language/domain specifics live.
- **`engine/registry.py — resolve()`** is the **only** wiring point: given a file, it picks adapters and hands the orchestrator an `AdapterSet`.
- **`surfaces/`** are thin clients of `engine/api.py — Engine`.

### Directory map (LOC)

| Path | LOC | Role |
|---|---|---|
| `engine/` | ~740 | the trusted core: loop, gate, models, ports, ledger, config, apply |
| `adapters/language/cpp/` | ~1,900 | everything C++: sensing, parsing, transforms, building, linking |
| `adapters/domain/performance/` | ~800 | the correctness + performance oracles (the two halves of the gate) |
| `adapters/proposer/` | ~70 | rule proposer (offline) + frontier-LLM stub |
| `surfaces/` | ~730 | CLI, daemon, patch series |
| `runtime/` | ~120 | sandbox, benchmark runner, temp-file naming |

---

## 3. The data model — `engine/models.py`

These plain dataclasses are the **only** things that cross layer boundaries. Learn these and the call flow reads itself.

| Type | Key fields | Produced by → consumed by |
|---|---|---|
| `Target` | `file, symbol, line, build, verify_mode` | CLI/api → sensor; the code under optimization. `verify_mode` = `"harness"` \| `"tests"` (2A) |
| `Evidence` | `target, source, facts, profile, skips` | `sensor.collect` → proposer; the reasoning input + honest skip list |
| `Skip` | `func, reason, stage` | sensor → surfaces; a site seen but not optimized, with *why* |
| `Candidate` | `transform, contract, rationale` | `proposer.propose` → mutator/gate; **UNTRUSTED** |
| `Variant` | `target, patch, source_after` | `mutator.apply` → gate; the real compilable artifact |
| `CorrectnessVerdict` | `rung, passed, witness` | correctness oracle → gate; `rung` = highest ladder level passed |
| `PerfVerdict` | `vector{p50,p99,peak_memory,…}, pareto_pass, reason` | performance oracle → gate |
| `Verdict` | `accepted, correctness, performance, reason, diff, udiff, applied, via, metamorphic` | **gate → every surface**; the one payload all UIs render |
| `Episode` | `evidence, candidate, verdict` | orchestrator → ledger (learning log) |
| `Priors` | `accepted_transforms, rejected_transforms` | ledger → proposer (recall) |
| `VerifyCtx` | `workdir, cache, extra_cflags, link_inputs, opt_flags` | gate → both oracles; **shared build cache** (compile once, reuse) |

---

## 4. End-to-end trace: `boostopt optimize foo.cpp`

Follow one command through the code:

```
surfaces/cli/__main__.py                         entrypoint
 └─ surfaces/cli/main.py — main() → handle_argv() → _run_command()
     ├─ parser.py — _parser()          parse argv
     ├─ config_build.py — _build_config()   argv → Config
     ├─ (daemon.py — try_client()       hand off to a warm daemon if running)
     └─ engine/api.py — Engine.optimize(file)
         └─ Engine._run()
             ├─ registry.py — resolve(file, cfg) → AdapterSet   (pick + wire adapters)
             ├─ Orchestrator(adapters, ledger).run(target)      ← THE LOOP
             │   ├─ 1. adapters.sensor.collect(target)  → Evidence
             │   ├─ 2. ledger.recall(ev)                → Priors
             │   ├─ 3. adapters.proposer.propose(ev)    → Candidate
             │   ├─    _precondition_holds(cand, ev)    (legality pre-check)
             │   ├─ 4. adapters.mutator.apply(...)      → Variant
             │   ├─ 5. adapters.gate.decide(...)        → Verdict   ← TRUSTED
             │   ├─ 6. ledger.record(Episode)
             │   └─ 7. if accepted & apply: txn.write(...)   (ApplyTransaction)
             └─ returns list[Verdict]
     └─ render.py — _render_human()/_render_json()     print the verdicts
```

Codebase mode (`--all` / `-p`) is the same loop wrapped by `Engine.optimize_codebase` (parallel over TUs via `--jobs`, one shared `ApplyTransaction`).

---

## 5. Engine core — `engine/`

The trusted, language-agnostic heart.

### `engine/gate.py — InvariantGate` (the single ACCEPT decision)
The **only** place `accepted=True` is returned. `decide()`:
1. Builds a `VerifyCtx` (one workdir + build cache shared by both oracles).
2. If `orig.verify_mode == "tests"` → `_decide_via_tests()` (the 2A path; correctness = project tests, perf = project bench).
3. Otherwise: `correctness.equivalent()` — reject if not `passed` (build fail vs `changed_output`) or `rung < min_rung` (`"unsafe"`).
4. `performance.compare()` — reject if `not pareto_pass` (`"slower"`).
5. **2D** (opt-in): `metamorphic.check()` — reject if a property the original had is broken.
6. **#3** (opt-in): `reuse.confirm()` — the project's own tests re-confirm.
7. Return `Verdict(accepted=True, reason="accepted")`.

### `engine/orchestrator.py — Orchestrator.run`
Owns iteration (`max_rounds`), in-run dedup (`tried_here`), stop conditions (2 no-accepts), and — after an accepted+sound change — writes via the transaction and re-profiles the mutated source. `_unified_diff()` builds the real git-apply-able patch (`Verdict.udiff`, used by 2C).

### The rest
| File — symbol | Responsibility |
|---|---|
| `engine/api.py — Engine` | public API: `analyze` / `optimize` / `optimize_codebase` / `report`. `_git_changed()` powers `--changed`; `optimize_codebase(on_done=…)` fires a per-TU progress callback. `Engine` reads its ledger from `workspace.ledger_path()` |
| `engine/workspace.py` | the `.boostopt/` per-project workspace (`boostopt init`): `find()`/`ledger_path()` (git-style walk-up), `init()`, `gitignore_add()`, `write_starter_config()` (root `.boostopt.toml`), `write_global_config()` (XDG). Model *pointer* only — weights stay in Ollama |
| `engine/registry.py — resolve()` | the wiring point: file → `AdapterSet`. Injects `reuse` (#3) and `metamorphic` (2D) into the gate |
| `engine/ports.py` | the 6 `Protocol`s: `Sensor, Proposer, Mutator, CorrectnessOracle, PerformanceOracle, Ledger` — the contract adapters satisfy |
| `engine/ledger.py — JsonlLedger` | append-only `record()` + `recall()` (priors) — the learning log |
| `engine/apply_txn.py — ApplyTransaction` | atomic, all-or-nothing `--apply`: snapshot → `os.replace` writes → `rollback()`/`commit()`; refuses a stale file (#9) |
| `engine/config.py — Config` | the gate policy + all knobs; `Config.load()` **layers** global `~/.config/boostopt/config.toml` (XDG) under the project `.boostopt.toml` (precedence: project > global > defaults) |

---

## 6. Stage 1 — Sensor / Evidence (`adapters/language/cpp/`)

Turns a `Target` into `Evidence`: which function to optimize + honest skips.

### `sensor.py — CppSensor.collect` (generic over transforms)
The key design: the sensor does **not** hardcode detectors. Candidate functions are the **union of every transform's `candidates(source)`**:
```python
candidates = set()
for t in ALL:                # ALL = the transform registry
    candidates.update(t.candidates(source))
```
Then a **skip cascade** keeps only what it can verify, recording *why* for the rest:
- `harness.unsupported_reason` — signature the synth harness can't build (→ SKIP, or route to 2A test-mode if `test_command` set)
- `regex_detect.detect_side_effect_reason` — touches a global / does I/O (#1c)
- `detect_parse_errors` — the TU wouldn't parse
- `detect_template_candidates` — optimizable but needs a concrete instantiation (#1d)

Finally **profile-guided selection** (`profile.py` / `profiler.py`) picks the *hot* candidate and sets `target.symbol`.

### AST analysis — `analysis/` (libclang)
| File | Owns |
|---|---|
| `analysis/parse.py` | libclang TU creation, **thread-local** parse flags (`set_parse_args`), `_infile_funcs`, `parse_errors` |
| `analysis/detect.py` | every **site detector**: `all_growth` (vector reserve), `all_string_growth`, `all_map`, `all_umap_growth`, `all_list`, `all_fuse` (count+at), `byval_params` — each returns a `*Site` with source offsets |
| `analysis/types.py` | `signature()`, `aggregate_fields()` (for POD-struct input synthesis) |
| `analysis/safety.py` | `side_effect_reason()` (#1c), `template_candidates()` (#1d) |
| `regex_detect.py` | the **public detector API** (`detect_*`) + the `*Site` dataclasses. AST-first with a regex fallback so it degrades gracefully without libclang |

### Codebase-mode plumbing
| File | Owns |
|---|---|
| `compile_db.py` | parse `compile_commands.json` → `TU` list; extract `-I/-D/-std` + `-O/-march` flags |
| `link.py — project_archive` | compile the *other* TUs into a cached static archive so the harness links against real dependencies (#1) |
| `cmake_ctest.py — discover_ctest` | **2A-1**: enumerate ctest, `nm`-map which tests exercise the target TU, derive test/bench commands |

---

## 7. Stage 2 — Proposer + Mutator

### Proposer (`adapters/proposer/`) — UNTRUSTED
| File — class | What |
|---|---|
| `rules.py — RuleProposer` | the `--offline` path: offer the first registered transform whose pattern `matches()` the chosen function. Deterministic |
| `frontier.py — FrontierProposer` | the LLM backend — a **stub today** (`raise NotImplementedError`); Phase 3 fills `_render_context` + `_parse_candidate` |

### Transforms (`adapters/language/cpp/transforms/`)
Each transform is self-contained: detect its own site + rewrite source. `base.py — Transform` defines the contract:
- `candidates(source)` → function names it can act on (the sensor unions these)
- `bind(func)` → scope to one function · `matches(source)` → pattern present? · `rewrite(source)` → `(new_source, patch)` · `contract()` → legality precondition

**The 7 shipped transforms** (registered in `transforms/__init__.py — ALL`):

| Transform | File | Rewrite |
|---|---|---|
| `reserve_before_pushback` | `reserve.py` | insert `v.reserve(n)` before a push_back loop |
| `reserve_string` | `reserve.py` | insert `s.reserve(n)` before a `+=` loop |
| `reserve_unordered_map` | `reserve.py` | insert `m.reserve(n)` before an insert loop |
| `map_to_unordered_map` | `map_to_unordered_map.py` | `std::map` → `std::unordered_map` |
| `list_to_vector` | `list_to_vector.py` | `std::list` → `std::vector` (refuses `push_front`/`splice`) |
| `fuse_map_lookup` | `fuse_map_lookup.py` | `if(m.count(k)) …m.at(k)` → one `find(k)` |
| `pass_by_const_ref` | `pass_by_const_ref.py` | heavy value param → `const&` |

### Mutator — `mutator.py — CppMutator.apply`
Generic: calls `transform.rewrite(source)` and wraps the result in a `Variant(patch, source_after)`. No transform logic lives here.

---

## 8. Stage 4a — Correctness oracle (`adapters/domain/performance/`)

`correctness.py — PerfCorrectnessOracle.equivalent` orchestrates the **correctness ladder** (the higher the rung, the stronger the proof):

| Rung | Check | Code |
|---|---|---|
| **1** | **differential test** — run original + variant on held-out + fuzzed inputs (`check` mode), compare outputs | `harness/` + `compare.py` + `inputs.py` |
| **3** | **sanitizers** — rebuild the variant with ASan/UBSan (+ TSan `race` mode, #1a) and run; any diagnostic → fail | `sanitizers.py` + `build/toolchain.py` |
| **2** | *(2D)* **metamorphic** property (permutation invariance) — opt-in, rejects-only | `metamorphic.py` |

Supporting cast:
| File — symbol | Role |
|---|---|
| `harness/template.py — generate` | assemble the self-contained C++ program with 3 modes (`check`/`race`/`bench`). `_neutralize_main` renames a real file's own `main()` so it doesn't collide with the driver |
| `harness/synth.py` | **input synthesis** — build values for primitives, `vector<primitive>`, `string`, simple aggregates; `unsupported_reason` reports what it *can't* build |
| `sanitizers.py — submit_builds/evaluate` | compile + run the sanitizer builds, summarize diagnostics |
| `compare.py — _outputs_match` | output equality (with `--fp-tolerance`, #1b) + `_first_diff` witness |
| `inputs.py — HeldOutInputs` | fixed edge cases + seeded fuzzed sizes (`--fuzz`/`--seed`, #7) |
| `reuse.py — TestReuseOracle` | **2A**: `confirm()` runs the project's own tests; `bench()` + `_pareto()` = the project-level perf gate (p50/p99/peak) |
| `metamorphic.py — MetamorphicOracle` | **2D**: builds a driver that checks `f(v) == f(shuffle(v))` on orig vs variant |

---

## 9. Stage 4b — Performance oracle

`performance.py — PerformanceOracleImpl.compare`:
1. `_verify.py — get_or_build_pair` — build (or **reuse from `VerifyCtx.cache`**) the original + variant binaries.
2. `runtime/bench_runner.py — measure` — warmup + adaptive reps, core-pinned, capture `{p50, p99, peak_memory (VmHWM), binary_size}`.
3. `_pareto()` — the Pareto rule: **≥1 objective improves past `min_speedup` AND none regresses past its budget** (`allow_regression`).

### Build subsystem — `adapters/language/cpp/build/`
| File — symbol | Role |
|---|---|
| `compile.py — compile_program` | compile a program; **content-addressed exe cache** + `ccache` + a fast linker (`mold`/`lld`/`gold`) — a repeat build is a hardlink |
| `compile.py — compile_pair` | build orig + variant together | 
| `toolchain.py` | probe a working ASan/UBSan/TSan/MSan toolchain (verify-or-skip) |

---

## 10. Surfaces & runtime

### `surfaces/`
| File — symbol | Role |
|---|---|
| `cli/main.py — main/_run_command` | dispatch: report / analyze / optimize / serve / list-transforms / verify-setup |
| `cli/parser.py — _parser` | argparse spec (all flags); generates the help cheatsheet |
| `cli/config_build.py — _build_config` | argv → `Config` (incl. `--ctest-dir` discovery wiring) |
| `cli/render.py` | `_render_human` (the verification box) / `_render_json` / `_render_codebase` / exit codes |
| `daemon.py — serve/try_client` | a warm background process (Python + libclang loaded once) over a unix socket — skips startup cost |
| `patches.py — emit_patches` | **2C**: ranked `REPORT.md` + numbered git-apply-able `.patch` series |

### `runtime/`
| File — symbol | Role |
|---|---|
| `bench_runner.py — measure` | the timing harness: core-pin, warmup, reps, p50/p99, peak RSS |
| `sandbox.py — run` | subprocess + `RLIMIT_CPU` + wall-timeout (Phase 3 #13 hardens this: fs/net isolation, memory cap) |
| `fs.py — unique_tmp` | collision-free temp names (pid + thread id) for `--jobs` safety |

---

## 11. Cross-cutting patterns (worth internalizing)

- **The trust boundary.** Untrusted: `sensor`, `proposer`, `mutator`, all transforms. Trusted: `gate` + both oracles + `ledger` + `apply_txn`. A bug in an untrusted part yields a *rejected* proposal, never a wrong accept.
- **`VerifyCtx` build cache.** The gate compiles the orig/variant **once** and both oracles reuse the binaries (`_verify.get_or_build_pair`) — correctness and performance don't each pay a build.
- **Generic sensor.** Adding a transform touches ~1 file: a detector in `analysis/detect.py`, a subclass in `transforms/`, and a line in `ALL`. The sensor is untouched because it unions `candidates()`.
- **Package-with-reexport.** Big modules were split into packages (`analysis/`, `build/`, `harness/`, `cli/`) whose `__init__` re-exports the public names, so old importers keep working.
- **AST-first, regex-fallback.** `regex_detect.py` prefers the libclang detectors in `analysis/` but degrades to regex, so the tool runs without a perfect libclang.

---

## 12. Extension points — where to add things

| To add… | Touch |
|---|---|
| **a transform** | `analysis/detect.py` (a `*_in_fn`/`all_*` detector) + `regex_detect.py` (public `detect_*`) + `transforms/<name>.py` (a `Transform` subclass) + `transforms/__init__.py` (`ALL`). Sensor/gate untouched |
| **a language** | a new `adapters/language/<lang>/` implementing `Sensor` + `Mutator`, plus a domain oracle pair; wire it in `registry.py — language_of/resolve` |
| **a correctness rung** | extend `correctness.py — equivalent` + a checker module; set the `CorrectnessVerdict.rung` |
| **a surface** | a thin client of `engine/api.py — Engine`; render the `Verdict` payload. No engine change |

---

## 13. Full file index (one line each)

**engine/** — `api.py` public Engine · `orchestrator.py` the loop · `gate.py` the ACCEPT decision · `models.py` data schemas · `ports.py` interfaces · `registry.py` wiring · `ledger.py` learning log · `apply_txn.py` atomic apply · `config.py` policy/knobs.

**adapters/language/cpp/** — `sensor.py` Evidence · `mutator.py` apply transform · `regex_detect.py` public detectors + Site types · `compile_db.py` compile_commands · `link.py` project archive · `cmake_ctest.py` 2A-1 discovery · `profile.py`/`profiler.py` hotspot selection · `analysis/` (parse·detect·types·safety) · `build/` (compile·toolchain) · `transforms/` (base + 7).

**adapters/domain/performance/** — `correctness.py` the ladder · `performance.py` the Pareto gate · `harness/` (template·synth) · `sanitizers.py` · `compare.py` · `inputs.py` · `reuse.py` 2A · `metamorphic.py` 2D · `_verify.py` build-cache.

**adapters/proposer/** — `rules.py` offline · `frontier.py` LLM stub.

**surfaces/** — `cli/` (main·parser·config_build·render) · `daemon.py` · `patches.py` 2C · `_help.py`.

**runtime/** — `bench_runner.py` · `sandbox.py` · `fs.py`.

---

*This LLD maps the code as built; the *why* lives in `BOOSTOPT.md`, the *what* in `BOOSTOPT_Architecture.md`. When the code and this doc disagree, the code wins — grep the symbol and update this map.*
